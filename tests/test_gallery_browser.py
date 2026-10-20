"""Gallery (MCP Apps view) in a real browser: host handshake, strict default CSP, hostile payloads.
Skipped when Playwright/Chromium are not installed. Usage: python tests/make_fake_library.py && python tests/test_gallery_browser.py"""
import os, sys, tempfile
here_dir = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("CALIBRE_LIBRARY", os.path.join(here_dir, "Calibre Library"))
os.environ.setdefault("CALIBRE_MCP_DATA", tempfile.mkdtemp())
try:
    from playwright.sync_api import sync_playwright  # noqa: F401
except ImportError:
    print("SKIP: playwright not installed"); sys.exit(0)
import json, base64
sys.argv = ["x"]; sys.path.insert(0, os.path.dirname(here_dir))
from pathlib import Path
from PIL import Image as PIL, ImageDraw
import calibre_mcp as m
m.set_libraries([Path(os.environ["CALIBRE_LIBRARY"])], Path(os.environ["CALIBRE_MCP_DATA"]))
# a recognisable cover for the fixture book
cov = m._cover_path(1); im = PIL.new("RGB", (600, 900), (24, 60, 110)); d = ImageDraw.Draw(im)
d.rectangle([40, 40, 560, 860], outline=(240, 200, 60), width=12); d.text((80, 420), "SICUREZZA DELLE RETI", fill=(255, 255, 255)); im.save(cov, "JPEG")
res = m.calibre_show_images([m.ImageRef(book_id=1)], title="Covers")
sc = getattr(res, "structured_content", None) or getattr(res, "structuredContent")
evil_svg = base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg" onload="parent.postMessage({pwned:1},\'*\')"/>').decode()
sc["images"].append({"label": "<img src=x onerror=\"window.__xss=1\">Evil", "sublabel": "<b>bold?</b>", "mime": "image/jpeg",
                     "data": sc["images"][0]["data"], "alt": "x"})
sc["images"].append({"label": "svg payload", "mime": "image/svg+xml", "data": evil_svg})
sc["images"].append({"label": "bad base64", "mime": "image/png", "data": "\"><script>window.__xss=2</script>"})
gallery = (Path(os.path.dirname(here_dir), "mcpcalibre", "ui", "gallery.html")).read_text()
csp = ("<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; script-src 'self' 'unsafe-inline'; "
       "style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' data:; connect-src 'none';\">")
gallery = gallery.replace("<head>", "<head>" + csp, 1)
host = """<!doctype html><html><body style="margin:0;background:#101010">
<iframe id="v" sandbox="allow-scripts" style="width:720px;height:200px;border:0"></iframe>
<script>
const log = []; window.__log = log;
const f = document.getElementById('v');
const SC = %s;
window.addEventListener('message', (ev) => {
  if (ev.source !== f.contentWindow) return;
  const m = ev.data; log.push(m.method || ('response:' + m.id));
  if (m.pwned) window.__pwned = 1;
  const reply = (result) => f.contentWindow.postMessage({jsonrpc:'2.0', id:m.id, result}, '*');
  if (m.method === 'ui/initialize') {
    window.__init = m.params;
    reply({protocolVersion:'2026-01-26', hostInfo:{name:'test-host',version:'1'}, hostCapabilities:{},
           hostContext:{theme:'dark', styles:{variables:{'--color-background-secondary':'#202830'}}, displayMode:'inline'}});
  } else if (m.method === 'ui/notifications/initialized') {
    f.contentWindow.postMessage({jsonrpc:'2.0', method:'ui/notifications/tool-input', params:{arguments:{}}}, '*');
    f.contentWindow.postMessage({jsonrpc:'2.0', method:'ui/notifications/tool-result',
      params:{content:[{type:'text', text:'summary'}], structuredContent: SC}}, '*');
  } else if (m.method === 'ui/notifications/size-changed') {
    window.__size = m.params; f.style.height = m.params.height + 'px';
  }
});
f.srcdoc = %s;
</script></body></html>""" % (json.dumps(sc).replace("</", "<\\/"), json.dumps(gallery).replace("</", "<\\/"))
Path(tempfile.gettempdir(), "calibre_mcp_host.html").write_text(host)

from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 760, "height": 1400})
    errors = []; pg.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    pg.goto(Path(tempfile.gettempdir(), "calibre_mcp_host.html").as_uri()); pg.wait_for_timeout(1500)
    fr = pg.frame_locator("#v")
    init = pg.evaluate("window.__init"); log = pg.evaluate("window.__log"); size = pg.evaluate("window.__size")
    FAILS = []
    def check(label, cond, detail=""):
        print(("PASS " if cond else "FAIL ") + label + ("" if cond else f"  -> {detail}"))
        FAILS.append(label) if not cond else None
    check("handshake order", log[:3] == ["ui/initialize", "ui/notifications/initialized", "ui/notifications/size-changed"], log)
    check("initialize params", init["protocolVersion"] == "2026-01-26" and "appInfo" in init, init)
    n_img = fr.locator("figure img").count()
    decoded = pg.evaluate("""() => [...document.getElementById('v').contentDocument?.querySelectorAll('figure img') || []].map(i => i.naturalWidth)""")
    check("only png/jpeg base64 rendered", n_img == 2, n_img)
    w = fr.locator("figure img").first.evaluate("i => i.naturalWidth")
    check("image decodes under the spec's default CSP", w == 600, w)
    labels = fr.locator("figcaption .t").all_inner_texts()
    check("captions rendered as text", labels[1].startswith("<img src=x"), labels)
    check("no XSS from captions/data", pg.evaluate("window.__xss || null") is None and fr.locator("figcaption img").count() == 0
          and pg.evaluate("window.__pwned || null") is None)
    check("host theme applied", fr.locator("html").get_attribute("data-theme") == "dark")
    check("size reported to host", size and size["height"] > 100, size)
    check("no console errors / CSP violations", not errors, errors[:3])
    # The shared view receives quotation text in result _meta, never structuredContent.
    quote_text = '<script>window.__quote_xss = 1</script>\nA fictional passage, with  exact spacing.'
    quote_result = {"structuredContent": {"count": 1, "references": [{"book_id": 1}]},
                    "_meta": {"calibreQuotes": {"title": "Quotes", "passages": [{
                        "book_id": 1, "format": "EPUB", "offset": 0, "end_offset": len(quote_text),
                        "label": "<b>Book title</b>", "authors": ["A fictional author"], "text": quote_text}]}}}
    def deliver(result):
        pg.evaluate("""r => document.getElementById('v').contentWindow.postMessage(
            {jsonrpc:'2.0', method:'ui/notifications/tool-result', params:r}, '*')""", result)
    deliver(quote_result)
    fr.locator("blockquote").wait_for()
    check("quotes: view metadata renders exact text", fr.locator("blockquote").text_content() == quote_text)
    check("quotes: no executable markup", fr.locator("blockquote script").count() == 0
          and fr.locator("html").evaluate("() => window.__quote_xss || null") is None)
    check("quotes: attribution is text", fr.locator("figcaption .t").text_content() == "<b>Book title</b>"
          and "A fictional author" in fr.locator("figcaption").text_content())
    check("quotes: reuses frame without images", fr.locator("figure img").count() == 0)
    deliver({"structuredContent": quote_result["structuredContent"]})
    fr.locator("#msg").filter(has_text="did not forward quotation view metadata").wait_for()
    check("quotes: stripped metadata has an explicit message", fr.locator("blockquote").count() == 0)
    deliver({"structuredContent": sc})
    fr.locator("figure img").first.wait_for()
    check("quotes: image view still works after quotations", fr.locator("figure img").count() == 2
          and fr.locator("#title").text_content() == "Covers")
    check("quotes: no console errors / CSP violations", not errors, errors[:3])
    b.close()
    print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    sys.exit(1 if FAILS else 0)

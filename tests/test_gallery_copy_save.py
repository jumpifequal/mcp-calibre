"""Gallery Copy PNG / Save PNG in a real browser, against four host behaviours (MCP Apps):
  A host grants nothing special, supports ui/download-file      -> host saves a real PNG
  B host without ui/download-file, frame may download           -> native download of a real PNG
  C opaque-origin sandbox (clipboard permission impossible)     -> selection-copy fallback (HTML with image)
  D dedicated view origin + clipboard-write delegated           -> Clipboard API holds a real image/png
Skipped when Playwright/Chromium are missing. Usage: python tests/make_fake_library.py && python tests/test_gallery_copy_save.py"""
import base64, functools, http.server, io, json, os, sys, tempfile, threading
from pathlib import Path
here = Path(__file__).resolve().parent
sys.argv = ["x"]; sys.path.insert(0, str(here.parent))
os.environ.setdefault("CALIBRE_LIBRARY", str(here / "Calibre Library"))
os.environ.setdefault("CALIBRE_MCP_DATA", tempfile.mkdtemp())
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("SKIP: playwright not installed"); sys.exit(0)
from PIL import Image as PIL
import calibre_mcp as m

FAILS = []
def check(label, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + label + ("" if cond else f"  -> {detail}"))
    FAILS.append(label) if not cond else None
def png_info(b):
    return b[:8] == b"\x89PNG\r\n\x1a\n", PIL.open(io.BytesIO(b)).size

m.set_libraries([Path(os.environ["CALIBRE_LIBRARY"])], Path(os.environ["CALIBRE_MCP_DATA"]))
PIL.new("RGB", (600, 900), (24, 60, 110)).save(m._cover_path(1), "JPEG")   # JPEG source: exercises PNG conversion
res = m.calibre_show_images([m.ImageRef(book_id=1)])
sc = getattr(res, "structured_content", None) or getattr(res, "structuredContent")
check("server provides a .png filename", sc["images"][0]["filename"] == "1-sicurezza-delle-reti-cover.png", sc["images"][0].get("filename"))
gallery = (here.parent / "mcpcalibre" / "ui" / "gallery.html").read_text()
csp = ("<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; script-src 'self' 'unsafe-inline'; "
       "style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' data:; connect-src 'none';\">")
gallery = gallery.replace("<head>", "<head>" + csp, 1)

web, view_dir = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
(view_dir / "view.html").write_text(gallery)
class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass
def serve(d):
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(d)))
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s
srv, srv2 = serve(web), serve(view_dir)
base, view_origin = f"http://localhost:{srv.server_address[1]}", f"http://127.0.0.1:{srv2.server_address[1]}"
def host_page(name, sandbox, allow, caps, src=None):
    load = f"f.src = {json.dumps(src)};" if src else "f.srcdoc = " + json.dumps(gallery).replace("</", "<\\/") + ";"
    (web / name).write_text("""<!doctype html><html><body>
<iframe id="v" sandbox="%s" allow="%s" style="width:720px;height:700px;border:0"></iframe>
<script>
window.__dl = null; const f = document.getElementById('v'); const SC = %s; const CAPS = %s;
window.addEventListener('message', (ev) => {
  if (ev.source !== f.contentWindow) return;
  const m = ev.data; const reply = (r) => f.contentWindow.postMessage({jsonrpc:'2.0', id:m.id, result:r}, '*');
  if (m.method === 'ui/initialize') reply({protocolVersion:'2026-01-26', hostInfo:{name:'h',version:'1'}, hostCapabilities: CAPS, hostContext:{}});
  else if (m.method === 'ui/notifications/initialized')
    f.contentWindow.postMessage({jsonrpc:'2.0', method:'ui/notifications/tool-result', params:{structuredContent: SC}}, '*');
  else if (m.method === 'ui/download-file') { window.__dl = m.params; reply({}); }
});
%s
</script></body></html>""" % (sandbox, allow, json.dumps(sc).replace("</", "<\\/"), json.dumps(caps), load))
host_page("a.html", "allow-scripts", "", {"downloadFile": {}})
host_page("b.html", "allow-scripts allow-downloads", "", {})
host_page("c.html", "allow-scripts", "", {})
host_page("d.html", "allow-scripts allow-same-origin", "clipboard-write", {}, src=view_origin + "/view.html")
READ_PNG = """async () => { const it = (await navigator.clipboard.read())[0];
  if (!it.types.includes('image/png')) return {types: it.types};
  const a = new Uint8Array(await (await it.getType('image/png')).arrayBuffer()); let s=''; for (const x of a) s += String.fromCharCode(x);
  return {types: it.types, b64: btoa(s)}; }"""
READ_HTML = """async () => { const it = (await navigator.clipboard.read())[0];
  const h = it.types.includes('text/html') ? await (await it.getType('text/html')).text() : '';
  return /<img[^>]+src="data:image\\/(png|jpeg);base64,/.test(h); }"""
with sync_playwright() as p:
    br = p.chromium.launch()
    ctx = br.new_context(); pg = ctx.new_page(); pg.goto(base + "/a.html"); pg.wait_for_timeout(800)
    fr = pg.frame_locator("#v"); fr.get_by_role("button", name="Save PNG").click(); pg.wait_for_timeout(600)
    dl = pg.evaluate("window.__dl")
    r = dl and dl["contents"][0]["resource"]
    check("A: Save uses ui/download-file when the host supports it", r and r["mimeType"] == "image/png" and r["uri"].endswith(".png"), dl)
    check("A: host receives a real PNG (JPEG converted)", r and png_info(base64.b64decode(r["blob"])) == (True, (600, 900)))
    ctx.close()
    ctx = br.new_context(accept_downloads=True); pg = ctx.new_page(); pg.goto(base + "/b.html"); pg.wait_for_timeout(800)
    fr = pg.frame_locator("#v")
    with pg.expect_download(timeout=5000) as d:
        fr.get_by_role("button", name="Save PNG").click()
    check("B: native download fallback saves a real PNG", png_info(Path(d.value.path()).read_bytes()) == (True, (600, 900))
          and d.value.suggested_filename.endswith(".png"))
    ctx.close()
    ctx = br.new_context(); ctx.grant_permissions(["clipboard-read"], origin=base)
    pg = ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(base + "/c.html"); pg.wait_for_timeout(800); fr = pg.frame_locator("#v")
    fr.get_by_role("button", name="Copy PNG").click(); pg.wait_for_timeout(600)
    check("C: opaque sandbox falls back to selection copy (image in HTML)", pg.evaluate(READ_HTML), fr.locator(".st").first.inner_text())
    check("C: no script errors", not errs, errs)
    ctx.close()
    ctx = br.new_context()
    for o in (base, view_origin):
        ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=o)
    pg = ctx.new_page(); pg.goto(base + "/d.html"); pg.wait_for_timeout(1200); fr = pg.frame_locator("#v")
    fr.get_by_role("button", name="Copy PNG").click(); pg.wait_for_timeout(600)
    clip = pg.evaluate(READ_PNG)
    check("D: Clipboard API holds a real image/png", "b64" in clip and png_info(base64.b64decode(clip["b64"])) == (True, (600, 900)), clip.get("types"))
    ctx.close(); br.close()
srv.shutdown(); srv2.shutdown()
print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
sys.exit(1 if FAILS else 0)

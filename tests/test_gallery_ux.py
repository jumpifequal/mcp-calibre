"""Real-browser UX checks. No Calibre fixture or running server required.

Run: python tests/test_gallery_ux.py
Set PLAYWRIGHT_CHANNEL=msedge (or chrome) to use an installed browser.
"""
import base64
import io
import json
import os
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw
from playwright.sync_api import expect, sync_playwright


def main():
    buffer = io.BytesIO()
    image = Image.new("RGB", (1400, 1200), "#eef3f7")
    draw = ImageDraw.Draw(image)
    for x in range(0, 1400, 100):
        draw.line((x, 0, x, 1200), fill="#6c8195", width=2)
    for y in range(0, 1200, 100):
        draw.line((0, y, 1400, y), fill="#6c8195", width=2)
    draw.text((30, 30), "Example diagram - received resolution: 1400 x 1200", fill="#172f46")
    image.save(buffer, "PNG")
    payload = {"title": "Figures", "images": [{
        "book_id": 7, "library": "secondary", "format": "EPUB",
        "label": "Example book", "sublabel": "Figure 1 - Example diagram", "mime": "image/png",
        "data": base64.b64encode(buffer.getvalue()).decode(), "filename": "example.png",
    }]}
    gallery = (Path(__file__).resolve().parents[1] / "mcpcalibre/ui/gallery.html").read_text("utf-8")
    gallery = gallery.replace("<head>", '<head><meta http-equiv="Content-Security-Policy" '
        'content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; '
        'img-src data:; connect-src \'none\';">', 1)
    host = """<!doctype html><html><body style="margin:0">
    <iframe id="v" sandbox="allow-scripts" style="width:720px;height:600px;border:0"></iframe>
    <textarea aria-label="Chat message" style="display:block;width:700px;height:60px"></textarea>
    <script>
    const f = document.getElementById('v');
    window.payload = PAYLOAD; window.downloads = 0; window.readerCalls = [];
    const bookText = BOOKTEXT;
    window.deliver = result => f.contentWindow.postMessage({jsonrpc:'2.0',
      method:'ui/notifications/tool-result', params:result}, '*');
    window.addEventListener('message', ev => {
      if (ev.source !== f.contentWindow) return;
      const m = ev.data;
      const reply = result => f.contentWindow.postMessage({jsonrpc:'2.0',id:m.id,result}, '*');
      if (m.method === 'ui/initialize') reply({protocolVersion:'2026-01-26',
        hostCapabilities:{downloadFile:{}},hostContext:{theme:'light'}});
      else if (m.method === 'ui/notifications/initialized') {
        window.initialized = true;
        if (location.hash !== '#missing') window.deliver({structuredContent:window.payload});
      }
      else if (m.method === 'ui/notifications/size-changed') f.style.height = m.params.height + 'px';
      else if (m.method === 'ui/download-file') {
        window.downloads++;
        if (!window.holdDownload) reply({});
      }
      else if (m.method === 'tools/call') {
        window.readerCalls.push(m.params);
        if (window.readerMode === 'hold') return;
        if (window.readerMode === 'error') { reply({isError:true,content:[{type:'text',text:'No text available'}]}); return; }
        if (window.readerMode === 'stripped') { reply({structuredContent:{reference:{book_id:7}}}); return; }
        const a = m.params.arguments, end = Math.min(bookText.length,a.offset + 6000);
        reply({_meta:{calibreReader:{book_id:7,library:'secondary',format:'EPUB',title:'Example book',authors:['Author'],
          offset:a.offset,text:bookText.slice(a.offset,end),total_chars:bookText.length,next_offset:end < bookText.length ? end : null,
          chapters:[{index:0,title:'Chapter One',offset:0,chars:7000},{index:1,title:'Chapter Two',offset:7000,chars:bookText.length-7000}]}}});
      }
    });
    f.srcdoc = GALLERY;
    </script></body></html>""".replace("PAYLOAD", json.dumps(payload)).replace("GALLERY", json.dumps(gallery).replace("</", "<\\/"))
    host = host.replace("BOOKTEXT", json.dumps("Chapter One\n<script>window.readerInjection=1</script>\n" +
        "First paragraph. " * 500 + "\nChapter Two\n" + "Second paragraph. " * 500).replace("<", "\\u003c"))

    with tempfile.TemporaryDirectory(prefix="calibre-gallery-ux-") as temp, sync_playwright() as p:
        path = Path(temp, "host.html")
        path.write_text(host, encoding="utf-8")
        channel = os.environ.get("PLAYWRIGHT_CHANNEL")
        browser = p.chromium.launch(**({"channel": channel} if channel else {}))
        page = browser.new_page(viewport={"width": 780, "height": 900})
        script_errors = []
        page.on("pageerror", lambda error: script_errors.append(str(error)))
        page.clock.install()
        page.goto(path.as_uri())
        frame = page.frame_locator("#v")
        preview = frame.get_by_role("button", name="Enlarge Example book")
        expect(preview).to_be_enabled()
        preview.focus()
        preview.press("Enter")
        dialog = frame.get_by_role("dialog")
        expect(dialog).to_be_visible()
        expect(frame.get_by_role("button", name="Close", exact=True)).to_be_focused()
        expect(frame.locator("#zimg")).to_have_attribute("alt", "Example book")
        assert frame.locator("#zimg").evaluate("e => e.clientWidth < e.naturalWidth")
        frame.locator("#zimg").dblclick()
        expect(frame.get_by_role("button", name="100%", exact=True)).to_have_attribute("aria-pressed", "true")
        frame.locator("#viewport").dblclick(position={"x": 100, "y": 100})
        expect(frame.get_by_role("button", name="Fit", exact=True)).to_have_attribute("aria-pressed", "true")
        frame.get_by_role("button", name="100%", exact=True).click()
        assert frame.locator("#zimg").evaluate("e => e.clientWidth === e.naturalWidth && e.clientWidth === 1400")
        viewport = frame.locator("#viewport")
        assert viewport.evaluate("e => e.scrollWidth > e.clientWidth && e.scrollHeight > e.clientHeight")
        box = viewport.bounding_box()
        x, y = box["x"] + 200, box["y"] + 200
        # A real Ctrl+wheel must zoom the image, not the host page, and keep its anchor.
        page.mouse.move(x, y)
        before_width = frame.locator("#zimg").evaluate("e => e.getBoundingClientRect().width")
        anchor = viewport.evaluate("e => { const r = document.getElementById('zimg').getBoundingClientRect(); const p = e.getBoundingClientRect(); return [(p.left + 200 - r.left) / r.width, (p.top + 200 - r.top) / r.height]; }")
        page.keyboard.down("Control")
        page.mouse.wheel(0, -100)
        page.keyboard.up("Control")
        expect(frame.locator("#zoom-level")).to_have_text("122%")
        after_width = frame.locator("#zimg").evaluate("e => e.getBoundingClientRect().width")
        assert after_width > before_width
        after_anchor = viewport.evaluate("e => { const r = document.getElementById('zimg').getBoundingClientRect(); const p = e.getBoundingClientRect(); return [(p.left + 200 - r.left) / r.width, (p.top + 200 - r.top) / r.height]; }")
        assert all(abs(a - b) < 0.002 for a, b in zip(anchor, after_anchor))
        page.keyboard.down("Control")
        page.mouse.wheel(0, 100)
        page.keyboard.up("Control")
        expect(frame.locator("#zoom-level")).to_have_text("100%")
        assert frame.locator("#zimg").evaluate("e => Math.abs(e.getBoundingClientRect().width - e.naturalWidth) < 1")
        assert page.evaluate("window.visualViewport.scale") == 1
        print("PASS Ctrl+wheel zoom in/out, cursor anchor and unchanged page scale")
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x - 100, y - 100, steps=5)
        page.mouse.up()
        assert viewport.evaluate("e => e.scrollTop >= 90 && e.scrollLeft >= 90")
        expect(dialog).to_be_visible()
        # Releasing a drag over the backdrop must not dismiss the dialog.
        iframe_box = page.locator("#v").bounding_box()
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(iframe_box["x"] + 2, iframe_box["y"] + 2, steps=5)
        page.mouse.up()
        expect(dialog).to_be_visible()
        viewport.evaluate("e => { e.scrollTop = 100; e.scrollLeft = 100; }")
        viewport.focus()
        before = viewport.evaluate("e => e.scrollTop")
        viewport.press("ArrowDown")
        page.wait_for_timeout(200)  # native keyboard scrolling animates across frames
        assert viewport.evaluate("e => e.scrollTop") > before
        # Fit resets both scroll axes and restores the image to the available space.
        frame.get_by_role("button", name="Fit", exact=True).click()
        assert viewport.evaluate("e => e.scrollTop === 0 && e.scrollLeft === 0")
        fit = frame.get_by_role("button", name="Fit", exact=True)
        fit.focus()
        fit.press("Shift+Tab")
        expect(viewport).to_be_focused()
        viewport.press("Tab")
        expect(fit).to_be_focused()
        fit.press("Escape")
        expect(dialog).not_to_be_visible()
        expect(preview).to_be_focused()
        print("PASS keyboard open, native modal focus loop, Escape and focus restoration; fit/100% and pointer pan")
        preview.click()
        frame.locator("#zimg").click()
        expect(dialog).to_be_visible()
        # Dialog padding and controls are inside the window, not its backdrop.
        dialog.click(position={"x": 2, "y": 2})
        expect(dialog).to_be_visible()
        page.mouse.click(iframe_box["x"] + 2, iframe_box["y"] + 2)
        expect(dialog).not_to_be_visible()
        expect(preview).to_be_focused()
        print("PASS double-click fit/100%, backdrop dismissal and drag-outside protection")
        preview.click()
        chat = page.get_by_role("textbox", name="Chat message")
        chat.click()
        page.clock.run_for(50)
        expect(dialog).not_to_be_visible()
        expect(chat).to_be_focused()
        chat.fill("Focus stays in the chat")
        expect(chat).to_have_value("Focus stays in the chat")
        print("PASS click on host chat closes the image without taking focus back")

        read = frame.get_by_role("button", name="Read", exact=True)
        read.click()
        expect(frame.locator("#reader-text")).to_contain_text("<script>window.readerInjection=1</script>")
        assert frame.locator("#reader-text script").count() == 0
        assert frame.locator("html").evaluate("() => window.readerInjection || null") is None
        args = page.evaluate("window.readerCalls[0].arguments")
        assert args["book_id"] == 7 and args["format"] == "EPUB" and args["library"] == "secondary"
        frame.get_by_role("button", name="Continue", exact=True).click()
        expect(frame.get_by_role("button", name="Previous", exact=True)).to_be_enabled()
        assert page.evaluate("window.readerCalls.at(-1).arguments.offset") == 6000
        frame.get_by_role("button", name="Previous", exact=True).click()
        expect(frame.get_by_role("button", name="Previous", exact=True)).to_be_disabled()
        frame.locator("#reader-chapter").select_option("7000")
        expect(frame.locator("#reader")).to_have_attribute("aria-busy", "false")
        assert page.evaluate("window.readerCalls.at(-1).arguments.offset") == 7000
        frame.get_by_role("button", name="Larger text", exact=True).click()
        assert frame.locator("#reader-text").evaluate("e => getComputedStyle(e).fontSize") == "18px"
        frame.get_by_role("button", name="Back to gallery", exact=True).click()
        expect(read).to_be_focused()
        page.evaluate("window.readerMode='stripped'")
        read.click()
        expect(frame.locator("#reader-status")).to_contain_text("did not forward reading metadata")
        page.evaluate("window.readerMode='ok'")
        frame.get_by_role("button", name="Retry", exact=True).click()
        expect(frame.locator("#reader-text")).not_to_be_empty()
        frame.get_by_role("button", name="Back to gallery", exact=True).click()
        frame.locator("#language").select_option("it")
        expect(frame.get_by_role("button", name="Copia PNG", exact=True)).to_be_visible()
        frame.get_by_role("button", name="Leggi", exact=True).click()
        expect(frame.get_by_role("button", name="Continua", exact=True)).to_be_visible()
        expect(frame.locator("#reader-status")).to_contain_text("Testo estratto")
        frame.get_by_role("button", name="Torna alla galleria", exact=True).click()
        frame.locator("#language").select_option("en")
        print("PASS reader pagination, chapter selection, font size, source binding, metadata failure/retry and IT/EN labels")

        save = frame.get_by_role("button", name="Save PNG")
        save.click()
        expect(frame.locator(".st")).to_contain_text("Download request accepted")
        expect(save).to_be_enabled()
        page.evaluate("window.holdDownload = true")
        save.click()
        expect(save).to_be_disabled()
        expect(frame.get_by_role("button", name="Copy PNG")).to_be_disabled()
        page.clock.fast_forward(16000)
        expect(frame.locator(".st")).to_contain_text("did not respond")
        expect(save).to_be_enabled()
        assert page.evaluate("window.downloads") == 2
        print("PASS export feedback, busy controls and timeout recovery without duplicate downloads")

        preview.click()
        page.evaluate("window.deliver({_meta:{calibreQuotes:{passages:[{book_id:7,library:'secondary',format:'EPUB',offset:7000,end_offset:7022,location:{chapter:'Chapter Two',percent:40},text:'Exact text  preserved.',label:'Book',authors:[]}]}}})")
        expect(dialog).not_to_be_visible()
        expect(frame.locator("blockquote")).to_have_text("Exact text  preserved.")
        expect(frame.locator("figcaption")).to_contain_text("Chapter Two")
        expect(frame.locator("figcaption")).to_contain_text("40%")
        expect(frame.locator("details")).not_to_have_attribute("open", "")
        frame.get_by_text("Source details", exact=True).click()
        expect(frame.locator("details")).to_contain_text("[7000, 7022)")
        frame.locator("#language").select_option("it")
        expect(frame.locator("figcaption")).to_contain_text("Posizione nel testo estratto: 40%")
        expect(frame.get_by_text("Dettagli della fonte", exact=True)).to_be_visible()
        frame.locator("#language").select_option("en")
        page.evaluate("window.deliver({structuredContent:window.payload})")
        expect(preview).to_be_enabled()
        page.evaluate("""() => window.deliver({structuredContent:{images:[{
          label:'Broken',mime:'image/png',data:btoa('not a PNG')}]}})""")
        expect(frame.locator(".image-state")).to_contain_text("could not be loaded")
        expect(frame.get_by_role("button", name="Save PNG")).to_be_disabled()
        expect(frame.get_by_role("button", name="Enlarge Broken")).to_be_disabled()
        print("PASS image/quotation transitions and corrupt-image feedback")

        page.close()
        page = browser.new_page(viewport={"width": 780, "height": 900})
        page.on("pageerror", lambda error: script_errors.append(str(error)))
        page.goto(path.as_uri() + "#missing")
        frame = page.frame_locator("#v")
        expect(frame.locator("#msg")).to_have_text("Loading content…")
        page.wait_for_function("window.initialized === true")
        expect(frame.locator("#msg")).to_contain_text("Content has not arrived", timeout=25000)
        page.evaluate("window.deliver({structuredContent:window.payload})")
        expect(frame.get_by_role("button", name="Enlarge Example book")).to_be_enabled()
        assert not script_errors, script_errors
        print("PASS missing-result timeout, late-result recovery and no script errors")
        screenshot = os.environ.get("GALLERY_UX_SCREENSHOT")
        if screenshot:
            frame.get_by_role("button", name="Enlarge Example book").click()
            page.screenshot(path=screenshot)
        browser.close()


if __name__ == "__main__":
    main()

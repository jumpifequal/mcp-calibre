"""Render the real gallery with fictional content, without accessing a Calibre library.

python presentation/render_ux_demo.py --channel msedge
Requires Pillow and Playwright; omit --channel to use Playwright's Chromium.
"""
import argparse
import base64
import io
import json
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "presentation/screenshots"


def font(size, bold=False):
    names = (["C:/Windows/Fonts/seguisb.ttf", "DejaVuSans-Bold.ttf"] if bold else
             ["C:/Windows/Fonts/segoeui.ttf", "DejaVuSans.ttf"])
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    raise RuntimeError("Install Segoe UI or DejaVu Sans to render the demo")


def png(image):
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def cover():
    image = Image.new("RGB", (720, 1020), "#102c3a")
    d = ImageDraw.Draw(image)
    d.rectangle((42, 44, 678, 976), outline="#52797d", width=2)
    d.text((76, 85), "MCP-CALIBRE / SAMPLE EDITION", font=font(22), fill="#9cd6ca")
    d.multiline_text((76, 170), "THE DEMO\nLIBRARY", font=font(78, True), spacing=8, fill="#f6f1e4")
    d.multiline_text((80, 398), "Notes on questions, ideas\nand small experiments", font=font(29), spacing=10, fill="#bfd7d6")
    for box in ((132, 556, 484, 862), (242, 530, 594, 836)):
        d.ellipse(box, outline="#69c8b4", width=4)
    d.line((122, 712, 600, 712), fill="#edbd74", width=3)
    for x, y in ((162, 712), (362, 552), (562, 712)):
        d.ellipse((x-10, y-10, x+10, y+10), fill="#edbd74")
    d.text((80, 903), "FICTIONAL BOOK / DEMONSTRATION ONLY", font=font(20, True), fill="#9cd6ca")
    return image


def diagram(title, labels):
    image = Image.new("RGB", (900, 720), "#f5f7f4")
    d = ImageDraw.Draw(image)
    d.text((52, 44), title, font=font(38, True), fill="#102c3a")
    d.text((52, 106), "The Demo Library / fictional sample figure", font=font(22), fill="#526a6f")
    positions = [(70, 200), (490, 200), (70, 445), (490, 445)]
    for i, ((x, y), (name, detail)) in enumerate(zip(positions, labels)):
        d.rounded_rectangle((x, y, x+335, y+175), radius=20, fill="#e2eeea", outline="#89b7ac", width=2)
        d.text((x+22, y+20), f"0{i+1}", font=font(23, True), fill="#2d7868")
        d.text((x+22, y+60), name, font=font(30, True), fill="#102c3a")
        d.text((x+22, y+112), detail, font=font(21), fill="#526a6f")
    for y in (286, 532):
        d.line((421, y, 472, y), fill="#2d7868", width=4)
        d.polygon(((474, y), (460, y-8), (460, y+8)), fill="#2d7868")
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", help="Installed browser channel, e.g. msedge or chrome")
    args = parser.parse_args()
    images = [cover(), diagram("A better question", [("Observe", "Notice one detail"), ("Ask", "Name the uncertainty"),
              ("Compare", "Consider alternatives"), ("Choose", "State the next step")]),
              diagram("Small experiments", [("Sketch", "Make the idea visible"), ("Try", "Test one assumption"),
              ("Reflect", "Record what changed"), ("Repeat", "Keep the useful part")])]
    labels = ["mcp-calibre · Fictional sample", "Figure 1 · A better question", "Figure 2 · Small experiments"]
    payload = {"title": "The Demo Library", "images": [{"book_id": 42, "library": "Demo library", "format": "EPUB",
        "image": "cover" if i == 0 else f"s{i}-1", "label": "The Demo Library", "sublabel": labels[i],
        "alt": labels[i], "mime": "image/png", "data": png(im), "filename": f"demo-{i}.png"} for i, im in enumerate(images)]}
    paragraphs = [
        "Chapter 1 · A better question",
        "A useful question makes room for an answer you did not expect. Start with one concrete observation: a repeated task, an unexplained delay, or an idea that is difficult to describe.",
        "Write down what you know and what you are assuming. The difference matters. An observation gives the conversation a starting point; an assumption gives you something to test.",
        "Choose a small experiment. Give it a clear stopping point and decide what evidence would change your mind. The aim is to learn enough to choose the next step, rather than to settle every question at once.",
        "After the experiment, keep a short record: the question, the result, and the decision that follows. A notebook becomes useful when it helps you act on what you learned.",
        "Chapter 2 · Small experiments",
        "Sketch an idea, try one variation, and compare the result with your expectation. Keep the useful part and revise the rest. Small experiments make uncertainty easier to discuss.",
        "This is original fictional sample text created solely to demonstrate the mcp-calibre reader. The book, cover and figures do not represent a published title."
    ]
    text = "\n\n".join(paragraphs)
    second = text.index("Chapter 2")
    chapters = [{"index": 0, "title": paragraphs[0], "offset": 0, "chars": second},
                {"index": 1, "title": paragraphs[5], "offset": second, "chars": len(text)-second}]
    quote = {"title": "The Demo Library", "passages": [{"book_id": 42, "library": "Demo library", "format": "EPUB",
        "offset": len(paragraphs[0])+2, "end_offset": len(paragraphs[0])+2+len(paragraphs[1]),
        "label": "The Demo Library", "authors": ["mcp-calibre · Fictional sample"], "text": paragraphs[1],
        "location": {"chapter": paragraphs[0], "percent": 3}}]}
    gallery = (ROOT / "mcpcalibre/ui/gallery.html").read_text("utf-8")
    gallery = gallery.replace("<head>", '<head><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        'script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; img-src data:; connect-src \'none\';">', 1)
    encode = lambda value: json.dumps(value, ensure_ascii=True).replace("<", "\\u003c")
    host = '''<!doctype html><html><head><meta charset="utf-8"><style>
      body{margin:0;padding:24px;background:#edf2f2;font:14px system-ui;color:#314c57}
      header{max-width:880px;margin:0 auto 16px;display:flex;justify-content:space-between;gap:12px}
      iframe{display:block;width:880px;max-width:100%;height:720px;border:0;border-radius:12px;background:white;margin:auto}
      </style></head><body><header><b>mcp-calibre · MCP Apps</b><span>Fictional book / documentation preview</span></header>
      <iframe id="view" title="mcp-calibre view" sandbox="allow-scripts"></iframe><script>
      const f=document.getElementById('view'), payload=PAYLOAD, text=TEXT, chapters=CHAPTERS;
      window.deliver=r=>f.contentWindow.postMessage({jsonrpc:'2.0',method:'ui/notifications/tool-result',params:r},'*');
      window.addEventListener('message',e=>{if(e.source!==f.contentWindow)return;const m=e.data;
      const reply=result=>f.contentWindow.postMessage({jsonrpc:'2.0',id:m.id,result},'*');
      if(m.method==='ui/initialize')reply({protocolVersion:'2026-01-26',hostCapabilities:{},hostContext:{theme:'light',locale:LOCALE}});
      else if(m.method==='ui/notifications/initialized')window.deliver({structuredContent:payload});
      else if(m.method==='ui/notifications/size-changed')f.style.height=Math.max(650,m.params.height)+'px';
      else if(m.method==='tools/call'){const a=m.params.arguments,end=Math.min(text.length,a.offset+900);
      reply({_meta:{calibreReader:{book_id:42,library:'Demo library',format:'EPUB',title:'The Demo Library',
      authors:['mcp-calibre · Fictional sample'],offset:a.offset,text:text.slice(a.offset,end),total_chars:text.length,
      next_offset:end<text.length?end:null,chapters}}});}});f.srcdoc=GALLERY;
      </script></body></html>'''
    for key, value in {"PAYLOAD": payload, "TEXT": text, "CHAPTERS": chapters, "GALLERY": gallery}.items():
        host = host.replace(key, encode(value))
    SHOTS.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="calibre-doc-demo-") as temp, sync_playwright() as p:
        browser = p.chromium.launch(**({"channel": args.channel} if args.channel else {}))
        for lang in ("en", "it"):
            page = browser.new_page(viewport={"width": 1000, "height": 850}, device_scale_factor=1)
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            path = Path(temp, f"demo-{lang}.html")
            path.write_text(host.replace("LOCALE", encode(lang)), encoding="utf-8")
            page.goto(path.as_uri())
            frame = page.frame_locator("#view")
            expect(frame.locator(".preview:enabled")).to_have_count(3)
            frame.locator("#grid").evaluate("async e=>{await Promise.all([...e.querySelectorAll('img')].map(i=>i.decode()));await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));}")
            frame.locator("body").screenshot(path=str(SHOTS / f"ux-gallery-{lang}.png"))
            frame.get_by_role("button", name="Leggi" if lang == "it" else "Read", exact=True).first.click()
            expect(frame.locator("#reader-text")).not_to_be_empty()
            frame.locator("body").screenshot(path=str(SHOTS / f"ux-reader-{lang}.png"))
            frame.get_by_role("button", name="Torna alla galleria" if lang == "it" else "Back to gallery").click()
            page.evaluate("q=>window.deliver({_meta:{calibreQuotes:q}})", quote)
            expect(frame.locator("blockquote")).to_have_text(paragraphs[1])
            frame.locator("body").screenshot(path=str(SHOTS / f"ux-quotes-{lang}.png"))
            assert not errors, errors
            page.close()
        browser.close()
    print("Rendered six real-view screenshots with fictional content in", SHOTS)


if __name__ == "__main__":
    main()

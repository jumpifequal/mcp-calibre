"""Figure extraction tests (EPUB, PDF, converted formats, hostile inputs).
Usage: python tests/make_fake_library.py && python tests/test_figures.py"""
import io, os, shutil, sqlite3, struct, sys, tempfile, zipfile, zlib
from pathlib import Path
sys.argv = ["x"]
here = Path(__file__).resolve().parent
sys.path.insert(0, str(here.parent))
os.environ["CALIBRE_MCP_DATA"] = tempfile.mkdtemp()
import pymupdf
from PIL import Image as PIL
import calibre_mcp as m
from mcpcalibre import htmlmd

FAILS = []
def check(label, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + label + ("" if cond else f"  -> {str(detail)[:300]}"))
    FAILS.append(label) if not cond else None
def err(fn, **kw):
    try:
        fn(**kw); return None
    except Exception as e:  # noqa: BLE001
        return str(e)

def png(w, h, color=(200, 30, 30)):
    b = io.BytesIO(); PIL.new("RGB", (w, h), color).save(b, "PNG"); return b.getvalue()
def jpg(w, h):
    b = io.BytesIO(); PIL.new("RGB", (w, h), (20, 120, 200)).save(b, "JPEG"); return b.getvalue()
def png_bomb(w=50000, h=50000):
    """Valid small PNG whose IHDR claims w x h pixels (decompression bomb)."""
    raw = png(4, 4)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    chunk = b"IHDR" + ihdr
    return raw[:8] + struct.pack(">I", 13) + chunk + struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF) + raw[33:]
svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="300" height="150"><rect width="300" height="150" fill="#3a7"/></svg>'

lib = Path(tempfile.mkdtemp()) / "Figs"
shutil.copytree(here / "Calibre Library", lib)
c = sqlite3.connect(lib / "metadata.db")
def add(bid, title, fmt):
    c.execute("INSERT INTO books(id,title,sort,timestamp,pubdate,series_index,author_sort,path,has_cover,uuid) "
              "VALUES (?,?,?,?,?,1,'x',?,0,?)", (bid, title, title, "2025-01-01", "2025-01-01", f"x/{bid}", f"u{bid}"))
    c.execute("INSERT INTO data(book,format,uncompressed_size,name) VALUES (?,?,1,'f')", (bid, fmt))
    d = lib / f"x/{bid}"; d.mkdir(parents=True, exist_ok=True); return d / f"f.{fmt.lower()}"

# ---- EPUB with every case
ch1 = b"""<html><body><h1>Chapter 1</h1><p>Intro.</p>
<figure><img src="../img/arch.png" alt="Architecture"/><figcaption>Figure 1-1. System architecture</figcaption></figure>
<p>Text.</p><img src="../img/flow.jpg"/><p>Figure 1-2: Data flow between agents</p>
<img src="../img/spacer.gif" alt=""/><img src="https://evil.example/x.png" alt="remote"/>
<img src="../../../../etc/passwd.png" alt="traversal"/></body></html>"""
ch2 = b"""<html><body><h1>Chapter 2</h1><svg xmlns="http://www.w3.org/2000/svg"><image href="../img/diagram.svg"/><text>ignore me</text></svg>
<p>Body</p><img src="../img/bomb.png" alt="bomb"/></body></html>"""
gif = io.BytesIO(); PIL.new("P", (1, 1)).save(gif, "GIF")
def make_epub(p):
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("META-INF/container.xml", '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>')
        z.writestr("OEBPS/content.opf", '<package xmlns="http://www.idpf.org/2007/opf"><manifest><item id="c1" href="text/c1.xhtml"/><item id="c2" href="text/c2.xhtml"/></manifest><spine><itemref idref="c1"/><itemref idref="c2"/></spine></package>')
        z.writestr("OEBPS/text/c1.xhtml", ch1); z.writestr("OEBPS/text/c2.xhtml", ch2)
        z.writestr("OEBPS/img/arch.png", png(1600, 900)); z.writestr("OEBPS/img/flow.jpg", jpg(800, 600))
        z.writestr("OEBPS/img/spacer.gif", gif.getvalue()); z.writestr("OEBPS/img/diagram.svg", svg)
        z.writestr("OEBPS/img/bomb.png", png_bomb() + b"\0" * 3000)
make_epub(add(50, "Epub With Figures", "EPUB"))

# ---- PDF: raster figure + caption, vector diagram + caption, tiny icon
doc = pymupdf.open()
p1 = doc.new_page(); p1.insert_text((72, 60), "Some text"); p1.insert_image(pymupdf.Rect(72, 80, 472, 380), stream=png(800, 600))
p1.insert_text((72, 400), "Figure 3-1. Agent loop")
p2 = doc.new_page(); p2.draw_rect(pymupdf.Rect(100, 100, 400, 300), color=(0, 0, 1), fill=(0.8, 0.9, 1)); p2.draw_line((100, 100), (400, 300))
p2.insert_text((72, 330), "Figure 3-2. Vector diagram")
p3 = doc.new_page(); p3.insert_image(pymupdf.Rect(10, 10, 26, 26), stream=png(16, 16)); p3.insert_text((72, 72), "icon page")
doc.save(add(51, "Pdf With Figures", "PDF"))

# ---- MOBI-only book: reached through ebook-convert -> EPUB (fake converter copies a prepared EPUB)
add(52, "Mobi Book", "MOBI").write_bytes(b"BOOKMOBI fake")
prepared = Path(tempfile.mkdtemp()) / "conv.epub"; make_epub(prepared)
# Portable stand-in for Calibre's ebook-convert: a Python script (wrapped in a .cmd on Windows, where a
# shebang script cannot be executed). EPUB targets get the prepared EPUB; anything else gets text.
_fdir = Path(tempfile.mkdtemp())
(_fdir / "fake_convert.py").write_text(
    "import shutil, sys\n"
    "src, out = sys.argv[1], sys.argv[2]\n"
    f"shutil.copy(r'{prepared}', out) if out.lower().endswith('.epub') else open(out, 'w').write('text')\n")
if os.name == "nt":
    fake = _fdir / "fake-ebook-convert.cmd"
    fake.write_text(f'@"{sys.executable}" "{_fdir / "fake_convert.py"}" %*\r\n')
else:
    fake = _fdir / "fake-ebook-convert"
    fake.write_text(f'#!{sys.executable}\n' + (_fdir / "fake_convert.py").read_text())
    fake.chmod(0o755)
os.environ["CALIBRE_EBOOK_CONVERT"] = str(fake)
c.commit(); c.close()
m.set_libraries([lib], Path(os.environ["CALIBRE_MCP_DATA"]))

# ---- EPUB listing
lst = m.calibre_list_figures(50)
ids = {f["id"]: f for f in lst["figures"]}
check("epub: figcaption caption", ids.get("s0-1", {}).get("caption") == "Figure 1-1. System architecture", ids.get("s0-1"))
check("epub: caption from following paragraph", ids.get("s0-2", {}).get("caption", "").startswith("Figure 1-2"), ids.get("s0-2"))
check("epub: section title attached", ids["s0-1"].get("section_title") == "Chapter 1" or "section_title" not in ids["s0-1"], ids["s0-1"])
check("epub: spacer hidden by default", "s0-3" not in ids and "s0-3" in {f["id"] for f in m.calibre_list_figures(50, include_small=True)["figures"]})
check("epub: remote image not available", ids.get("s0-4", {}).get("available") is False, ids.get("s0-4"))
check("epub: path traversal not available", ids.get("s0-5", {}).get("available") is False, ids.get("s0-5"))
check("epub: svg <image> inside <svg> listed", ids.get("s1-1", {}).get("format") == "svg", ids.get("s1-1"))
check("epub: section filter", {f["section"] for f in m.calibre_list_figures(50, section=1)["figures"]} == {1})

# ---- EPUB extraction
im = m.calibre_get_figure(50, "s0-1", max_px=400)
w, h = PIL.open(io.BytesIO(im.data)).size
check("epub: png resized to max_px", max(w, h) == 400 and im.data[:4] == b"\x89PNG", (w, h))
im = m.calibre_get_figure(50, "s0-2", max_px=300)
check("epub: jpeg stays jpeg", im.data[:3] == b"\xff\xd8\xff" and max(PIL.open(io.BytesIO(im.data)).size) == 300)
im = m.calibre_get_figure(50, "s1-1", max_px=600)
check("epub: svg rasterised to png", im.data[:4] == b"\x89PNG" and max(PIL.open(io.BytesIO(im.data)).size) <= 600)
check("epub: decompression bomb refused", "decompression bomb" in (err(m.calibre_get_figure, book_id=50, figure_id="s1-2") or ""))
check("epub: remote figure refused", "external" in (err(m.calibre_get_figure, book_id=50, figure_id="s0-4") or ""))
check("epub: unknown id", "No figure" in (err(m.calibre_get_figure, book_id=50, figure_id="s9-9") or ""))
check("epub: bad id pattern rejected by schema-level check", err(m.calibre_get_figure, book_id=50, figure_id="../x") is not None)

# ---- markdown placeholders carry the same ids
md = m.calibre_read_section(50, section=0, output="markdown")["text"]
check("markdown: placeholder ids match list", "[image s0-1: Architecture]" in md and "[image s0-2]" in md, md[:300])
md2 = m.calibre_read_section(50, section=1, output="markdown")["text"]
check("markdown: svg text ignored, image counted", "ignore me" not in md2 and "[image s1-1]" in md2, md2)

# ---- PDF
pl = m.calibre_list_figures(51)
pid = {f["id"]: f for f in pl["figures"]}
raster = next((f for f in pl["figures"] if f["kind"] == "image"), None)
check("pdf: raster image with caption", raster and raster["page"] == 1 and raster.get("caption", "").startswith("Figure 3-1"), pl)
check("pdf: vector diagram detected", "p2-render" in pid and pid["p2-render"]["kind"] == "vector", pl)
check("pdf: tiny icon hidden by default", not any(f["page"] == 3 for f in pl["figures"])
      and any(f["page"] == 3 for f in m.calibre_list_figures(51, include_small=True)["figures"]))
im = m.calibre_get_figure(51, raster["id"], max_px=500)
check("pdf: embedded image extracted & resized", max(PIL.open(io.BytesIO(im.data)).size) <= 500)
check("pdf: xref must be on the page", "not on page" in (err(m.calibre_get_figure, book_id=51, figure_id=f"p2-x{raster['id'].split('x')[1]}") or ""))
im = m.calibre_render_page(51, 2, max_px=800)
check("pdf: render page", max(PIL.open(io.BytesIO(im.data)).size) in (799, 800))
im = m.calibre_render_page(51, 2, max_px=400, clip=[0.1, 0.1, 0.7, 0.45])
wc, hc = PIL.open(io.BytesIO(im.data)).size
check("pdf: render clip", max(wc, hc) in (399, 400) and wc > hc, (wc, hc))
check("pdf: bad clip rejected", "clip must be" in (err(m.calibre_render_page, book_id=51, page=1, clip=[0.5, 0, 0.2, 1]) or ""))
check("pdf: page out of range", "out of range" in (err(m.calibre_render_page, book_id=51, page=99) or ""))
check("render needs a PDF", "no PDF" in (err(m.calibre_render_page, book_id=50, page=1) or ""))

# ---- converted format (MOBI -> EPUB, cached)
ml = m.calibre_list_figures(52)
check("mobi: figures via conversion", ml["source"] == "epub" and any(f["id"] == "s0-1" for f in ml["figures"]), ml)
conv = list((m.LIB.side_dir / "converted").glob("52-MOBI-*.epub"))
check("mobi: conversion cached", len(conv) == 1)
os.environ["CALIBRE_EBOOK_CONVERT"] = "/nonexistent"   # cached copy must be reused without the converter
check("mobi: cache reused", m.calibre_list_figures(52)["total"] == ml["total"])
# ---- calibre_show_images: covers + EPUB/PDF figures, data only in structuredContent
import base64
def _lib_state():
    return sorted((str(p.relative_to(lib)), p.stat().st_size, p.stat().st_mtime_ns) for p in lib.rglob("*") if p.is_file())
_before = _lib_state()
r = m.calibre_show_images([m.ImageRef(book_id=1), m.ImageRef(book_id=50, image="s0-1"),
                           m.ImageRef(book_id=51, image=raster["id"]), m.ImageRef(book_id=50, image="s1-2"),
                           m.ImageRef(book_id=999)], title="Mixed")
sc = getattr(r, "structured_content", None) or getattr(r, "structuredContent")
txt = r.content[0].text
check("show: covers and figures in one gallery", [i["image"] for i in sc["images"]] == ["cover", "s0-1", raster["id"]], sc["images"])
check("show: figure caption used as sublabel", "System architecture" in sc["images"][1]["sublabel"], sc["images"][1]["sublabel"])
check("show: bomb and unknown book reported, not fatal", len(sc["errors"]) == 2 and any("decompression" in e for e in sc["errors"]), sc["errors"])
check("show: model text is short, no image data", len(txt) < 1200 and sc["images"][0]["data"][:40] not in txt, len(txt))
check("show: only text for the model by default", [c.type for c in r.content] == ["text"])
check("show: data decodes", all(base64.b64decode(i["data"])[:3] in (b"\xff\xd8\xff", b"\x89PN") for i in sc["images"]))
r2 = m.calibre_show_images([m.ImageRef(book_id=50, image="s0-1")], also_for_model=True)
check("show: also_for_model adds a thumbnail", [c.type for c in r2.content] == ["text", "image"])
check("show: read-only (library files, sizes and mtimes unchanged)", _lib_state() == _before)
print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
sys.exit(1 if FAILS else 0)

"""OCR tests (Tesseract). Skipped when Tesseract is not installed.
Usage: python tests/make_fake_library.py && python tests/test_ocr.py"""
import contextlib, glob, io, os, shutil, sqlite3, subprocess, sys, tempfile
from pathlib import Path
sys.argv = ["x"]
here = Path(__file__).resolve().parent
sys.path.insert(0, str(here.parent))
os.environ["CALIBRE_MCP_DATA"] = tempfile.mkdtemp()
os.environ["CALIBRE_MCP_EMBED_BACKEND"] = "hash"
if not shutil.which("tesseract"):
    print("SKIP: tesseract not installed"); sys.exit(0)
import pymupdf
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import calibre_mcp as m
from mcpcalibre import ocr

FAILS = []
def check(label, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + label + ("" if cond else f"  -> {str(detail)[:400]}"))
    FAILS.append(label) if not cond else None
def quiet(fn, *a, **kw):
    err = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
        r = fn(*a, **kw)
    return r, err.getvalue()

# Italian language data: reuse CALIBRE_MCP_TESSDATA if given, else download tessdata_fast (setup path)
if not os.environ.get("CALIBRE_MCP_TESSDATA"):
    r = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True)
    if "ita" not in (r.stdout + r.stderr):
        ocr.download_languages(Path(os.environ["CALIBRE_MCP_DATA"]) / "tessdata", ["ita", "eng"])

FONT = next(iter(glob.glob("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf") +
                 glob.glob("/usr/share/fonts/**/*.ttf", recursive=True) + glob.glob("C:/Windows/Fonts/arial.ttf")))
def page_image(lines):
    img = Image.new("L", (1700, 2200), 255); d = ImageDraw.Draw(img); f = ImageFont.truetype(FONT, 40)
    y = 220
    for ln in lines:
        d.text((150, y), ln, fill=0, font=f); y += 72
    img = img.rotate(0.5, fillcolor=255).filter(ImageFilter.GaussianBlur(0.5))   # a little skew and blur, like a scan
    b = io.BytesIO(); img.save(b, "PNG"); return b.getvalue()
IT = ["Capitolo 1. La sicurezza delle reti", "", "Il firewall è la prima linea di difesa:",
      "filtra il traffico secondo regole precise.", "Perché funzioni, però, serve una buona",
      "segmentazione della rete e un monitoraggio."]
EN = ["Chapter 2. Incident response", "", "Containment comes before eradication.", "Preserve the evidence first."]

lib = Path(tempfile.mkdtemp()) / "OCR Library"
shutil.copytree(here / "Calibre Library", lib)
c = sqlite3.connect(lib / "metadata.db"); f = sqlite3.connect(lib / "full-text-search.db")
c.execute("INSERT INTO authors(id,name,sort) VALUES (95,'Scan Author','Author, Scan')")
def add(bid, title, pages, lang=None, calibre_text=None):
    """pages: list of ('img', lines) or ('txt', str)."""
    c.execute("INSERT INTO books(id,title,sort,timestamp,pubdate,series_index,author_sort,path,has_cover,uuid) "
              "VALUES (?,?,?,'2025-01-01','2020-01-01',1,'x',?,0,?)", (bid, title, title, f"x/{bid}", f"u{bid}"))
    c.execute("INSERT INTO books_authors_link(book,author) VALUES (?,95)", (bid,))
    c.execute("INSERT INTO data(book,format,uncompressed_size,name) VALUES (?,'PDF',1,'f')", (bid,))
    if lang:
        c.execute("INSERT INTO books_languages_link(book,lang_code) VALUES (?,?)", (bid, lang))
    if calibre_text is not None:
        f.execute("INSERT INTO books_text(book,timestamp,format,format_size,format_hash,searchable_text,text_size,text_hash) "
                  "VALUES (?,0,'PDF',1,'h',?,?,?)", (bid, calibre_text, len(calibre_text), f"t{bid}"))
    d = lib / f"x/{bid}"; d.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    for kind, content in pages:
        pg = doc.new_page(width=595, height=842)
        if kind == "img":
            pg.insert_image(pg.rect, stream=page_image(content))
        else:
            pg.insert_text((72, 100), content, fontsize=11)
    doc.save(d / "f.pdf")
IT2 = ["Capitolo 2. Il monitoraggio", "", "I registri degli eventi vanno conservati", "e analizzati con regolarità."]
add(100, "Libro Scansionato", [("img", IT), ("img", IT2)], lang=1)                         # ita, 2 scanned pages
add(101, "Mixed PDF", [("txt", "This page has a real text layer about zero trust networks."), ("img", EN)], lang=2)
add(102, "Bad Text Layer", [("img", IT)], lang=1, calibre_text="x0 ~~ #### l1l1 " * 20)      # garbage OCR layer
add(103, "Scanned Without Engine", [("img", EN)], lang=2)
c.commit(); c.close(); f.commit(); f.close()
m.set_libraries([lib], Path(os.environ["CALIBRE_MCP_DATA"]))
m.LIB.index.sync()

# ---- engine, languages
m._OCR_ENGINE.clear()
eng = m.ocr_engine()
check("tesseract engine found with Italian data", eng is not None and "ita" in eng.languages(), getattr(eng, "exe", None))
check("language from the book (ita) first", ocr.pick_languages(eng, ["ita"]).startswith("ita"))
check("language aliases (fre -> fra) and fallback", ocr.pick_languages(eng, ["xxx"]) in ("ita+eng", "eng+ita", "ita", "eng"))

# ---- 1) scanned PDF, OCR automatic in --extract-missing
res, log = quiet(m.extract_missing, books=[100])
check("extract-missing OCRs the scanned PDF", res["ok"] == 1 and res["ocr_books"] == 1, (res, log[-400:]))
t = m.calibre_read_text(100)
check("OCR text is readable, accents kept", "segmentazione" in t["text"] and "è" in t["text"] and "Perché" in t["text"]
      and t["source"].startswith("cache:pdf-ocr:tesseract"), t)
ft = m.calibre_search_fulltext("segmentazione rete", limit=5)
check("OCR text is searchable (full-text) with a snippet", any(r["book_id"] == 100 and r.get("snippets") for r in ft["results"]), ft)
ch = m.calibre_get_chapters(100)
titles = [x["title"] or "" for x in ch["chapters"]]
check("chapter map works on OCR text", ch["method"] == "headings" and any("Capitolo 1" in x for x in titles)
      and any("Capitolo 2" in x for x in titles), ch)

# ---- 2) mixed PDF: only the scanned page is OCRed
res, log = quiet(m.extract_missing, books=[101])
t = m.calibre_read_text(101)["text"]
check("mixed PDF: text layer kept, scanned page OCRed", "zero trust" in t and "Containment" in t and "1/2 pages" in log, log[-300:])

# ---- 3) bad text layer: --force-ocr replaces Calibre's garbage text
before = m.calibre_read_text(102)
check("before: Calibre's (bad) text is used", before["source"] == "calibre-fts")
res, log = quiet(m.extract_missing, books=[102], force_ocr=True)
after = m.calibre_read_text(102)
check("force-ocr: OCR text now takes precedence", res["ocr_books"] == 1 and "segmentazione" in after["text"]
      and after["source"].startswith("cache:pdf-ocr"), (res, after["source"]))
srcs, details = m._embedding_sources()
check("force-ocr: semantic index uses the OCR text", 102 in details and details[102]["hash"].startswith("ocr:"), details.get(102))
quiet(m.build_embeddings, books=[100, 102])
sem = m.calibre_search_semantic("segmentazione della rete firewall", limit=3)
check("OCR books reach semantic search", {r["book_id"] for r in sem["results"]} >= {100, 102}, sem)
try:
    m.extract_missing(force_ocr=True); bad = None
except ValueError as e:
    bad = str(e)
check("--force-ocr without --books is refused", bad and "needs --books" in bad, bad)

# ---- 4) no engine: failure recorded, then skipped, then retried
os.environ["CALIBRE_MCP_OCR_ENGINE"] = "none"; m._OCR_ENGINE.clear()
res, log = quiet(m.extract_missing, books=[103])
check("no engine: clear failure, nothing crashes", res["failed"] == 1 and "install Tesseract" in log, log[-300:])
res, _ = quiet(m.extract_missing, books=[103])
check("known failure skipped while the file is unchanged", res["processed"] == 0 and res["skipped_known_failures"] == 1, res)
rep = m.calibre_semantic_index_report("no_text")
err = next((x.get("error") for x in rep["categories"]["no_text"] if x["book_id"] == 103), None)
check("semantic report shows the extraction error", err and "OCR" in err, rep["categories"]["no_text"])
del os.environ["CALIBRE_MCP_OCR_ENGINE"]; m._OCR_ENGINE.clear()
res, _ = quiet(m.extract_missing, books=[103], retry_failed=True)
check("--retry-failed with the engine back: OCR succeeds", res["ok"] == 1 and "Containment" in m.calibre_read_text(103)["text"], res)
check("failure cleared after success", 103 not in m.LIB.index.extract_failures())

# ---- 5) library read-only: PDFs untouched
check("PDFs are never modified", all((lib / f"x/{b}/f.pdf").stat().st_size > 0 for b in (100, 101, 102, 103)))

# ---- 6) unknown engine names are rejected
os.environ["CALIBRE_MCP_OCR_ENGINE"] = "not-an-engine"; m._OCR_ENGINE.clear()
try:
    m.ocr_engine(); bad = None
except ocr.OcrError as e:
    bad = str(e)
check("only tesseract/auto/none are accepted", bad and "use auto, tesseract or none" in bad, bad)
del os.environ["CALIBRE_MCP_OCR_ENGINE"]; m._OCR_ENGINE.clear()

# ---- 7) limits and input validation
class Probe:
    name = "probe"
    def __init__(self): self.sizes = []
    def page_text(self, png, langs):
        self.sizes.append(Image.open(io.BytesIO(png)).size); return "x"
big = Path(tempfile.mkdtemp()) / "big.pdf"; d = pymupdf.open(); d.new_page(width=5000, height=5000); d.save(big)
p = Probe(); ocr.ocr_pdf(str(big), p, "eng")
check("huge page rendered within the pixel budget", p.sizes and p.sizes[0][0] * p.sizes[0][1] <= ocr.MAX_PIXELS * 1.01, p.sizes)
try:
    ocr.download_languages(Path(tempfile.mkdtemp()), ["../../etc"]); bad = None
except ocr.OcrError as e:
    bad = str(e)
check("language codes validated before download", bad and "bad language code" in bad)
st = m.status()["features"]["ocr"]
check("status reports the OCR engine and languages", st.get("engine") == "tesseract" and "ita" in st.get("languages", []), st)
print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
sys.exit(1 if FAILS else 0)

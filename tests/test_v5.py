"""Tests for 5.0 features. Usage: python tests/make_fake_library.py && python tests/test_v5.py"""
import io, json, os, shutil, sqlite3, subprocess, sys, tempfile, zipfile
from pathlib import Path
sys.argv = ["x"]
here = Path(__file__).resolve().parent
sys.path.insert(0, str(here.parent))
os.environ["CALIBRE_MCP_DATA"] = tempfile.mkdtemp()
os.environ["CALIBRE_MCP_EMBED_BACKEND"] = "hash"      # lexical stand-in: no model download in tests
import pymupdf
from PIL import Image as PIL
import calibre_mcp as m
from mcpcalibre import isbn as isbnmod, semantic, structure

FAILS = []
def check(label, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + label + ("" if cond else f"  -> {str(detail)[:400]}"))
    FAILS.append(label) if not cond else None
def err(fn, **kw):
    try:
        fn(**kw); return None
    except Exception as e:  # noqa: BLE001
        return str(e)

lib = Path(tempfile.mkdtemp()) / "V5 Library"
shutil.copytree(here / "Calibre Library", lib)
c = sqlite3.connect(lib / "metadata.db"); f = sqlite3.connect(lib / "full-text-search.db")
def add_book(bid, title, author_id, text=None, fmt="EPUB", lang=None, isbn=None, tags=(), series=None, sidx=1, sort=None):
    c.execute("INSERT INTO books(id,title,sort,timestamp,pubdate,series_index,author_sort,path,has_cover,uuid) "
              "VALUES (?,?,?,?,?,?,?,?,0,?)", (bid, title, title, "2025-01-01", "2020-01-01", sidx, sort or "x", f"x/{bid}", f"u{bid}"))
    c.execute("INSERT INTO books_authors_link(book,author) VALUES (?,?)", (bid, author_id))
    c.execute("INSERT INTO data(book,format,uncompressed_size,name) VALUES (?,?,?,'f')", (bid, fmt, len(text or "")))
    if lang:
        c.execute("INSERT INTO books_languages_link(book,lang_code) VALUES (?,?)", (bid, lang))
    if isbn:
        c.execute("INSERT INTO identifiers(book,type,val) VALUES (?,'isbn',?)", (bid, isbn))
    for t in tags:
        c.execute("INSERT INTO books_tags_link(book,tag) VALUES (?,?)", (bid, t))
    if series:
        c.execute("INSERT INTO books_series_link(book,series) VALUES (?,?)", (bid, series))
    if text is not None:
        f.execute("INSERT INTO books_text(book,timestamp,format,format_size,format_hash,searchable_text,text_size,text_hash) "
                  "VALUES (?,0,?,1,'h',?,?,?)", (bid, fmt, text, len(text), f"t{bid}"))
    (lib / f"x/{bid}").mkdir(parents=True, exist_ok=True)

c.executemany("INSERT INTO authors(id,name,sort) VALUES (?,?,?)", [
    (60, "Cooper| Glenn", "Cooper| Glenn"), (61, "Glenn Cooper", "Cooper, Glenn"), (62, "Jane Doe", "Jane Doe"),
    (63, "Rossi, Mario", "Rossi, Mario"), (64, "Agent Writer", "Writer, Agent"), (65, "History Writer", "Writer, History")])
c.executemany("INSERT INTO tags(id,name) VALUES (?,?)", [(60, "Science-Fiction"), (61, "science fiction")])
c.execute("INSERT INTO series(id,name,sort) VALUES (60,'Saga','Saga')")
body = "The orchestration of coding agents requires review of every diff and small tasks. " * 25
front = ("Praise for this book\n\nAgents agents coding agents review diff! A must read on coding agents and diffs.\n\n"
         + "Agents coding review diff praise. " * 30)
agent_text = (front + "\n\n1. Introduction\n\n" + body + "\n\n2. Orchestrating coding agents\n\n"
              "Kerberoasting is unrelated here but the token appears once. " + body + "\n\nIndex\n\nagents, 1\ndiff, 2\n")
add_book(70, "Agents In Practice", 64, agent_text, tags=(60,), lang=2,
         isbn="978-0-306-40615-7")                                       # valid ISBN-13
add_book(71, "History of Cities", 65, "Medieval guilds, merchants and the plague shaped the city states. " * 120)
add_book(72, "795731065.pdf", 62, "x " * 50, isbn="978-0-306-40615-8")   # raw title + bad checksum
add_book(73, "Il calice della vita (Italian Edition)", 60, "y " * 50, tags=(61,), series=60, sidx=1)
add_book(74, "Il marchio del diavolo", 61, "z " * 50, series=60, sidx=4)
add_book(75, "Hunger Games", 63, "w " * 50, lang=1)
add_book(76, "Hunger Games", 63, "w " * 50, lang=2)                     # same work, other language
lit_text = ("Indice\n\nCapitolo 1\nCapitolo 2\nCapitolo 3\n\n" + "n " * 120 + "\n\nCapitolo 1\n\n" + "Primo capitolo. " * 60
            + "\n\nCapitolo 2\n\n" + "Secondo capitolo. " * 60 + "\n\nCapitolo 3\n\n" + "Terzo capitolo. " * 60)
add_book(77, "Romanzo LIT", 62, lit_text, fmt="LIT")
isbn_text = ("Copyright 2019\nISBN 978-0-306-40615-7\n\n" + "Body text. " * 400 + "\n\nBibliography: see ISBN 9781593272906.\n")
add_book(78, "Book With ISBN In Text", 62, isbn_text)
c.commit(); f.commit()

# EPUB with figures (captions) for the figure index, attached to book 70
def png(w, h):
    b = io.BytesIO(); PIL.new("RGB", (w, h), (90, 30, 30)).save(b, "PNG"); return b.getvalue()
ep = lib / "x/70/f.epub"
with zipfile.ZipFile(ep, "w") as z:
    z.writestr("META-INF/container.xml", '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>')
    z.writestr("OEBPS/content.opf", '<package xmlns="http://www.idpf.org/2007/opf"><manifest><item id="c1" href="c1.xhtml"/></manifest><spine><itemref idref="c1"/></spine></package>')
    z.writestr("OEBPS/c1.xhtml", b"<html><body><h1>Introduction</h1><figure><img src='loop.png' alt='loop'/><figcaption>Figure 1-1. The agent orchestration loop</figcaption></figure>"
               b"<img src='kitchen.png' alt='A brigade kitchen with a head chef'/></body></html>")
    z.writestr("OEBPS/loop.png", png(900, 500)); z.writestr("OEBPS/kitchen.png", png(800, 600))
c.close(); f.close()
m.set_libraries([lib], Path(os.environ["CALIBRE_MCP_DATA"]))
m.LIB.index.sync()

# ------------------------------------------------------------------ 1 quality report
q = m.calibre_quality_report(limit=500)
by = {}
for it in q["book_issues"]:
    by.setdefault(it["check"], set()).add(it["book_id"])
lib_issues = {(i["check"], tuple(i.get("values", [])) or i.get("series")) for i in q["library_issues"]}
check("quality: raw filename title", 72 in by.get("raw_filename_title", set()), by.get("raw_filename_title"))
check("quality: invalid ISBN checksum", 72 in by.get("invalid_isbn", set()) and 70 not in by.get("invalid_isbn", set()))
check("quality: title noise (Italian Edition)", 73 in by.get("title_noise", set()))
check("quality: author name anomaly (| and inverted)", {73, 75} <= by.get("author_name_anomaly", set()), by.get("author_name_anomaly"))
check("quality: unsorted author sort", 72 in by.get("author_sort_unsorted", set()), by.get("author_sort_unsorted"))
check("quality: author variants grouped", ("author_variants", ("Cooper| Glenn", "Glenn Cooper")) in lib_issues, q["library_issues"])
check("quality: tag variants grouped", ("tag_variants", ("Science-Fiction", "science fiction")) in lib_issues)
check("quality: series gaps", any(i["check"] == "series_gaps" and "2, 3" in i["detail"] for i in q["library_issues"]), q["library_issues"])
check("quality: summary counts", q["summary"].get("raw_filename_title") == 1 and q["books_checked"] >= 10)
qq = m.calibre_quality_report(checks=["invalid_isbn"], query="id:>=70")
check("quality: checks + query scope", set(qq["summary"]) == {"invalid_isbn"} and qq["books_checked"] == 9, qq["summary"])
check("quality: unknown check rejected", "Unknown check" in (err(m.calibre_quality_report, checks=["nope"]) or ""))

# ------------------------------------------------------------------ 5 chapter map
ch = m.calibre_get_chapters(70)
kinds = [(x["title"], x["kind"]) for x in ch["chapters"]]
check("chapters: front matter, body chapters, index", kinds[0][1] == "front" and ("1. Introduction", "body") in kinds
      and ("Index", "back") in kinds, kinds)
lit = m.calibre_get_chapters(77)
check("chapters: LIT text via heading detection, printed index skipped",
      lit["method"] == "headings" and [x["title"] for x in lit["chapters"] if x["kind"] == "body"] == ["Capitolo 1", "Capitolo 2", "Capitolo 3"], lit)
epub_toc = m.calibre_get_chapters(1)
check("chapters: EPUB aligned to its own TOC", epub_toc["method"] == "toc", epub_toc)
r = m.calibre_read_text(77, chapter=2, max_chars=50000)
check("read_text chapter: starts at chapter, stops at its end", r["text"].startswith("Capitolo 2") and "Terzo" not in r["text"]
      and r["next_offset"] is None and r["chapter_title"] == "Capitolo 2", r["text"][:80])
check("read_text chapter: out of range", "out of range" in (err(m.calibre_read_text, book_id=77, chapter=99) or ""))

# ------------------------------------------------------------------ 3 chunks: chapter-bounded, contextual, full coverage
import contextlib as _cl
with _cl.redirect_stdout(io.StringIO()):
    m.build_embeddings()
with sqlite3.connect(m.LIB.semantic.path) as db:
    rows = db.execute("SELECT off, len, heading, kind FROM chunks WHERE book=70 ORDER BY off").fetchall()
    meta = dict(db.execute("SELECT key, val FROM meta"))
spans = [(x["offset"], x["offset"] + x["chars"], x["title"]) for x in ch["chapters"]]
inside = all(any(a <= off and off + ln <= b + 1 and h == t for a, b, t in spans) for off, ln, h, _k in rows)
check("chunks never cross chapters and carry the heading", rows and inside, rows[:5])
check("chunks cover the whole book (no sampling at this size)", rows[-1][0] > len(agent_text) * 0.8, rows[-1])
check("index schema 2 with chunk size", meta.get("schema") == "2" and meta.get("chunk") == str(semantic.CHUNK), meta)
pref = semantic.context_prefix("Agents In Practice", "Agent Writer", "2. Orchestrating coding agents")
check("context prefix format", pref == "Agents In Practice - Agent Writer > 2. Orchestrating coding agents: ", pref)

# ------------------------------------------------------------------ 2 hybrid search / 4 front matter + floor
res = m.calibre_search_semantic("coding agents review diff", book_id=70, limit=30)
ps = res["results"][0]["passages"]
check("book scope returns ranked passages with chapters", len(ps) >= 3 and all("chapter" in p for p in ps), ps[:2])
fronts = [i for i, p in enumerate(ps) if p.get("section") == "[front matter]"]
check("front matter labelled and demoted below body", ps[0].get("section") is None and fronts and fronts[0] > 0,
      [(p["chapter"], p.get("section")) for p in ps])
raw = m.LIB.semantic.search("coding agents review diff", m.fold, k=50, book=70)
fm = next(h for h in raw if h["kind"] == "front")
check("demotion halves the fused score of front matter", fm["score"] < max(h["score"] for h in raw if h["kind"] == "body"))
kw = m.calibre_search_semantic("kerberoasting", mode="keyword", limit=3)
check("keyword mode finds the exact rare token", kw["results"] and kw["results"][0]["book_id"] == 70
      and kw["results"][0]["passages"][0]["keyword_match"], kw)
hy = m.calibre_search_semantic("kerberoasting", limit=3)
check("hybrid keeps the exact-term hit at the top", hy["results"][0]["book_id"] == 70 and hy["mode"] == "hybrid")
vec = m.calibre_search_semantic("medieval guilds merchants", mode="vector", limit=2)
check("vector mode returns similarity", vec["results"][0]["book_id"] == 71 and vec["results"][0]["passages"][0]["similarity"] > 0.3, vec)
weak = m.calibre_search_semantic("quantum chromodynamics lattice gauge", limit=3)
check("weak matches flagged + note", weak["count"] == 0 or ("note" in weak and all(p.get("low_confidence")
      for r in weak["results"] for p in r["passages"])), weak)
with sqlite3.connect(m.LIB.semantic.path) as db:   # simulate an index from an older version
    db.execute("UPDATE meta SET val='1' WHERE key='schema'")
m.LIB.semantic._cache = None
check("old index format: clear rebuild message", "older version" in (err(m.calibre_search_semantic, query="agents") or ""))
check("old index format reported in status", "needs_rebuild" in m.status()["features"]["semantic_index"])
with _cl.redirect_stdout(io.StringIO()), _cl.redirect_stderr(io.StringIO()):
    m.build_embeddings()
check("build upgrades the old index", m.status()["features"]["semantic_index"].get("schema") == "2"
      and m.calibre_search_semantic("agents", limit=1)["count"] == 1)

# ------------------------------------------------------------------ 7 figure search
with _cl.redirect_stdout(io.StringIO()), _cl.redirect_stderr(io.StringIO()):
    m.index_figures()
fs = m.calibre_search_figures("orchestration loop diagram")
check("figure search by caption", fs["count"] >= 1 and fs["results"][0]["figure_id"] == "s0-1"
      and fs["results"][0]["book_id"] == 70, fs)
fs2 = m.calibre_search_figures("head chef kitchen")
check("figure search by alt text", fs2["results"] and fs2["results"][0]["figure_id"] == "s0-2", fs2)
check("figure results tell how to view them", fs["results"][0]["view_with"]["tool"] == "calibre_show_images")
check("figure index is hybrid when vectors exist", fs["mode"] == "hybrid", fs["mode"])
info = m.status()["features"]["figure_index"]
check("figure index in status", info["built"] and info["figures"] >= 2, info)

# ------------------------------------------------------------------ 8 ISBN + compare + translations
check("isbn: checksum rules", isbnmod.valid13("9780306406157") and not isbnmod.valid13("9780306406158")
      and isbnmod.valid10("0306406152") and isbnmod.to13("0-306-40615-2") == "9780306406157")
fi = m.calibre_find_isbn(78)
check("isbn from text: copyright-page ISBN ranked first", fi["candidates"][0]["isbn13"] == "9780306406157"
      and fi["candidates"][0]["labeled"], fi)
check("isbn from text: cited ISBN kept but ranked lower", any(x["isbn13"] == "9781593272906" for x in fi["candidates"][1:]))
check("isbn from text: suggestion when none stored", fi["verdict"].startswith("suggested ISBN: 9780306406157"), fi["verdict"])
check("isbn: no valid ISBN", "no valid ISBN" in m.calibre_find_isbn(71)["verdict"])
d = m.calibre_find_duplicates(by="title_author")
g = next((i for i, grp in enumerate(d["duplicates"]) if {b["id"] for b in grp} == {75, 76}), None)
check("duplicates: translations flagged", g is not None and any(n["group"] == g and n["likely_translations"]
      for n in d.get("group_notes", [])), d.get("group_notes"))
cmp_ = m.calibre_compare_books([75, 76])
check("compare: differences + translation warning", "languages" in [x["field"] for x in cmp_["differences"]]
      and "translations" in cmp_.get("warning", ""), cmp_)
cmp2 = m.calibre_compare_books([1, 3])
check("compare: suggests the richer record", cmp2["books"][0]["id"] == 1 and cmp2["suggestion"].startswith("keep 1"), cmp2["books"])

# ------------------------------------------------------------------ 10 legal gate
good = ("# Agent orchestration: a study sheet\n\nSource: Agents In Practice (Agent Writer).\n\n"
        "Keep each task tiny, inspect every change the assistant proposes, and treat its output like a junior "
        "colleague's draft. Plan before delegating; verify after.\n")
r = m.calibre_check_overlap(good, [70])
check("legal gate: transformed notes pass", r["pass"], r["checks"])
copied = good + "\n" + body[:600]
r = m.calibre_check_overlap(copied, [70])
check("legal gate: copied paragraph fails overlap and run", not r["checks"]["longest_run"]["pass"]
      and not r["checks"]["verbatim_overlap"]["pass"] and not r["pass"], r["checks"]["longest_run"])
quoted = good + '\n"' + " ".join(["word"] * 40) + '"\n'
r = m.calibre_check_overlap(quoted, [70])
check("legal gate: long quote fails quote budget", not r["checks"]["quote_budget"]["pass"])
short_q = good + '\nAs the author puts it, "review of every diff and small tasks".\n'
r = m.calibre_check_overlap(short_q, [70])
check("legal gate: short declared quote allowed", r["checks"]["quote_budget"]["pass"] and r["checks"]["longest_run"]["pass"])
mirror = ("# Introduction\n\nSource: Agents In Practice.\n\nNotes.\n\n# Orchestrating coding agents\n\nMore notes.\n")
r = m.calibre_check_overlap(mirror, [70])
check("legal gate: mirrored chapter headings fail", not r["checks"]["heading_mirroring"]["pass"], r["checks"]["heading_mirroring"])
r = m.calibre_check_overlap("# Notes\n\nKeep tasks tiny and verify every change; plan first, review after. " * 2, [70])
check("legal gate: missing attribution fails", not r["checks"]["attribution"]["pass"])
skill = Path(tempfile.mkdtemp()) / "skill"; skill.mkdir(); (skill / "SKILL.md").write_text(good)
env = dict(os.environ, CALIBRE_LIBRARY=str(lib))
ok = subprocess.run([sys.executable, str(here.parent / "calibre_mcp.py"), "--legal-gate", str(skill), "--book", "70"],
                    capture_output=True, text=True, env=env)
(skill / "copied.md").write_text(body[:900])
bad = subprocess.run([sys.executable, str(here.parent / "calibre_mcp.py"), "--legal-gate", str(skill), "--book", "70"],
                     capture_output=True, text=True, env=env)
check("legal gate CLI: exit 0 on pass, 1 on fail", ok.returncode == 0 and bad.returncode == 1 and "FAIL  longest_run" in bad.stdout,
      (ok.returncode, bad.returncode, ok.stdout[-300:], bad.stdout[-300:]))

# ------------------------------------------------------------------ skills shipped (item 10)
for name in ("calibre-distill", "calibre-distill-topic"):
    sk = here.parent / "skills" / name / "SKILL.md"
    txt = sk.read_text() if sk.is_file() else ""
    check(f"skill {name}: frontmatter + uses the gate", txt.startswith("---\nname: " + name) and "calibre_check_overlap" in txt)
print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
sys.exit(1 if FAILS else 0)

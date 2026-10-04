"""Semantic index sanity report + selective rebuild. Usage: python tests/make_fake_library.py && python tests/test_index_report.py"""
import contextlib, io, json, os, shutil, sqlite3, subprocess, sys, tempfile
from pathlib import Path
sys.argv = ["x"]
here = Path(__file__).resolve().parent
sys.path.insert(0, str(here.parent))
os.environ["CALIBRE_MCP_DATA"] = tempfile.mkdtemp()
os.environ["CALIBRE_MCP_EMBED_BACKEND"] = "hash"
os.environ["CALIBRE_MCP_EMBED_MAX_CHUNKS"] = "60"          # small cap so a long book is 'capped'
import calibre_mcp as m

FAILS = []
def check(label, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + label + ("" if cond else f"  -> {str(detail)[:400]}"))
    FAILS.append(label) if not cond else None
def quiet(fn, *a, **kw):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        fn(*a, **kw)
    return out.getvalue()

lib = Path(tempfile.mkdtemp()) / "Report Library"
shutil.copytree(here / "Calibre Library", lib)
c = sqlite3.connect(lib / "metadata.db"); f = sqlite3.connect(lib / "full-text-search.db")
c.execute("INSERT INTO authors(id,name,sort) VALUES (90,'Report Author','Author, Report')")
def add(bid, title, text, fmt="EPUB", with_file=True):
    c.execute("INSERT INTO books(id,title,sort,timestamp,pubdate,series_index,author_sort,path,has_cover,uuid) "
              "VALUES (?,?,?,'2025-01-01','2020-01-01',1,'x',?,0,?)", (bid, title, title, f"x/{bid}", f"u{bid}"))
    c.execute("INSERT INTO books_authors_link(book,author) VALUES (?,90)", (bid,))
    if with_file:
        c.execute("INSERT INTO data(book,format,uncompressed_size,name) VALUES (?,?,1,'f')", (bid, fmt))
    if text is not None:
        f.execute("INSERT INTO books_text(book,timestamp,format,format_size,format_hash,searchable_text,text_size,text_hash) "
                  "VALUES (?,0,?,1,'h',?,?,?)", (bid, fmt, text, len(text), f"t{bid}"))
    (lib / f"x/{bid}").mkdir(parents=True, exist_ok=True)
para = "Agents need review of every diff and small, verifiable tasks to stay reliable. "
add(80, "Good Book", para * 120)
add(81, "Format Deleted In Calibre", para * 60, with_file=False)      # FTS text left, format gone -> fails
add(82, "Layout Noise PDF", " " * 60_000 + para * 3, fmt="PDF")      # mostly whitespace -> sparse
add(83, "Almost Empty", "Cover.", fmt="PDF")                         # no usable passage -> empty
add(84, "Very Long Book", para * 900)                                # > cap -> capped
add(85, "Will Change", para * 80)                                    # stale after a text change
add(86, "Will Be Deleted", para * 80)                                # orphan after deletion
add(87, "Not Indexed Yet", para * 80)                                # missing (excluded from first build)
add(88, "No Text At All", None)                                      # no_text
add(89, "Crashes The Embedder", para * 80)                           # unexpected RuntimeError
c.commit(); c.close(); f.commit(); f.close()
m.set_libraries([lib], Path(os.environ["CALIBRE_MCP_DATA"]))

# an unexpected error inside one book must not stop the build
_orig = m.book_chapters
def flaky(book_id, fmt=None):
    if book_id == 89:
        raise RuntimeError("onnxruntime exploded")
    return _orig(book_id, fmt)
m.book_chapters = flaky
srcs, _ = m._embedding_sources()
first = [b for b, _f, _h in srcs if b != 87]
m.LIB.index.sync()
res = json.loads(quiet(m.build_embeddings, books=first))
m.book_chapters = _orig
check("build continues after failures (ValueError and RuntimeError)", res["failed"] == 2 and res["embedded"] == len(first) - 2, res)
check("failures persisted with their error", set(m.LIB.semantic.failed_books()) == {81, 89})

# change one book's text, delete another
f = sqlite3.connect(lib / "full-text-search.db")
f.execute("UPDATE books_text SET searchable_text=?, text_hash='t85b' WHERE book=85", (para * 81,)); f.commit(); f.close()
c = sqlite3.connect(lib / "metadata.db"); c.execute("DELETE FROM books WHERE id=86"); c.commit(); c.close()
m.LIB.index.sync()

rep = m.calibre_semantic_index_report()
ids = {k: [x["book_id"] for x in v] for k, v in rep["categories"].items()}
check("report: failed with error text", ids["failed"] == [81, 89]
      and any("RuntimeError: onnxruntime exploded" in x["error"] for x in rep["categories"]["failed"]), rep["categories"]["failed"])
check("report: missing (has text, not indexed)", 87 in ids["missing"], ids["missing"])
check("report: stale (text changed)", ids["stale"] == [85], ids["stale"])
check("report: empty", ids["empty"] == [83], ids["empty"])
check("report: sparse (damaged text)", ids["sparse"] == [82], ids["sparse"])
check("report: capped (very long book)", 84 in ids["capped"], ids["capped"])
check("report: no_text", 88 in ids["no_text"], ids["no_text"])
check("report: orphan (deleted from Calibre)", ids["orphan"] == [86], ids["orphan"])
check("report: good book in no category", not any(80 in v for v in ids.values()))
check("report: titles and actions", rep["categories"]["failed"][0]["title"] == "Format Deleted In Calibre"
      and "--retry-failed" in rep["actions"]["failed"])
check("report: integrity ok", rep["integrity"]["ok"] and rep["integrity"]["sqlite_quick_check"] == "ok", rep["integrity"])
check("report: single category filter", list(m.calibre_semantic_index_report("sparse")["categories"]) == ["sparse"])

# fix the failed books, then retry only those
c = sqlite3.connect(lib / "metadata.db")
c.execute("INSERT INTO data(book,format,uncompressed_size,name) VALUES (81,'EPUB',1,'f')"); c.commit(); c.close()
with sqlite3.connect(m.LIB.semantic.path) as db:
    before = {r[0]: r[1] for r in db.execute("SELECT book, MIN(id) FROM chunks GROUP BY book")}
res = json.loads(quiet(m.build_embeddings, retry_failed=True))
check("retry-failed: only the failed books, now fixed", res["embedded"] == 2 and res["failed"] == 0, res)
with sqlite3.connect(m.LIB.semantic.path) as db:
    after = {r[0]: r[1] for r in db.execute("SELECT book, MIN(id) FROM chunks GROUP BY book")}
check("retry-failed: other books untouched", all(after[b] == before[b] for b in before if b not in (81, 89)) and 86 in after)
check("retry-failed: failures cleared", m.LIB.semantic.failed_books() == [])

# --books forces a re-embed even when unchanged, and leaves the rest alone
res = json.loads(quiet(m.build_embeddings, books=[80]))
with sqlite3.connect(m.LIB.semantic.path) as db:
    again = {r[0]: r[1] for r in db.execute("SELECT book, MIN(id) FROM chunks GROUP BY book")}
check("--books: forced re-embed of the selected book", res["embedded"] == 1 and again[80] != after[80])
check("--books: others untouched (no removals in a partial run)", again[84] == after[84] and 86 in again)

# a full run reconciles missing/stale/orphan
quiet(m.build_embeddings)
rep2 = m.calibre_semantic_index_report()
check("full build: missing, stale and orphan resolved", not rep2["categories"]["missing"] and not rep2["categories"]["stale"]
      and not rep2["categories"]["orphan"], rep2["summary"])

# integrity: damage the index on purpose
with sqlite3.connect(m.LIB.semantic.path) as db:
    db.execute("DELETE FROM chunks WHERE book=80 AND id IN (SELECT id FROM chunks WHERE book=80 LIMIT 3)")
m.LIB.semantic._cache = None
integ = m.calibre_semantic_index_report()["integrity"]
check("integrity: count mismatch detected", not integ["ok"] and 80 in integ["count_mismatch"], integ)

# CLI: readable report with re-run commands, and --books parsing
env = dict(os.environ, CALIBRE_LIBRARY=str(lib))
out = subprocess.run([sys.executable, str(here.parent / "calibre_mcp.py"), "--embeddings-report"], capture_output=True, text=True, env=env)
check("CLI report: readable, integrity line, re-run command", out.returncode == 0 and "Integrity: PROBLEMS" in out.stdout
      and "--build-embeddings --books" in out.stdout, out.stdout[-800:] + out.stderr[-400:])
out = subprocess.run([sys.executable, str(here.parent / "calibre_mcp.py"), "--build-embeddings", "--books", "80, 85"],
                     capture_output=True, text=True, env=env)
check("CLI --books '80, 85'", out.returncode == 0 and json.loads(out.stdout)["embedded"] == 2, out.stdout[-300:] + out.stderr[-300:])
check("integrity restored after re-embedding the damaged book", m.calibre_semantic_index_report()["integrity"]["ok"])
print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
sys.exit(1 if FAILS else 0)

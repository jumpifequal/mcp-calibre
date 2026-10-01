"""Regression tests for cases found on a real library (duplicates false positives, similar-books fallback).
Usage: python tests/make_fake_library.py && python tests/test_real_cases.py"""
import os, shutil, sqlite3, sys, tempfile
from pathlib import Path
sys.argv = ["x"]
here = Path(__file__).resolve().parent
sys.path.insert(0, str(here.parent))
os.environ["CALIBRE_MCP_DATA"] = tempfile.mkdtemp()
import calibre_mcp as m

lib = Path(tempfile.mkdtemp()) / "Real Cases"
shutil.copytree(here / "Calibre Library", lib)
c = sqlite3.connect(lib / "metadata.db")
f = sqlite3.connect(lib / "full-text-search.db")
c.execute("INSERT INTO authors(id,name,sort) VALUES (10,'Fiabe Illustrate','x'),(11,'H. P. Lovecraft','x'),"
          "(12,'Suzanne Collins','x'),(13,'Francesco De Sanctis','x'),(14,'Gene Kim','x')")
c.execute("INSERT INTO series(id,name,sort) VALUES (5,'Hunger Games','Hunger Games')")
books = [  # id, title, author, series_index or None
    (20, "Le più belle Fiabe del Mondo: I Fratelli Grimm", 10, None),
    (21, "Le più belle Fiabe del Mondo: Favole di Esopo", 10, None),
    (22, "Tutti I Racconti (1923-1926)", 11, None),
    (23, "Tutti I Racconti (1927-1930)", 11, None),
    (24, "Hunger Games", 12, 3), (25, "Hunger Games: La ragazza di fuoco", 12, 1),
    (26, "Storia Della Letteratura Italiana (Biblioteca Della Pleiade)", 13, None),
    (27, "Storia Della Letteratura Italiana", 13, None),
    (28, "Kubernetes Patterns", 14, None), (29, "Kubernetes Patterns (2nd edition)", 14, None),
]
for bid, title, au, si in books:
    c.execute("INSERT INTO books(id,title,sort,timestamp,pubdate,series_index,author_sort,path,has_cover,uuid) "
              "VALUES (?,?,?,?,?,?,?,?,0,?)", (bid, title, title, "2011-05-09", "2011-01-01", si or 1, "x", f"x/{bid}", f"u{bid}"))
    c.execute("INSERT INTO books_authors_link(book,author) VALUES (?,?)", (bid, au))
    if si:
        c.execute("INSERT INTO books_series_link(book,series) VALUES (?,5)", (bid,))
# a metadata-poor book (no tags, no series, unique author/publisher) with real text, plus two related texts
texts = {
    30: "agentic coding assistants generate pull requests; review every diff, run the test suite, keep tasks small, "
        "checkpoint often with git, agents hallucinate apis, sandbox the agents, context window management " * 40,
    31: "coding assistants and agents: review each diff, test suite first, small tasks, git checkpoint, sandbox, "
        "context window, hallucinated apis in generated pull requests " * 30,
    32: "medieval history of the italian city states, guilds, merchants, the black death and the renaissance " * 40,
}
c.execute("INSERT INTO authors(id,name,sort) VALUES (15,'Solo Author','x'),(16,'Other Author','x'),(17,'Historian','x')")
for bid, au in ((30, 15), (31, 16), (32, 17)):
    c.execute("INSERT INTO books(id,title,sort,timestamp,pubdate,series_index,author_sort,path,has_cover,uuid) "
              "VALUES (?,?,?,?,?,1,'x',?,0,?)", (bid, f"Book {bid}", f"Book {bid}", "2025-11-24", "2025-01-01", f"x/{bid}", f"u{bid}"))
    c.execute("INSERT INTO books_authors_link(book,author) VALUES (?,?)", (bid, au))
    c.execute("INSERT INTO data(book,format,uncompressed_size,name) VALUES (?,'EPUB',1,'f')", (bid,))
    f.execute("INSERT INTO books_text(book,timestamp,format,format_size,format_hash,searchable_text,text_size,text_hash) "
              "VALUES (?,0,'EPUB',1,'h',?,?,?)", (bid, texts[bid], len(texts[bid]), f"t{bid}"))
c.commit(); f.commit(); c.close(); f.close()

m.set_libraries([lib], Path(os.environ["CALIBRE_MCP_DATA"]))
m.LIB.index.sync()
FAILS = []
def check(label, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + label + ("" if cond else f"  -> {detail}"))
    FAILS.append(label) if not cond else None

groups = [{b["id"] for b in g} for g in m.calibre_find_duplicates(by="title_author")["duplicates"]]
check("true dup: bracketed collection note ignored", {26, 27} in groups, groups)
check("true dup: edition note ignored", {28, 29} in groups, groups)
check("collection volumes NOT dups (subtitle kept)", not any(g & {20, 21} == {20, 21} for g in groups), groups)
check("numbered parts NOT dups ((1923-1926))", not any(g >= {22, 23} for g in groups), groups)
check("series volumes NOT dups", not any(g >= {24, 25} for g in groups), groups)
check("existing fixture dup still found", {1, 3} in groups, groups)
loose = [{b["id"] for b in g} for g in m.calibre_find_duplicates(by="title_author", loose=True)["duplicates"]]
check("loose mode groups subtitled volumes", any(g >= {20, 21} for g in loose), loose)
check("loose mode still respects series numbers", not any(g >= {24, 25} for g in loose), loose)

sim = m.calibre_similar_books(30)
check("similar auto falls back to content", sim["method"] == "content", sim)
check("content similar ranks related text first", sim["similar"] and sim["similar"][0]["book_id"] == 31, sim)
check("unrelated text not first", all(s["book_id"] != 32 for s in sim["similar"][:1]), sim)
check("explicit content method", m.calibre_similar_books(30, method="content")["method"] == "content")
check("metadata method unchanged when it has data", m.calibre_similar_books(1, method="auto")["method"] == "metadata")
print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
sys.exit(1 if FAILS else 0)

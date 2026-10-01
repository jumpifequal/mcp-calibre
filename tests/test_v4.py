"""Functional tests for v4 features. Usage: python tests/make_fake_library.py && python tests/test_v4.py"""
import json, os, sys, tempfile
from pathlib import Path
sys.argv = ["x"]
here = Path(__file__).resolve().parent
sys.path.insert(0, str(here.parent))
os.environ.setdefault("CALIBRE_MCP_DATA", tempfile.mkdtemp())
import calibre_mcp as m

m.set_libraries([here / "Calibre Library"], Path(os.environ["CALIBRE_MCP_DATA"]))
m.LIB.index.sync()
FAILS = []


def check(label, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + label + ("" if cond else f"  -> {detail}"))
    if not cond:
        FAILS.append(label)


def ids(q, **kw):
    """Sorted ids (ordering is tested separately)."""
    return sorted(b["id"] for b in m.calibre_search_books(query=q, limit=200, **kw)["books"])


def err(fn, **kw):
    try:
        fn(**kw)
        return None
    except Exception as e:  # noqa: BLE001
        return str(e)

# --- query language
check("cql bare word", ids("sicurezza") == [1, 3], ids("sicurezza"))
check("cql tag + not", ids("tag:security and not tag:malware") == [1, 3], ids("tag:security and not tag:malware"))
check("cql or + parens", sorted(ids("(author:honig or author:rossi) and tag:networking")) == [1, 3])
check("cql exact", ids('author:"=mario rossi"') == [1, 3] and not ids('author:"=rossi"'))
check("cql regex", ids("title:~^Practical") == [2])
check("cql accents", ids("title:sécurité") == [] and ids("title:sicurezza") == [1, 3])
check("cql rating stars", ids("rating:>=4") == [2] and not ids("rating:>4"))
check("cql pubdate", ids("pubdate:>2020") == [3] and ids("pubdate:2019") == [1])
check("cql pubdate undefined", ids("pubdate:false") == [2])
check("cql date relative", ids("date:<today") == [1, 2, 3] and ids("date:>=2026-01") == [2])
check("cql formats", ids("formats:pdf") == [2] and sorted(ids("not formats:pdf")) == [1, 3])
check("cql identifiers", sorted(ids("identifiers:isbn:true")) == [1, 2, 3] and ids("isbn:1593272906") == [2])
check("cql size units", ids("size:>1500") == [2] and ids("size:<1K") == [1] and ids("size:>1M") == [])
check("cql cover", ids("cover:true") == [1])
check("cql id", ids("id:>=2") == [2, 3] or sorted(ids("id:>=2")) == [2, 3])
check("cql #text multiple", ids("#genre:netsec") == [1] and ids('#genre:"=reverse engineering"') == [2])
# yes/no columns: Calibre tristate semantics (default). #read: book1 Yes, book2 No, book3 unset
check("bool tristate yes/no", ids("#read:yes") == [1] and ids("#read:no") == [2] and ids("#read:checked") == [1])
check("bool tristate true = set", ids("#read:true") == [1, 2])
check("bool tristate false/empty = unset", ids("#read:false") == [3] and ids("#read:empty") == [3] and ids("#read:blank") == [3])
check("bool italian si", ids("#read:sì") == [1])
check("bool invalid value", "Invalid yes/no" in (err(m.calibre_search_books, query="#read:maybe") or ""))
check("heading resolves (Must Read)", ids("#mustread:yes") == [2] and ids("#MustRead:no") == [3] and ids("#must_read:empty") == [1])
check("italian column", ids("#letto:yes") == [1] and ids("#letto:false") == [2, 3])
check("cql #int", ids("#pages:>500") == [2])
check("cql #rating", ids("#myrating:5") == [2])
check("cql #datetime", ids("#finished:2025-06") == [1] and ids("#finished:false") == [2, 3] or sorted(ids("#finished:false")) == [2, 3])
check("cql #series", ids("#course:sans") == [2])
check("cql vl (tristate)", ids('vl:"Unread security"') == [3])
check("cql saved search", ids('search:"Big books"') == [2])
check("virtual_library param", sorted(m.calibre_search_books(virtual_library="italiano")["books"][i]["id"] for i in range(1)) == [1])
check("vl recursion guarded", "Recursive" in (err(m.calibre_search_books, query='vl:"Loop A"') or ""))
check("composite rejected", "composite" in (err(m.calibre_search_books, query="#summary:x") or ""))
check("unknown field msg", "Supported" in (err(m.calibre_search_books, query="foo:bar") or ""))
check("unknown custom msg", "#must_read (Must Read)" in (err(m.calibre_search_books, query="#nope:x") or ""))
check("syntax error msg", err(m.calibre_search_books, query="(tag:x") is not None)
check("regex too long", "Regex" in (err(m.calibre_search_books, query="title:~" + "a" * 300) or ""))
check("regex keeps \\d escapes", ids('title:"~^Sicurezza \\w+ reti"') == [1, 3])
check("redos nested quantifier rejected", "nested" in (err(m.calibre_search_books, query='title:"~(a+)+$"') or ""))
check("backreference rejected", "nested" in (err(m.calibre_search_books, query='title:"~(a)\\1"') or ""))
check("injection is data", ids("title:\"x') OR 1=1 --\"") == [])
check("sort series", [b["id"] for b in m.calibre_search_books(sort="series")["books"]][0] == 1)
check("sort added desc", [b["id"] for b in m.calibre_search_books(sort="added", descending=True)["books"]] == [2, 3, 1])
check("query + filter AND", ids("tag:security", author="sikorski") == [2])

# --- custom columns, VLs, progress, notes, cover, duplicates, similar
cc = {c["label"]: c for c in m.calibre_list_custom_columns()["columns"]}
check("custom columns listed", set(cc) == {"#genre", "#read", "#pages", "#myrating", "#finished", "#course", "#summary",
                                         "#must_read", "#letto"} and cc["#must_read"]["name"] == "Must Read")
check("custom top values", "Netsec" in cc["#genre"]["top_values"])
b1, b2 = m.calibre_get_book(1), m.calibre_get_book(2)
cv = {k: v["value"] for k, v in b1["custom"].items()}
check("get_book custom", cv == {"#genre": ["Netsec", "Manuale"], "#read": True, "#pages": 220,
                               "#finished": "2025-06-15", "#letto": True}, b1.get("custom"))
check("get_book custom carries heading", b2["custom"]["#must_read"] == {"name": "Must Read", "value": True})
check("get_book bool No kept", m.calibre_get_book(3)["custom"]["#must_read"]["value"] is False)
check("get_book custom series/rating", b2["custom"]["#course"]["value"] == "SANS 610 [3]" and b2["custom"]["#myrating"]["value"] == 5.0, b2.get("custom"))
check("get_book progress latest device", b1["reading_progress"]["percent"] == 55.0, b1.get("reading_progress"))
check("get_book notes", any("NSA" in n["excerpt"] for n in b2.get("notes", [])), b2.get("notes"))
vls = m.calibre_list_virtual_libraries()
vlmap = {v["name"]: v for v in vls["virtual_libraries"]}
check("list VLs counts", vlmap["Unread security"]["books"] == 1 and "error" in vlmap["Loop A"])
check("saved searches", vls["saved_searches"][0]["books"] == 1)
rp = m.calibre_reading_progress(status="reading")
check("progress reading", [r["book_id"] for r in rp["books"]] == [1])
check("progress finished", [r["book_id"] for r in m.calibre_reading_progress(status="finished")["books"]] == [2])
nt = m.calibre_get_notes(field="authors")
check("notes by field", nt["count"] == 1 and nt["notes"][0]["name"] == "Michael Sikorski", nt)
check("notes by name/query", m.calibre_get_notes(name="sikor")["count"] == 1 and m.calibre_get_notes(query="networking")["count"] == 1)
img = m.calibre_get_cover(1, max_px=256)
check("cover image resized", img.data[:4] in (b"\x89PNG", b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xdb") and len(img.data) > 100)
check("cover missing", "no cover" in (err(m.calibre_get_cover, book_id=2) or ""))
dups = m.calibre_find_duplicates(by="title_author")
check("duplicates title_author", dups["groups"] == 1 and {d["id"] for d in dups["duplicates"][0]} == {1, 3}, dups)
check("duplicates isbn", m.calibre_find_duplicates(by="isbn")["groups"] == 1)
sim = m.calibre_similar_books(1, method="metadata")
check("similar metadata", sim["similar"][0]["book_id"] == 3, sim)

# --- markdown
md = m.calibre_read_section(1, section=0, output="markdown")
check("epub markdown heading", md["text"].startswith("# Capitolo 1"), md["text"][:60])
pdfmd = m.calibre_read_section(2, start_page=1, end_page=1, output="markdown")
check("pdf markdown fallback note", "note" in pdfmd or pdfmd["output"] == "markdown")

# --- resources / prompts
check("resource book card", "# Sicurezza delle reti" in m.resource_book("1") and "Contents" in m.resource_book("1"))
check("resource section md", m.resource_section("1", "1").startswith("## "))
check("resource highlights", "firewall" in m.resource_highlights("1"))
check("prompt text", "calibre_get_toc" in m.prompt_summarize_book("1"))

# --- multi-library
lib2 = Path(tempfile.mkdtemp()) / "Second Library"
import shutil
shutil.copytree(here / "Calibre Library", lib2)
m.set_libraries([here / "Calibre Library", lib2], Path(os.environ["CALIBRE_MCP_DATA"]))
check("list libraries", [l["name"] for l in m.calibre_list_libraries()["libraries"]] == ["Calibre Library", "Second Library"])
check("library param routes", m.calibre_get_book(1, library="Second Library")["title"] == "Sicurezza delle reti")
check("library unknown", "Available" in (err(m.calibre_get_book, book_id=1, library="nope") or ""))
check("status features", m.status()["features"]["custom_columns"] == 9)
check("resource card shows heading", "**Must Read** (#must_read): True" in m.resource_book("2"))

# two-state mode (Calibre pref bools_are_tristate = false): false/no include unset
import sqlite3 as _sq
_db = _sq.connect(here / "Calibre Library" / "metadata.db")
_db.execute("INSERT OR REPLACE INTO preferences(key,val) VALUES ('bools_are_tristate','false')"); _db.commit()
check("bool two-state", ids("#read:true") == [1] and ids("#read:false") == [2, 3] and ids("#read:no") == [2, 3])
_db.execute("DELETE FROM preferences WHERE key='bools_are_tristate'"); _db.commit(); _db.close()

print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
sys.exit(1 if FAILS else 0)

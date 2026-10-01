"""Snippet selection tests (query-aware highlighting). Usage: python tests/make_fake_library.py && python tests/test_snippets.py"""
import os, shutil, sqlite3, sys, tempfile
from pathlib import Path
sys.argv = ["x"]
here = Path(__file__).resolve().parent
sys.path.insert(0, str(here.parent))
os.environ["CALIBRE_MCP_DATA"] = tempfile.mkdtemp()
import calibre_mcp as m
from mcpcalibre import highlight as h

FAILS = []
def check(label, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + label + ("" if cond else f"  -> {detail}"))
    FAILS.append(label) if not cond else None
fold = m.fold

# --- unit: the real-library case. Front matter repeats "prompt"; the matching passage is deep inside.
front = "Prompt Engineering for LLMs. Praise: the best prompt book. Prompt prompt prompt. " * 3
filler = "Lorem ipsum dolor sit amet consectetur adipiscing elit. " * 400
deep = ("If you put user content into the system prompt, attackers can override your instructions; "
        "this is the core of indirect prompt injection via retrieved documents.")
text = front + filler + deep + filler
deep_at = text.index(deep)
q = 'jailbreak* OR "malicious prompt" OR "system prompt" NEAR(override*, 10)'
sn = h.best_snippets(text, h.clauses_from_raw(q, fold), 2, 300, fold)
check("raw: best snippet is the real passage, not front matter", sn and abs(sn[0]["offset"] - deep_at) < 200, sn[:1])
check("raw: snippet reports matched clauses", sn and '"system prompt"' in sn[0]["matched"] and "override*" in sn[0]["matched"], sn[:1])
check("raw: no snippet from a lone word of a phrase", all("system" in s["text"].lower() for s in sn), sn)

# NOT branches never drive highlighting
sn = h.best_snippets(text, h.clauses_from_raw('"system prompt" NOT lorem', fold), 3, 200, fold)
check("raw: NOT terms excluded", sn and all("lorem" not in s["matched"] for s in sn), sn)

# NEAR proximity, order-free
t2 = "alpha beta gamma. " * 50 + "override one two three system prompt end. " + "zeta " * 200 + "system prompt alone. " + "x " * 50
sn = h.best_snippets(t2, h.clauses_from_raw('NEAR("system prompt" override*, 5)', fold), 1, 120, fold)
check("raw: NEAR prefers the proximate occurrence", sn and "override" in sn[0]["text"], sn)

# all-mode: window containing BOTH words beats the first occurrence of one
t3 = "lateral thinking is great. " + "pad " * 300 + "lateral movement with kerberos tickets. " + "pad " * 300
sn = h.best_snippets(t3, h.clauses_from_terms(["lateral", "movement"], [False, False], False, fold), 1, 120, fold)
check("all: window with every term wins", sn and "movement" in sn[0]["text"], sn)

# whole-word semantics match FTS (no 'injections' for 'injection' unless prefix/stemmed)
t4 = "many injections here. " + "pad " * 100 + "one injection there."
sn = h.best_snippets(t4, h.clauses_from_terms(["injection"], [False], False, fold), 2, 60, fold)
check("whole words by default", len(sn) == 1 and "injection there" in sn[0]["text"], sn)
sn = h.best_snippets(t4, h.clauses_from_terms(["injection"], [True], False, fold), 2, 60, fold)
check("prefix* matches variants", len(sn) == 2, sn)

# accents fold both ways
sn = h.best_snippets("La sécurité à l'école.", h.clauses_from_terms(["securite"], [False], False, fold), 1, 60, fold)
check("accent-insensitive", len(sn) == 1, sn)

# --- integration through the tool, on a library copy with the real-case text
lib = Path(tempfile.mkdtemp()) / "Snip"
shutil.copytree(here / "Calibre Library", lib)
c = sqlite3.connect(lib / "metadata.db"); f = sqlite3.connect(lib / "full-text-search.db")
c.execute("INSERT INTO books(id,title,sort,timestamp,pubdate,series_index,author_sort,path,has_cover,uuid) "
          "VALUES (40,'Prompt Engineering Test','x','2025-01-01','2025-01-01',1,'x','x/40',0,'u40')")
c.execute("INSERT INTO data(book,format,uncompressed_size,name) VALUES (40,'PDF',1,'f')")
f.execute("INSERT INTO books_text(book,timestamp,format,format_size,format_hash,searchable_text,text_size,text_hash) "
          "VALUES (40,0,'PDF',1,'h',?,?,'t40')", (text, len(text)))
c.commit(); f.commit(); c.close(); f.close()
m.set_libraries([lib], Path(os.environ["CALIBRE_MCP_DATA"]))
m.LIB.index.sync()
r = m.calibre_search_fulltext(query=q, mode="raw", snippets_per_book=1, snippet_chars=300, book_ids=[40])
s0 = r["results"][0]["snippets"][0]
check("tool raw: snippet lands on the passage", abs(s0["offset"] - deep_at) < 200, s0)
rt = m.calibre_read_text(40, format="PDF", offset=s0["offset"], center=True, max_chars=400)["text"]
check("tool raw: offset usable with read_text", "system prompt" in rt, rt[:120])
r = m.calibre_search_fulltext(query="prompt injection", mode="phrase", book_ids=[40], snippets_per_book=1)
check("tool phrase still works", "prompt injection" in r["results"][0]["snippets"][0]["text"].lower(), r)
print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
sys.exit(1 if FAILS else 0)

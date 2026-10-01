"""Stemming + semantic (hash backend) + fulltext filters. Separate process: env flags are read at import."""
import json, os, sys, tempfile
from pathlib import Path
sys.argv = ["x"]
here = Path(__file__).resolve().parent
sys.path.insert(0, str(here.parent))
os.environ["CALIBRE_MCP_DATA"] = tempfile.mkdtemp()
os.environ["CALIBRE_MCP_STEMMING"] = "1"
os.environ["CALIBRE_MCP_EMBED_BACKEND"] = "hash"
import calibre_mcp as m
m.set_libraries([here / "Calibre Library"], Path(os.environ["CALIBRE_MCP_DATA"]))
FAILS = []
def check(label, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + label + ("" if cond else f"  -> {detail}"))
    FAILS.append(label) if not cond else None

r = m.LIB.index.sync()
check("sync with stemming", r.get("added") == 1 and "stem_backfilled" in r, r)
m.calibre_read_text(2)  # PDF text extracted locally -> indexed in both indexes
plain = m.calibre_search_fulltext(query="detections")
stem = m.calibre_search_fulltext(query="detections", stemmed=True)
check("stemmed finds variants (English)", plain["count"] == 0 and stem["count"] == 1, (plain, stem))
snip = stem["results"][0].get("snippets") or [{}]
check("stemmed snippet highlighted", "detection" in snip[0].get("text", ""), stem)
check("porter is English-only (documented)", m.calibre_search_fulltext(query="segmentazioni", stemmed=True)["count"] == 0)
check("fulltext query_filter", m.calibre_search_fulltext(query="firewall", query_filter="#read:true")["count"] == 1
      and m.calibre_search_fulltext(query="firewall", query_filter="#read:false")["count"] == 0)
check("fulltext virtual_library", m.calibre_search_fulltext(query="firewall", virtual_library="Italiano")["count"] == 1)
# backfill: fresh process state simulated by dropping stem_state
with m.LIB.index._rw() as c:
    c.execute("DELETE FROM stem_state"); c.execute("DELETE FROM fts_stem")
r2 = m.LIB.index.sync()
check("stem backfill", r2.get("stem_backfilled") == 2, r2)

# semantic (hash backend: lexical, deterministic, no model download)
import io, contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    m.build_embeddings()
res = json.loads(buf.getvalue())
check("embeddings built", res["embedded"] == 2 and res["failed"] == 0, res)
with contextlib.redirect_stdout(io.StringIO()):
    m.build_embeddings()
check("embeddings incremental", m.LIB.semantic.info()["books"] == 2)
sem = m.calibre_search_semantic(query="process hollowing detection sandbox")
check("semantic top book", sem["results"][0]["book_id"] == 2, sem)
off = sem["results"][0]["passages"][0]["offset"]
check("semantic offset usable", "hollowing" in m.calibre_read_text(2, offset=off, max_chars=400)["text"])
check("semantic filter", all(r["book_id"] == 1 for r in m.calibre_search_semantic(query="firewall", query_filter="languages:ita")["results"]))
check("similar semantic", m.calibre_similar_books(1, method="semantic")["method"] == "semantic")
st = m.status()["features"]
check("status semantic info", st["semantic_index"]["built"] and st["stemming"], st)
print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
sys.exit(1 if FAILS else 0)

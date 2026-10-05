# Usage: python tests/make_fake_library.py ; set CALIBRE_LIBRARY=tests\Calibre Library ; python tests/test_skills.py
"""Checks the Agent Skills in skills/ against the server.

Static: front matter, name == folder, description length, every calibre_* tool and every keyword argument written
in a skill exists in the server, every --flag exists in the CLI, the book-agent template is complete.
Dynamic: the call sequences the skills prescribe run on the fake library (hash embedding backend, own data dir).
"""
import inspect
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("CALIBRE_LIBRARY", str(ROOT / "tests" / "Calibre Library"))
os.environ["CALIBRE_MCP_DATA"] = tempfile.mkdtemp(prefix="calibre-skills-test-")
os.environ["CALIBRE_MCP_EMBED_BACKEND"] = "hash"
sys.argv = ["x"]
sys.path.insert(0, str(ROOT))
import calibre_mcp as m  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  -> {detail}"))
    if not cond:
        fails.append(name)


skills = sorted((ROOT / "skills").glob("*/SKILL.md"))
check("at least four skills", len(skills) >= 4, [p.parent.name for p in skills])
server_src = (ROOT / "calibre_mcp.py").read_text(encoding="utf-8")
cli_flags = set(re.findall(r'add_argument\(\s*"(--[a-z0-9-]+)"', server_src))

# ------------------------------------------------------------------------------------------------ static
for path in skills:
    name = path.parent.name
    text = path.read_text(encoding="utf-8")
    fm = re.match(r"---\n(.*?)\n---\n", text, re.S)
    check(f"{name}: has front matter", bool(fm))
    if not fm:
        continue
    meta = dict(re.findall(r"^(\w+):\s*(.*)$", fm.group(1), re.M))
    check(f"{name}: name matches folder", meta.get("name") == name, meta.get("name"))
    desc = meta.get("description", "")
    check(f"{name}: description present and <= 1024 chars", 40 < len(desc) <= 1024, len(desc))
    body = text[fm.end():]
    bad_tools, bad_args = set(), []
    for call in re.finditer(r"\b(calibre_[a-z_]+)(\(([^()]*(?:\([^()]*\)[^()]*)*)\))?", body):
        tool, args = call.group(1), call.group(3) or ""
        fn = getattr(m, tool, None)
        if fn is None:
            if tool != "calibre_mcp":
                bad_tools.add(tool)
            continue
        params = set(inspect.signature(fn).parameters)
        for kw in re.findall(r"(?<![\w-])(\w+)=", args):
            if kw not in params:
                bad_args.append(f"{tool}({kw}=)")
    check(f"{name}: every calibre_* tool exists", not bad_tools, sorted(bad_tools))
    check(f"{name}: every keyword argument exists in the tool signature", not bad_args, bad_args)
    flags = set(re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]+)", body))
    check(f"{name}: every --flag exists in the CLI", flags <= cli_flags, sorted(flags - cli_flags))
    check(f"{name}: states the untrusted-content rule", "untrusted" in body.lower())

agent = (ROOT / "skills" / "calibre-book-agent" / "SKILL.md").read_text(encoding="utf-8")
tpl = re.search(r"```markdown\n(.*?)\n```", agent, re.S)
check("book-agent: template block present", bool(tpl))
if tpl:
    t = tpl.group(1)
    check("book-agent template: front matter with name and description", bool(re.match(r"---\nname: book-\{\{slug\}\}\ndescription: .+\n", t)))
    for section in ("Thesis", "Principles", "Decision heuristics", "Vocabulary", "Questions you ask first", "Blind spots and limits",
                    "Grounding protocol", "How you answer", "When you debate or collaborate", "Source"):
        check(f"book-agent template: section '{section}'", f"## {section}" in t)
    for label in ("grounded", "inferred", "outside the book"):
        check(f"book-agent template: label '{label}'", label in t)
    filled = re.sub(r"\{\{(\w+)\}\}", "x", t)
    check("book-agent template: every placeholder is a plain {{name}}", "{{" not in filled and "}}" not in filled)
    check("book-agent template: no placeholder left unnamed", not re.search(r"\{\{\s*\}\}", t))

redteam = (ROOT / "skills" / "calibre-book-redteam" / "SKILL.md").read_text(encoding="utf-8")
for rating in ("Supported", "Qualified", "Contested", "Contradicted", "Unverifiable here"):
    check(f"book-redteam: rating '{rating}' defined", f"| {rating} |" in redteam)
check("book-redteam: states its honest limit", "Absence of contradiction is not support" in redteam)

# ------------------------------------------------------------------------------------------------ dynamic
m.set_libraries([m.detect_library()], m.default_data_dir())
m.LIB.index.sync()
m.build_embeddings()
BOOK = 1

book = m.calibre_get_book(book_id=BOOK)
check("get_book returns the book", book.get("id") == BOOK or book.get("book_id") == BOOK or "title" in book, list(book)[:6])
chap = m.calibre_get_chapters(book_id=BOOK)
chapters = chap.get("chapters", [])
check("get_chapters returns a chapter map", bool(chapters), list(chap))
body_chap = next((i for i, c in enumerate(chapters) if c.get("kind", "body") == "body"), 0)
rt = m.calibre_read_text(book_id=BOOK, chapter=body_chap)
check("read_text(chapter=N) returns text", bool(rt.get("text")), list(rt))

sem = m.calibre_search_semantic(query="firewall perimeter defence", book_id=BOOK, mode="hybrid")
check("semantic search inside one book (book-agent grounding step)", "error" not in sem and (sem.get("results") or sem.get("passages")), str(sem)[:200])
lib = m.calibre_search_semantic(query="network segmentation", alt_queries=["segmentazione della rete"], mode="hybrid", limit=10)
check("library-wide semantic search with alt_queries (red-team step)", "error" not in lib and bool(lib.get("results")), str(lib)[:200])
flt = m.calibre_search_semantic(query="network segmentation", mode="hybrid", limit=10, query_filter="tag:security")
check("semantic search with a Calibre query_filter", "error" not in flt, str(flt)[:200])

hit = m.calibre_find_in_book(book_id=BOOK, query="firewall", context_chars=100)
check("find_in_book finds the term", bool(hit.get("results") or hit.get("matches") or hit.get("hits")), list(hit))
ph = m.calibre_search_fulltext(query="firewall", mode="phrase")
check("fulltext phrase search", bool(ph.get("results")), list(ph))
sim = m.calibre_similar_books(book_id=BOOK, method="semantic")
check("similar_books(method='semantic') runs", isinstance(sim, dict) and "error" not in sim, str(sim)[:200])

sample = ("Notes in my own words. The perimeter is only the first layer of defence, so a network is split into "
          "segments to shrink the attack surface. Source: Sicurezza delle reti, Mario Rossi. " * 2)
gate = m.calibre_check_overlap(text=sample, book_ids=[BOOK])
check("check_overlap returns a verdict with per-check results", isinstance(gate, dict) and ("pass" in gate or "verdict" in gate or "passed" in gate or "checks" in gate), list(gate))

print(f"\n{len(fails)} failure(s)")
sys.exit(1 if fails else 0)

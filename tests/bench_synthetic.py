#!/usr/bin/env python3
"""Reproducible performance benchmark on a SYNTHETIC Calibre library.

It builds a library of N fake books whose text follows a Zipf word distribution, then times the operations an
assistant uses most. Nothing here is a real library: the figures show how the server scales, not how your own
books will behave (real text is less uniform, PDFs and LIT/MOBI add extraction work, a spinning disk is slower).

    python tests/bench_synthetic.py                       # 1,500 books, about 525 MB of text (the documented run)
    python tests/bench_synthetic.py --books 300           # quicker
    python tests/bench_synthetic.py --semantic-books 100  # also the semantic index path (hash backend, see below)
    python tests/bench_synthetic.py --json out.json       # machine-readable results

The metadata tables get the indexes a real Calibre library has (link tables by book and by item, data/comments/
identifiers by book): without them SQLite scans every link table for every book and metadata searches look
artificially slow.

Needs only the server's own requirements and numpy. The library is created in a temporary folder and removed
at the end (--keep to inspect it). The semantic part uses the offline `hash` embedding backend: it measures the
index build and the hybrid ranking path (passages, vectors, fusion), NOT the speed of the real embedding model,
which depends on your CPU (see docs/en/performance.md).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--books", type=int, default=1500, help="number of synthetic books (default 1500)")
ap.add_argument("--avg-kb", type=int, default=296, help="average text size per book in KB (default 296 -> ~525 MB for 1,500 books)")
ap.add_argument("--seed", type=int, default=7)
ap.add_argument("--dir", help="working folder (default: a temporary one)")
ap.add_argument("--keep", action="store_true", help="keep the generated library and sidecar")
ap.add_argument("--runs", type=int, default=30, help="timed repetitions per operation (default 30)")
ap.add_argument("--semantic-books", type=int, default=0, help="also build the semantic index for this many books (hash backend)")
ap.add_argument("--json", help="write the results to this file")
args = ap.parse_args()

try:
    import numpy as np
except ImportError:
    sys.exit("numpy is required: pip install numpy")

work = Path(args.dir) if args.dir else Path(tempfile.mkdtemp(prefix="calibre-mcp-bench-"))
lib_root = work / "Calibre Library"
data_dir = work / "sidecar"
lib_root.mkdir(parents=True, exist_ok=True)
data_dir.mkdir(parents=True, exist_ok=True)
rng = np.random.default_rng(args.seed)


# ---------------------------------------------------------------------------------------------- generator
def make_vocab(n: int = 50_000) -> np.ndarray:
    syl = np.array([c + v for c in "bcdfglmnprstvz" for v in "aeiou"] + [c + v + "n" for c in "bdgklmprst" for v in "aeiou"])
    words: set[str] = set()
    while len(words) < n:
        k = rng.integers(2, 5, size=n)
        for kk in k:
            words.add("".join(rng.choice(syl, size=kk)))
            if len(words) >= n:
                break
    return np.array(sorted(words))


VOCAB = make_vocab()
ZIPF = 1.0 / np.arange(1, len(VOCAB) + 1) ** 1.07
CDF = np.cumsum(ZIPF / ZIPF.sum())
# needle terms (not in the pseudo-vocabulary): word -> share of books containing it
NEEDLES = {"firewall": 0.05, "kerberos": 0.02, "segmentation": 0.30, "lateral movement": 0.015}
TAGS = ["security", "networking", "malware", "cloud", "ai", "history", "fiction", "science", "math", "law", "cooking", "travel"] \
    + [f"topic{i}" for i in range(28)]
LANGS = [("ita", 1), ("eng", 2)]


def book_text(n_words: int, lang: str, needles: list[str]) -> str:
    idx = np.searchsorted(CDF, rng.random(n_words))
    idx = np.minimum(idx, len(VOCAB) - 1)
    words = VOCAB[idx].tolist()
    for nd in needles:
        for _ in range(int(rng.integers(3, 12))):
            pos = int(rng.integers(0, max(1, n_words - 3)))
            words[pos] = nd
    head = "Capitolo" if lang == "ita" else "Chapter"
    chap = max(1, n_words // 6000)
    step = n_words // chap
    parts = []
    for c in range(chap):
        seg = words[c * step:(c + 1) * step]
        paras = [" ".join(seg[i:i + 90]).capitalize() + "." for i in range(0, len(seg), 90)]
        parts.append(f"{head} {c + 1}\n\n" + "\n\n".join(paras))
    return "\n\n".join(parts)


def generate() -> dict:
    t0 = time.monotonic()
    c = sqlite3.connect(lib_root / "metadata.db")
    c.executescript("""
    CREATE TABLE books(id INTEGER PRIMARY KEY, title TEXT, sort TEXT, timestamp TEXT, pubdate TEXT, series_index REAL DEFAULT 1.0, author_sort TEXT, path TEXT, has_cover INTEGER DEFAULT 0, uuid TEXT, last_modified TEXT DEFAULT '2025-01-01 00:00:00+00:00');
    CREATE TABLE authors(id INTEGER PRIMARY KEY, name TEXT, sort TEXT, link TEXT DEFAULT '');
    CREATE TABLE books_authors_link(id INTEGER PRIMARY KEY, book INTEGER, author INTEGER);
    CREATE TABLE tags(id INTEGER PRIMARY KEY, name TEXT);
    CREATE TABLE books_tags_link(id INTEGER PRIMARY KEY, book INTEGER, tag INTEGER);
    CREATE TABLE series(id INTEGER PRIMARY KEY, name TEXT, sort TEXT);
    CREATE TABLE books_series_link(id INTEGER PRIMARY KEY, book INTEGER, series INTEGER);
    CREATE TABLE publishers(id INTEGER PRIMARY KEY, name TEXT, sort TEXT);
    CREATE TABLE books_publishers_link(id INTEGER PRIMARY KEY, book INTEGER, publisher INTEGER);
    CREATE TABLE languages(id INTEGER PRIMARY KEY, lang_code TEXT);
    CREATE TABLE books_languages_link(id INTEGER PRIMARY KEY, book INTEGER, lang_code INTEGER, item_order INTEGER DEFAULT 0);
    CREATE TABLE ratings(id INTEGER PRIMARY KEY, rating INTEGER);
    CREATE TABLE books_ratings_link(id INTEGER PRIMARY KEY, book INTEGER, rating INTEGER);
    CREATE TABLE data(id INTEGER PRIMARY KEY, book INTEGER, format TEXT, uncompressed_size INTEGER, name TEXT);
    CREATE TABLE comments(id INTEGER PRIMARY KEY, book INTEGER, text TEXT);
    CREATE TABLE identifiers(id INTEGER PRIMARY KEY, book INTEGER, type TEXT, val TEXT);
    CREATE TABLE annotations(id INTEGER PRIMARY KEY, book INTEGER, format TEXT, user_type TEXT, user TEXT, timestamp REAL, annot_id TEXT, annot_type TEXT, annot_data TEXT, searchable_text TEXT);
    CREATE TABLE custom_columns (id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT NOT NULL, name TEXT NOT NULL, datatype TEXT NOT NULL, mark_for_delete BOOL DEFAULT 0 NOT NULL, editable BOOL DEFAULT 1 NOT NULL, display TEXT DEFAULT '{}' NOT NULL, is_multiple BOOL DEFAULT 0 NOT NULL, normalized BOOL NOT NULL, UNIQUE(label));
    CREATE TABLE preferences(id INTEGER PRIMARY KEY, key TEXT NOT NULL, val TEXT NOT NULL, UNIQUE(key));
    CREATE TABLE last_read_positions (id INTEGER PRIMARY KEY, book INTEGER NOT NULL, format TEXT NOT NULL COLLATE NOCASE, user TEXT NOT NULL, device TEXT NOT NULL, cfi TEXT NOT NULL, epoch REAL NOT NULL, pos_frac REAL NOT NULL DEFAULT 0, UNIQUE(user, device, book, format));
    """)
    c.executescript("""
    CREATE INDEX books_idx ON books (sort COLLATE NOCASE);
    CREATE INDEX authors_idx ON books (author_sort COLLATE NOCASE);
    CREATE INDEX comments_idx ON comments (book);
    CREATE INDEX data_idx ON data (book);
    CREATE INDEX formats_idx ON data (format);
    CREATE INDEX identifiers_idx ON identifiers (book);
    CREATE INDEX tags_idx ON tags (name COLLATE NOCASE);
    CREATE INDEX languages_idx ON languages (lang_code COLLATE NOCASE);
    CREATE INDEX books_authors_link_aidx ON books_authors_link (author);
    CREATE INDEX books_authors_link_bidx ON books_authors_link (book);
    CREATE INDEX books_tags_link_aidx ON books_tags_link (tag);
    CREATE INDEX books_tags_link_bidx ON books_tags_link (book);
    CREATE INDEX books_languages_link_aidx ON books_languages_link (lang_code);
    CREATE INDEX books_languages_link_bidx ON books_languages_link (book);
    CREATE INDEX books_series_link_bidx ON books_series_link (book);
    CREATE INDEX books_publishers_link_bidx ON books_publishers_link (book);
    CREATE INDEX books_ratings_link_bidx ON books_ratings_link (book);
    CREATE INDEX annot_idx ON annotations (book);
    """)
    f = sqlite3.connect(lib_root / "full-text-search.db")
    f.executescript("""CREATE TABLE books_text(id INTEGER PRIMARY KEY, book INTEGER NOT NULL, timestamp REAL NOT NULL, format TEXT NOT NULL COLLATE NOCASE, format_size INTEGER NOT NULL, format_hash TEXT NOT NULL, err_msg TEXT DEFAULT '', searchable_text TEXT NOT NULL, text_size INTEGER NOT NULL, text_hash TEXT NOT NULL);
    CREATE TABLE dirtied_formats(id INTEGER PRIMARY KEY, book INTEGER NOT NULL, format TEXT NOT NULL COLLATE NOCASE, in_progress INTEGER NOT NULL DEFAULT FALSE);""")
    n_auth = 300
    authors = [(i + 1, f"{VOCAB[int(rng.integers(0, 4000))].capitalize()} {VOCAB[int(rng.integers(0, 4000))].capitalize()}") for i in range(n_auth)]
    c.executemany("INSERT INTO authors VALUES (?,?,?,'')", [(i, n, ", ".join(reversed(n.split()))) for i, n in authors])
    c.executemany("INSERT INTO tags VALUES (?,?)", list(enumerate(TAGS, 1)))
    c.executemany("INSERT INTO languages VALUES (?,?)", [(1, "ita"), (2, "eng")])
    total_chars = 0
    for bid in range(1, args.books + 1):
        lang = "ita" if rng.random() < 1 / 3 else "eng"
        title = " ".join(w.capitalize() for w in VOCAB[rng.integers(0, 6000, size=int(rng.integers(2, 6)))])
        a = int(rng.integers(1, n_auth + 1))
        year = int(rng.integers(1995, 2026))
        c.execute("INSERT INTO books(id,title,sort,timestamp,pubdate,author_sort,path,uuid) VALUES (?,?,?,?,?,?,?,?)",
                  (bid, title, title, f"{year}-03-01 10:00:00+00:00", f"{year}-01-01 00:00:00+00:00",
                   authors[a - 1][1], f"A/B ({bid})", f"u{bid}"))
        c.execute("INSERT INTO books_authors_link(book,author) VALUES (?,?)", (bid, a))
        for t in rng.choice(len(TAGS), size=int(rng.integers(1, 4)), replace=False):
            c.execute("INSERT INTO books_tags_link(book,tag) VALUES (?,?)", (bid, int(t) + 1))
        c.execute("INSERT INTO books_languages_link(book,lang_code) VALUES (?,?)", (bid, 1 if lang == "ita" else 2))
        fmt = "EPUB" if rng.random() < 0.7 else "PDF"
        c.execute("INSERT INTO data(book,format,uncompressed_size,name) VALUES (?,?,?,?)", (bid, fmt, 1000, f"b{bid}"))
        c.execute("INSERT INTO comments(book,text) VALUES (?,?)", (bid, f"<p>{title}: a synthetic book.</p>"))
        if rng.random() < 0.8:
            c.execute("INSERT INTO identifiers(book,type,val) VALUES (?,?,?)", (bid, "isbn", f"97888{bid:07d}"))
        needles = [w for w, share in NEEDLES.items() if rng.random() < share]
        kb = max(40, int(rng.normal(args.avg_kb, args.avg_kb * 0.4)))
        text = book_text(kb * 1000 // 7, lang, needles)       # ~7 characters per word including the space
        total_chars += len(text)
        f.execute("INSERT INTO books_text VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (bid, bid, 0, fmt, 1000, "h", "", text, len(text), hashlib.sha1(text.encode()).hexdigest()))
        if bid % 100 == 0:
            c.commit(); f.commit()
            print(f"  generated {bid}/{args.books} books ({total_chars / 1e6:.0f} MB)", file=sys.stderr, flush=True)
    c.commit(); f.commit(); c.close(); f.close()
    return {"books": args.books, "text_mb": round(total_chars / 1e6), "seconds": round(time.monotonic() - t0, 1),
            "library_db_mb": round((lib_root / "full-text-search.db").stat().st_size / 1e6)}


# ---------------------------------------------------------------------------------------------- measurements
def timed(fn, runs: int, warmup: int = 3) -> dict:
    first_t0 = time.perf_counter(); fn(); first = (time.perf_counter() - first_t0) * 1000
    for _ in range(warmup):
        fn()
    xs = []
    for _ in range(runs):
        t0 = time.perf_counter(); fn(); xs.append((time.perf_counter() - t0) * 1000)
    xs.sort()
    return {"first_ms": round(first, 1), "median_ms": round(statistics.median(xs), 2),
            "p95_ms": round(xs[min(len(xs) - 1, int(len(xs) * 0.95))], 2), "runs": runs}


def main() -> None:
    env_info = {
        "os": platform.platform(), "python": sys.version.split()[0], "sqlite": sqlite3.sqlite_version,
        "cpu_count": os.cpu_count(),
        "ram_mb": next((int(l.split()[1]) // 1024 for l in open("/proc/meminfo") if l.startswith("MemTotal")), None) if os.path.exists("/proc/meminfo") else None, "cpu": next((l.split(":", 1)[1].strip() for l in open("/proc/cpuinfo") if l.startswith("model name")), platform.processor()) if os.path.exists("/proc/cpuinfo") else platform.processor(),
    }
    print("Generating the synthetic library...", file=sys.stderr)
    gen = generate()
    print(f"Library ready: {gen}", file=sys.stderr)

    child_env = dict(os.environ, CALIBRE_LIBRARY=str(lib_root), CALIBRE_MCP_DATA=str(data_dir), PYTHONUTF8="1")
    r = subprocess.run([sys.executable, str(ROOT / "calibre_mcp.py"), "--sync"], env=child_env, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("--sync failed:\n" + r.stderr[-1500:])
    sync = json.loads(r.stdout[r.stdout.index("{"):])
    idx = sorted(data_dir.glob("*/index.db"))[0]
    results: dict = {"environment": env_info, "dataset": gen, "initial_index": {**sync, "index_mb": round(idx.stat().st_size / 1e6)}}

    os.environ.update(CALIBRE_LIBRARY=str(lib_root), CALIBRE_MCP_DATA=str(data_dir))
    sys.argv = ["x"]
    sys.path.insert(0, str(ROOT))
    import calibre_mcp as m
    m.set_libraries([m.detect_library()], m.default_data_dir())
    n = args.runs
    AUTHOR_SAMPLE = sqlite3.connect(lib_root / "metadata.db").execute("SELECT name FROM authors WHERE id=17").fetchone()[0].split()[-1]
    _f = sqlite3.connect(lib_root / "full-text-search.db")
    mid7 = _f.execute("SELECT text_size FROM books_text WHERE book=7").fetchone()[0] // 2     # middle of book 7
    _f.close()

    ops = {
        "metadata search (q=tag word)": lambda: m.calibre_search_books(q="security", limit=20),
        "metadata search (tag filter)": lambda: m.calibre_search_books(tag="security", limit=20),
        "metadata search (author filter)": lambda: m.calibre_search_books(author=AUTHOR_SAMPLE, limit=20),
        "metadata search (Calibre syntax)": lambda: m.calibre_search_books(query="tag:security and pubdate:>2010 and languages:eng", limit=20),
        "full-text, rare word, 10 books x 3 snippets": lambda: m.calibre_search_fulltext(query="firewall", limit=10, snippets_per_book=3),
        "full-text, common word, 10 books x 3 snippets": lambda: m.calibre_search_fulltext(query="segmentation", limit=10, snippets_per_book=3),
        "full-text, phrase, 10 books x 3 snippets": lambda: m.calibre_search_fulltext(query="lateral movement", mode="phrase", limit=10, snippets_per_book=3),
        "full-text, rare word, 50 books, no snippets": lambda: m.calibre_search_fulltext(query="firewall", limit=50, snippets_per_book=0),
        "full-text, common word, 50 books, no snippets": lambda: m.calibre_search_fulltext(query="segmentation", limit=50, snippets_per_book=0),
        "read_text (6,000 chars, middle of a book)": lambda: m.calibre_read_text(book_id=7, offset=mid7, max_chars=6000),
        "find_in_book (10 hits)": lambda: m.calibre_find_in_book(book_id=7, query="firewall", max_results=10),
        "chapter map of one book": lambda: m.calibre_get_chapters(book_id=7),
        "quality report (whole library)": lambda: m.calibre_quality_report(limit=100),
        "find_duplicates (whole library)": lambda: m.calibre_find_duplicates(),
    }
    results["operations"] = {}
    for name, fn in ops.items():
        try:
            results["operations"][name] = timed(fn, n if "report" not in name and "duplicates" not in name else max(5, n // 6))
        except Exception as exc:                                  # a failing tool must not hide the other numbers
            results["operations"][name] = {"error": f"{type(exc).__name__}: {exc}"}

    # incremental sync: change one book's text, delete another, sync again
    fts = sqlite3.connect(lib_root / "full-text-search.db")
    new = "Aggiornamento sintetico del testo. " * 50
    fts.execute("UPDATE books_text SET searchable_text=?, text_size=?, text_hash=? WHERE id=5", (new, len(new), "changed"))
    fts.execute("DELETE FROM books_text WHERE id=9"); fts.commit(); fts.close()
    t0 = time.perf_counter(); inc = m.LIB.index.sync(); wall = time.perf_counter() - t0
    results["incremental_sync"] = {**inc, "wall_ms": round(wall * 1000, 1), "note": "1 changed text, 1 removed; includes the per-document throttle"}

    if args.semantic_books:
        os.environ["CALIBRE_MCP_EMBED_BACKEND"] = "hash"
        try:
            t0 = time.perf_counter(); m.build_embeddings(max_books=args.semantic_books); build_s = time.perf_counter() - t0
            emb = sorted(data_dir.glob("*/embeddings.db"))
            con = sqlite3.connect(emb[0]); passages = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] if emb else 0; con.close()
            sem = timed(lambda: m.calibre_search_semantic(query="how firewall segmentation limits lateral movement", limit=8), max(5, n // 3))
            results["semantic_hash_backend"] = {"books": args.semantic_books, "passages": passages, "build_seconds": round(build_s, 1),
                                                "embeddings_mb": round(emb[0].stat().st_size / 1e6) if emb else None, "hybrid_search": sem,
                                                "note": "hash backend: ranking path only, not model inference speed"}
        except Exception as exc:
            results["semantic_hash_backend"] = {"error": f"{type(exc).__name__}: {exc}"}

    # ------------------------------------------------------------------ report
    print("\n### Environment\n")
    print(f"- {env_info['cpu']} ({env_info['cpu_count']} core(s)), {env_info['os']}, Python {env_info['python']}, SQLite {env_info['sqlite']}")
    print(f"- synthetic library: {gen['books']} books, {gen['text_mb']} MB of text (generated in {gen['seconds']} s)\n")
    print("### Results\n")
    print("| Operation | Median | p95 | First call |\n|---|---|---|---|")
    print(f"| Initial index build (`--sync`, one-off) | {results['initial_index']['seconds']} s | | {results['initial_index']['index_mb']} MB index |")
    inc = results["incremental_sync"]
    print(f"| Incremental sync (1 change, 1 removal) | {inc.get('seconds', '?')} s | | |")
    for name, v in results["operations"].items():
        if "error" in v:
            print(f"| {name} | error: {v['error']} | | |")
        else:
            print(f"| {name} | {v['median_ms']} ms | {v['p95_ms']} ms | {v['first_ms']} ms |")
    if "semantic_hash_backend" in results and "error" not in results["semantic_hash_backend"]:
        s = results["semantic_hash_backend"]
        print(f"| Semantic hybrid search over {s['passages']:,} passages (hash backend) | {s['hybrid_search']['median_ms']} ms | {s['hybrid_search']['p95_ms']} ms | {s['hybrid_search']['first_ms']} ms |")
        print(f"| Semantic index build, {s['books']} books (hash backend) | {s['build_seconds']} s | | {s['embeddings_mb']} MB |")
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2), encoding="utf-8")


try:
    main()
finally:
    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)

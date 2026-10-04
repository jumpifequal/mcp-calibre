"""Opt-in semantic search over book text (local embeddings, no network at query time).

Built ONLY by an explicit batch command (`calibre_mcp.py --build-embeddings`), never in the
background: computing embeddings for a whole library is CPU-heavy.

Backends (CALIBRE_MCP_EMBED_BACKEND)
  fastembed  default. ONNX, CPU. Model CALIBRE_MCP_EMBED_MODEL (default multilingual MiniLM,
             384 dims, IT+EN). The model is downloaded once from Hugging Face on first build.
  hash       dependency-light lexical fallback (feature hashing). Not semantic: for tests and
             air-gapped machines.
Index (schema 2), <sidecar>/embeddings.db
  passages  ~CHUNK chars, split inside chapters (chapter map), each embedded WITH its context
            ("title - author > chapter: text") so the vector knows where it comes from
  coverage  the whole book, up to MAX_CHUNKS passages (evenly sampled beyond that)
  vectors   int8 (384 bytes per passage at 384 dims), scored in blocks: bounded memory
  keywords  an FTS5 index over the same passages, for hybrid search
Search (hybrid by default): vector ranking + keyword (BM25) ranking fused with reciprocal rank
fusion; front/back-matter passages (contents, praise, copyright, index...) are demoted, and a
similarity floor flags weak matches instead of presenting them as relevant.
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

# The default model was trained on 128 word pieces: ~700 chars (+ context prefix) keeps passages
# inside its effective window instead of diluting them.
CHUNK = int(os.environ.get("CALIBRE_MCP_EMBED_CHUNK", "700"))
OVERLAP = 120
MAX_CHUNKS = int(os.environ.get("CALIBRE_MCP_EMBED_MAX_CHUNKS", "1500"))
SCHEMA = "2"
RRF_K = 60
FRONT_DEMOTION = 0.5
SIM_FLOOR = float(os.environ.get("CALIBRE_MCP_SEMANTIC_FLOOR", "0.30"))
_BLOCK = 65_536
DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MODEL_DIR: Optional[Path] = None   # set by calibre_mcp at startup (sidecar dir), not the OS temp folder
_REQ = Path(__file__).resolve().parent.parent / "requirements-semantic.txt"


def _install_hint() -> str:
    import sys
    return (f'install them into the server\'s environment:  "{sys.executable}" -m pip install -r "{_REQ}"  '
            "then restart the MCP client and build the index:  calibre_mcp.py --build-embeddings")


def _np():
    try:
        import numpy as np  # type: ignore
        return np
    except ImportError as exc:
        raise ValueError("Semantic search dependencies are missing (numpy, fastembed): " + _install_hint()) from exc


class HashEmbedder:
    name, dim = "hash", 512

    def __init__(self, fold: Callable[[str], str]):
        self.fold = fold

    def embed(self, texts: list[str]):
        np = _np()
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            words = re.findall(r"\w{3,}", self.fold(t).casefold())
            for w in words + [a + " " + b for a, b in zip(words, words[1:])]:
                h = int.from_bytes(hashlib.blake2b(w.encode(), digest_size=8).digest(), "little")
                out[i, h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
        n = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.where(n == 0, 1, n)


class FastEmbedder:
    def __init__(self, model: str):
        try:
            from fastembed import TextEmbedding  # type: ignore
        except ImportError as exc:
            raise ValueError("Semantic search backend 'fastembed' is not installed: " + _install_hint() +
                             "  (or set CALIBRE_MCP_EMBED_BACKEND=hash for a lexical fallback)") from exc
        cache = os.environ.get("FASTEMBED_CACHE_PATH") or (str(MODEL_DIR) if MODEL_DIR else None)
        # half the cores by default: building the index must not saturate the machine
        threads = int(os.environ.get("CALIBRE_MCP_EMBED_THREADS", "0")) or max(1, (os.cpu_count() or 2) // 2)
        try:
            self.model = TextEmbedding(model_name=model, cache_dir=cache, threads=threads)
        except Exception as exc:  # noqa: BLE001 - download/ONNX errors come in many types
            raise ValueError(
                f"Could not load embedding model {model!r}: {exc}. The first use downloads it once "
                f"(~220 MB for the default) from Hugging Face into {cache or 'the fastembed cache'}; "
                "check network/proxy (HTTPS_PROXY), or pre-seed that folder, or set "
                "CALIBRE_MCP_EMBED_BACKEND=hash for an offline lexical fallback.") from exc
        self.name = f"fastembed:{model}"
        self.dim = len(next(iter(self.model.embed(["probe"]))))

    def embed(self, texts: list[str]):
        np = _np()
        v = np.asarray(list(self.model.embed(texts)), dtype=np.float32)
        n = np.linalg.norm(v, axis=1, keepdims=True)
        return v / np.where(n == 0, 1, n)


_EMBEDDER: dict[str, Any] = {}
_EMB_LOCK = threading.Lock()


def get_embedder(fold: Callable[[str], str]):
    backend = os.environ.get("CALIBRE_MCP_EMBED_BACKEND", "fastembed").lower()
    model = os.environ.get("CALIBRE_MCP_EMBED_MODEL", DEFAULT_MODEL)
    key = f"{backend}:{model}"
    with _EMB_LOCK:
        if key not in _EMBEDDER:
            _EMBEDDER[key] = HashEmbedder(fold) if backend == "hash" else FastEmbedder(model)
        return _EMBEDDER[key]


def prefetch_model(fold: Callable[[str], str]) -> dict[str, Any]:
    """Download (once) and load the embedding model locally, then run one probe embedding.
    Used by setup so the first semantic build/query does not have to download anything."""
    t0 = time.monotonic()
    emb = get_embedder(fold)
    emb.embed(["probe"])
    info: dict[str, Any] = {"backend": emb.name, "dim": emb.dim, "seconds": round(time.monotonic() - t0, 1)}
    cache = os.environ.get("FASTEMBED_CACHE_PATH") or (str(MODEL_DIR) if MODEL_DIR else None)
    if cache and Path(cache).is_dir() and emb.name != "hash":
        size = sum(f.stat().st_size for f in Path(cache).rglob("*") if f.is_file())
        info.update(cache_dir=cache, size_mb=round(size / 2 ** 20, 1))
    return info


def chunk_text(text: str, chapters: Optional[list[dict]] = None) -> list[dict]:
    """Passages that never cross a chapter boundary. Each: {off, text, heading, kind}."""
    spans = chapters or [{"offset": 0, "end": len(text), "title": None, "kind": "body"}]
    out: list[dict] = []
    for ch in spans:
        pos, end = ch["offset"], ch["end"]
        while pos < end:
            stop = min(end, pos + CHUNK)
            if stop < end:
                sp = text.rfind(" ", pos + CHUNK // 2, stop)
                stop = sp if sp > 0 else stop
            piece = text[pos:stop].strip()
            if len(piece) > 60:
                out.append({"off": pos, "text": piece, "heading": ch.get("title"), "kind": ch.get("kind", "body")})
            if stop >= end:
                break
            pos = max(stop - OVERLAP, pos + 1)
    if len(out) > MAX_CHUNKS:  # even sampling keeps coverage of the whole book
        step = len(out) / MAX_CHUNKS
        out = [out[int(i * step)] for i in range(MAX_CHUNKS)]
    return out


def context_prefix(title: str, authors: str, heading: Optional[str]) -> str:
    head = f"{title} - {authors}".strip(" -")[:120]
    return f"{head} > {heading[:80]}: " if heading else f"{head}: "


_WORD = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
_STOP = set("""the and for with that this from are was were have has had not but you your they their them what
which when where who how why can could would should will into about over under than then also only such
these those there here its our out all any per via una uno gli lei lui che chi con per tra fra del della
delle dei degli dal dalla nel nella nei sul sulla come anche più non sono era essere hanno questo questa
quello quella quali quale cosa dove quando perché però tutti tutto ogni""".split())


def keyword_match(queries: list[str], fold: Callable[[str], str]) -> Optional[str]:
    """Natural-language question(s) -> OR of quoted content words (lexical half of hybrid search)."""
    words, seen = [], set()
    for q in queries:
        for w in _WORD.findall(fold(q).casefold()):
            if w not in _STOP and w not in seen:
                seen.add(w)
                words.append(w)
    return " OR ".join(f'"{w}"' for w in words[:24]) or None


class SemanticIndex:
    def __init__(self, side_dir: Path):
        self.path = side_dir / "embeddings.db"
        self._cache: Optional[tuple[float, Any, Any]] = None
        self._lock = threading.Lock()

    def exists(self) -> bool:
        return self.path.is_file()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=30)
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript("""
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, val TEXT);
            CREATE TABLE IF NOT EXISTS books (book INTEGER PRIMARY KEY, fmt TEXT, src_hash TEXT, n INTEGER);
            CREATE TABLE IF NOT EXISTS failures (book INTEGER PRIMARY KEY, fmt TEXT, error TEXT, at TEXT);""")
        return c

    def _schema_ok(self, c: sqlite3.Connection) -> bool:
        return dict(c.execute("SELECT key, val FROM meta")).get("schema") == SCHEMA

    @staticmethod
    def _create_v2(c: sqlite3.Connection) -> None:
        contentless = tuple(map(int, sqlite3.sqlite_version.split("."))) >= (3, 43, 0)
        opts = ", content='', contentless_delete=1" if contentless else ""
        c.executescript(f"""
            DROP TABLE IF EXISTS chunks; DROP TABLE IF EXISTS chunks_fts; DELETE FROM books; DELETE FROM meta;
            CREATE TABLE IF NOT EXISTS failures (book INTEGER PRIMARY KEY, fmt TEXT, error TEXT, at TEXT);
            DELETE FROM failures;
            CREATE TABLE chunks (id INTEGER PRIMARY KEY, book INTEGER, fmt TEXT, off INTEGER, len INTEGER,
                                 heading TEXT, kind TEXT, vec BLOB);
            CREATE INDEX chunks_book ON chunks(book);
            CREATE VIRTUAL TABLE chunks_fts USING fts5(body, tokenize='unicode61 remove_diacritics 2'{opts});""")

    def info(self) -> dict[str, Any]:
        if not self.exists():
            return {"built": False}
        with sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True) as c:
            meta = dict(c.execute("SELECT key, val FROM meta"))
            books, chunks = c.execute("SELECT COUNT(*), COALESCE(SUM(n),0) FROM books").fetchone()
        out = {"built": True, "schema": meta.get("schema", "1"), "backend": meta.get("backend"), "dim": meta.get("dim"),
               "books": books, "chunks": chunks, "size_mb": round(self.path.stat().st_size / 2 ** 20, 1)}
        if meta.get("schema") != SCHEMA:
            out["needs_rebuild"] = "index from an older version: run  calibre_mcp.py --build-embeddings"
        return out

    def build(self, sources: Iterable[tuple[int, str, str]],
              prepare: Callable[[int, str], tuple[str, str, str, list[dict]]],
              fold: Callable[[str], str], max_books: int = 0, rebuild: bool = False,
              progress: Callable[[str], None] = print, only_books: Optional[set[int]] = None,
              force: bool = False) -> dict[str, Any]:
        """sources: (book, fmt, src_hash). prepare(book, fmt) -> (text, title, authors, chapters).
        Incremental: unchanged books are skipped; an index from an older schema is rebuilt.
        only_books restricts the work to those books (the rest of the index is left untouched);
        force re-embeds them even if unchanged. A failing book never stops the build: its error is
        recorded in the 'failures' table (see report()) and cleared when it later succeeds."""
        np = _np()
        sources = list(sources)
        emb = get_embedder(fold)
        t0, done, failed = time.monotonic(), 0, 0
        with self._conn() as c:
            meta = dict(c.execute("SELECT key, val FROM meta"))
            reason = ("requested" if rebuild else
                      "index format upgraded" if meta.get("schema") != SCHEMA else
                      f"embedding backend changed ({meta.get('backend')} -> {emb.name})"
                      if meta.get("backend") not in (None, emb.name) or meta.get("dim") not in (None, str(emb.dim)) else None)
            if reason:
                if meta:
                    progress(f"rebuilding the semantic index: {reason}")
                self._create_v2(c)
            c.executemany("INSERT OR REPLACE INTO meta VALUES (?,?)",
                          [("schema", SCHEMA), ("backend", emb.name), ("dim", str(emb.dim)), ("chunk", str(CHUNK))])
            have = dict(c.execute("SELECT book, src_hash FROM books"))
            todo = [s for s in sources if have.get(s[0]) != s[2] or (force and only_books and s[0] in only_books)]
            if only_books is not None:
                todo = [s for s in todo if s[0] in only_books]
            unchanged = len(sources) - len(todo) if only_books is None else len(only_books) - len(todo)
            live = {s[0] for s in sources}
            gone = [b for b in have if b not in live] if only_books is None else []
            for b in gone:
                self._drop_book(c, b)
            c.commit()
            if max_books:
                todo = todo[:max_books]
            for i, (book, fmt, h) in enumerate(todo, 1):
                try:
                    text, title, authors, chapters = prepare(book, fmt)
                    chunks = chunk_text(text, chapters)
                    inputs = [context_prefix(title, authors, ch["heading"]) + ch["text"] for ch in chunks]
                    vecs = np.zeros((0, emb.dim), np.float32)
                    if inputs:
                        vecs = np.concatenate([emb.embed(inputs[j:j + 64]) for j in range(0, len(inputs), 64)])
                except Exception as exc:  # noqa: BLE001 - one bad book must not stop the whole build
                    failed += 1
                    msg = f"{type(exc).__name__}: {exc}"[:500]
                    c.execute("INSERT OR REPLACE INTO failures VALUES (?,?,?,?)",
                              (book, fmt, msg, time.strftime("%Y-%m-%d %H:%M:%S")))
                    c.commit()
                    progress(f"[{i}/{len(todo)}] book {book}: FAILED {msg}")
                    continue
                self._drop_book(c, book)
                q = np.clip(np.rint(vecs * 127), -127, 127).astype(np.int8)
                for ch, v in zip(chunks, q):
                    cur = c.execute("INSERT INTO chunks(book, fmt, off, len, heading, kind, vec) VALUES (?,?,?,?,?,?,?)",
                                    (book, fmt, ch["off"], len(ch["text"]), ch["heading"], ch["kind"], v.tobytes()))
                    c.execute("INSERT INTO chunks_fts(rowid, body) VALUES (?,?)", (cur.lastrowid, ch["text"]))
                c.execute("INSERT OR REPLACE INTO books VALUES (?,?,?,?)", (book, fmt, h, len(chunks)))
                c.execute("DELETE FROM failures WHERE book=?", (book,))
                c.commit()
                done += 1
                progress(f"[{i}/{len(todo)}] book {book}: {len(chunks)} passages")
        self._cache = None
        return {"embedded": done, "failed": failed, "unchanged": unchanged, "removed": len(gone),
                "backend": emb.name, "seconds": round(time.monotonic() - t0, 1)}

    def failed_books(self) -> list[int]:
        if not self.exists():
            return []
        with self._ro() as c:
            if not c.execute("SELECT 1 FROM sqlite_master WHERE name='failures'").fetchone():
                return []
            return [r[0] for r in c.execute("SELECT book FROM failures ORDER BY book")]

    def report(self, sources: dict[int, dict[str, Any]], library_ids: set[int],
               integrity: bool = True) -> dict[str, Any]:
        """Sanity check of the index against the current sources (read-only).
        sources: {book: {fmt, hash, chars}} = books that HAVE text; library_ids = every book id."""
        if not self.exists():
            return {"built": False, "hint": "run  calibre_mcp.py --build-embeddings"}
        with self._ro() as c:
            meta = dict(c.execute("SELECT key, val FROM meta"))
            books = {r[0]: {"fmt": r[1], "hash": r[2], "n": r[3]} for r in c.execute("SELECT book, fmt, src_hash, n FROM books")}
            fails = {}
            if c.execute("SELECT 1 FROM sqlite_master WHERE name='failures'").fetchone():
                fails = {r[0]: {"fmt": r[1], "error": r[2], "at": r[3]} for r in c.execute("SELECT * FROM failures")}
            integ: dict[str, Any] = {}
            if integrity and self._schema_ok(c):
                per_book = dict(c.execute("SELECT book, COUNT(*) FROM chunks GROUP BY book"))
                dim = int(meta.get("dim", 0) or 0)
                integ = {
                    "sqlite_quick_check": c.execute("PRAGMA quick_check").fetchone()[0],
                    "count_mismatch": sorted(b for b, v in books.items() if per_book.get(b, 0) != v["n"]),
                    "orphan_passages": sorted(b for b in per_book if b not in books),
                    "bad_vectors": c.execute("SELECT COUNT(*) FROM chunks WHERE length(vec) != ?", (dim,)).fetchone()[0],
                    "passages": sum(per_book.values()),
                }
                integ["ok"] = (integ["sqlite_quick_check"] == "ok" and not integ["count_mismatch"]
                               and not integ["orphan_passages"] and integ["bad_vectors"] == 0)
        cats: dict[str, list[dict[str, Any]]] = {k: [] for k in
            ("failed", "missing", "stale", "empty", "sparse", "capped", "no_text", "orphan")}
        for b, f in sorted(fails.items()):
            cats["failed"].append({"book_id": b, "format": f["fmt"], "error": f["error"], "at": f["at"]})
        for b, src in sorted(sources.items()):
            if b in fails:
                continue
            got = books.get(b)
            if got is None:
                cats["missing"].append({"book_id": b, "format": src["fmt"], "chars": src["chars"]})
            elif got["hash"] != src["hash"]:
                cats["stale"].append({"book_id": b, "format": src["fmt"]})
            elif got["n"] == 0:
                cats["empty"].append({"book_id": b, "format": got["fmt"], "chars": src["chars"]})
            else:
                expected = max(1, src["chars"] // (CHUNK - OVERLAP))
                if got["n"] >= MAX_CHUNKS:
                    cats["capped"].append({"book_id": b, "passages": got["n"], "chars": src["chars"]})
                elif src["chars"] > 20_000 and got["n"] < expected * 0.5:
                    cats["sparse"].append({"book_id": b, "passages": got["n"], "expected_about": expected,
                                           "chars": src["chars"]})
        for b in sorted(library_ids - set(sources)):
            cats["no_text"].append({"book_id": b})
        for b in sorted(set(books) - library_ids):
            cats["orphan"].append({"book_id": b})
        return {"built": True, "schema": meta.get("schema"), "backend": meta.get("backend"),
                "indexed_books": len(books), "summary": {k: len(v) for k, v in cats.items()},
                "categories": cats, "integrity": integ}

    @staticmethod
    def _drop_book(c: sqlite3.Connection, book: int) -> None:
        ids = [r[0] for r in c.execute("SELECT id FROM chunks WHERE book=?", (book,))]
        for cid in ids:
            c.execute("DELETE FROM chunks_fts WHERE rowid=?", (cid,))
        c.execute("DELETE FROM chunks WHERE book=?", (book,))
        c.execute("DELETE FROM books WHERE book=?", (book,))
        c.execute("DELETE FROM failures WHERE book=?", (book,))

    def _ro(self) -> sqlite3.Connection:
        return sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)

    def _matrix(self):
        """(int8 matrix, rows) cached until the file changes. rows[i] = (id, book, fmt, off, len, heading, kind)."""
        np = _np()
        mtime = self.path.stat().st_mtime
        wal = self.path.with_name(self.path.name + "-wal")
        if wal.exists():
            mtime = max(mtime, wal.stat().st_mtime)
        with self._lock:
            if self._cache and self._cache[0] == mtime:
                return self._cache[1], self._cache[2]
            with self._ro() as c:
                if not self._schema_ok(c):
                    raise ValueError("The semantic index was built by an older version: rebuild it with  "
                                     "calibre_mcp.py --build-embeddings")
                dim = int(dict(c.execute("SELECT key, val FROM meta")).get("dim", 0))
                rows = c.execute("SELECT id, book, fmt, off, len, heading, kind, vec FROM chunks ORDER BY id").fetchall()
            if not rows:
                raise ValueError("Embedding index is empty: run  python calibre_mcp.py --build-embeddings")
            mat = np.frombuffer(b"".join(r[7] for r in rows), dtype=np.int8).reshape(len(rows), dim)
            meta = [r[:7] for r in rows]
            self._cache = (mtime, mat, meta)
            return mat, meta

    def _vector_scores(self, qv, allowed_mask=None):
        """Cosine similarity of every passage, computed in blocks (bounded temporary memory)."""
        np = _np()
        mat, _ = self._matrix()
        out = np.empty(mat.shape[0], dtype=np.float32)
        for a in range(0, mat.shape[0], _BLOCK):
            out[a:a + _BLOCK] = (mat[a:a + _BLOCK].astype(np.float32) @ qv) / 127.0
        if allowed_mask is not None:
            out[~allowed_mask] = -np.inf
        return out

    def search(self, query: str, fold: Callable[[str], str], k: int, allowed: Optional[set[int]] = None,
               mode: str = "hybrid", alt_queries: Optional[list[str]] = None,
               book: Optional[int] = None) -> list[dict]:
        """Ranked passages: {book, fmt, off, len, heading, kind, score, vector, keyword_rank, low_confidence}."""
        np = _np()
        if not self.exists():
            raise ValueError("Semantic index not built. Run:  python calibre_mcp.py --build-embeddings "
                             "[--max-books N]   (opt-in, CPU heavy)")
        mat, meta = self._matrix()
        if book is not None:
            allowed = {book} if allowed is None else (allowed & {book})
        mask = None
        if allowed is not None:
            mask = np.fromiter((m[1] in allowed for m in meta), dtype=bool, count=len(meta))
        queries = [query, *[q for q in (alt_queries or []) if q and q.strip() and q != query]]
        pool = max(k * 4, 200)
        vec_best = np.full(len(meta), -np.inf, dtype=np.float32)
        vec_rank: dict[int, int] = {}
        if mode in ("hybrid", "vector"):
            with self._ro() as c:
                backend = dict(c.execute("SELECT key, val FROM meta")).get("backend")
            emb = get_embedder(fold)
            if emb.name != backend:
                raise ValueError(f"Index built with {backend}, current backend is {emb.name}: rebuild with "
                                 "--build-embeddings --rebuild")
            for qv in emb.embed(queries):
                vec_best = np.maximum(vec_best, self._vector_scores(qv.astype(np.float32), mask))
            n = min(pool, int(np.isfinite(vec_best).sum()))
            if n:
                top = np.argpartition(-vec_best, n - 1)[:n]
                top = top[np.argsort(-vec_best[top])]
                vec_rank = {int(i): r for r, i in enumerate(top)}
        kw_rank: dict[int, int] = {}
        if mode in ("hybrid", "keyword"):
            match = keyword_match(queries, fold)
            if match:
                id_to_row = {m[0]: i for i, m in enumerate(meta)}
                sql = ("SELECT f.rowid FROM chunks_fts f JOIN chunks ch ON ch.id=f.rowid WHERE chunks_fts MATCH ?")
                args: list[Any] = [match]
                if allowed is not None:
                    import json
                    sql += " AND ch.book IN (SELECT value FROM json_each(?))"
                    args.append(json.dumps(sorted(allowed)))
                sql += " ORDER BY bm25(chunks_fts) LIMIT ?"
                args.append(pool)
                with self._ro() as c:
                    for r, (rid,) in enumerate(c.execute(sql, args)):
                        if rid in id_to_row:
                            kw_rank[id_to_row[rid]] = r
        fused: dict[int, float] = {}
        for i, r in vec_rank.items():
            fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + r + 1)
        for i, r in kw_rank.items():
            fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + r + 1)
        out = []
        for i, sc in fused.items():
            m = meta[i]
            if m[6] in ("front", "back"):
                sc *= FRONT_DEMOTION        # contents, praise, index...: keyword-dense, rarely the answer
            v = float(vec_best[i]) if np.isfinite(vec_best[i]) else None
            out.append({"book": m[1], "fmt": m[2], "off": m[3], "len": m[4], "heading": m[5], "kind": m[6],
                        "score": sc, "vector": v, "keyword_rank": kw_rank.get(i),
                        "low_confidence": (v is None or v < SIM_FLOOR) and i not in kw_rank if mode != "keyword" else False})
        out.sort(key=lambda h: -h["score"])
        return out[:k]

    def book_centroids(self, book_id: int):
        np = _np()
        mat, meta = self._matrix()
        rows = [i for i, m in enumerate(meta) if m[1] == book_id and m[6] == "body"] or \
               [i for i, m in enumerate(meta) if m[1] == book_id]
        if not rows:
            raise ValueError(f"Book {book_id} is not in the embedding index (run --build-embeddings)")
        centroid = mat[rows].astype(np.float32).mean(axis=0)
        centroid /= (np.linalg.norm(centroid) or 1)
        scores = self._vector_scores(centroid)  # cosine (int8 rows rescaled inside), comparable across books
        best: dict[int, float] = {}
        for i, sc in enumerate(scores):
            b = meta[i][1]
            if b != book_id and sc > best.get(b, -1e9):
                best[b] = float(sc)
        return best

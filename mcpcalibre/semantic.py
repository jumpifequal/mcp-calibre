"""Opt-in semantic search over book text (local embeddings, no network at query time).

Built ONLY by an explicit batch command (`calibre_mcp.py --build-embeddings`), never in the
background: computing embeddings for a whole library is CPU-heavy.

Backends (CALIBRE_MCP_EMBED_BACKEND)
  fastembed  default. ONNX, CPU. Model CALIBRE_MCP_EMBED_MODEL (default multilingual MiniLM,
             384 dims, IT+EN). The model is downloaded once from Hugging Face on first build.
  hash       dependency-light lexical fallback (feature hashing). Not semantic: for tests and
             air-gapped machines.
Storage: <sidecar>/embeddings.db, float16 vectors, chunks of ~CHUNK chars, at most MAX_CHUNKS per
book (evenly sampled), so memory at query time is bounded (~0.8 KB per chunk at 384 dims).
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

CHUNK = int(os.environ.get("CALIBRE_MCP_EMBED_CHUNK", "1200"))
OVERLAP = 200
MAX_CHUNKS = int(os.environ.get("CALIBRE_MCP_EMBED_MAX_CHUNKS", "300"))
DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def _np():
    try:
        import numpy as np  # type: ignore
        return np
    except ImportError as exc:
        raise ValueError("Semantic search needs numpy: pip install numpy fastembed") from exc


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
            raise ValueError("Semantic search backend 'fastembed' not installed: pip install fastembed "
                             "(or set CALIBRE_MCP_EMBED_BACKEND=hash for a lexical fallback)") from exc
        self.model = TextEmbedding(model_name=model)
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


def chunk_text(text: str) -> list[tuple[int, str]]:
    out, pos, n = [], 0, len(text)
    while pos < n:
        end = min(n, pos + CHUNK)
        if end < n:
            sp = text.rfind(" ", pos + CHUNK // 2, end)
            end = sp if sp > 0 else end
        piece = text[pos:end].strip()
        if len(piece) > 80:
            out.append((pos, piece))
        if end >= n:
            break
        pos = max(end - OVERLAP, pos + 1)
    if len(out) > MAX_CHUNKS:  # even sampling keeps coverage of the whole book
        step = len(out) / MAX_CHUNKS
        out = [out[int(i * step)] for i in range(MAX_CHUNKS)]
    return out


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
            CREATE TABLE IF NOT EXISTS chunks (id INTEGER PRIMARY KEY, book INTEGER, fmt TEXT,
                                               off INTEGER, vec BLOB);
            CREATE INDEX IF NOT EXISTS chunks_book ON chunks(book);""")
        return c

    def info(self) -> dict[str, Any]:
        if not self.exists():
            return {"built": False}
        with sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True) as c:
            meta = dict(c.execute("SELECT key, val FROM meta"))
            books, chunks = c.execute("SELECT COUNT(*), COALESCE(SUM(n),0) FROM books").fetchone()
        return {"built": True, "backend": meta.get("backend"), "dim": meta.get("dim"), "books": books,
                "chunks": chunks, "size_mb": round(self.path.stat().st_size / 2 ** 20, 1)}

    def build(self, sources: Iterable[tuple[int, str, str]], get_text: Callable[[int, str], str],
              fold: Callable[[str], str], max_books: int = 0, rebuild: bool = False,
              progress: Callable[[str], None] = print) -> dict[str, Any]:
        """sources: (book, fmt, src_hash). Incremental: unchanged books are skipped."""
        np = _np()
        sources = list(sources)
        emb = get_embedder(fold)
        t0, done, failed = time.monotonic(), 0, 0
        with self._conn() as c:
            meta = dict(c.execute("SELECT key, val FROM meta"))
            if rebuild or (meta and (meta.get("backend") != emb.name or meta.get("dim") != str(emb.dim))):
                if meta and not rebuild:
                    progress(f"embedding backend changed ({meta.get('backend')} -> {emb.name}): rebuilding")
                c.executescript("DELETE FROM chunks; DELETE FROM books; DELETE FROM meta;")
            c.executemany("INSERT OR REPLACE INTO meta VALUES (?,?)",
                          [("backend", emb.name), ("dim", str(emb.dim))])
            have = dict(c.execute("SELECT book, src_hash FROM books"))
            todo = [s for s in sources if have.get(s[0]) != s[2]]
            unchanged = len(sources) - len(todo)
            live = {s[0] for s in sources}
            gone = [b for b in have if b not in live]
            for b in gone:
                c.execute("DELETE FROM chunks WHERE book=?", (b,))
                c.execute("DELETE FROM books WHERE book=?", (b,))
            c.commit()
            if max_books:
                todo = todo[:max_books]
            for i, (book, fmt, h) in enumerate(todo, 1):
                try:
                    chunks = chunk_text(get_text(book, fmt))
                    vecs = emb.embed([t for _, t in chunks]) if chunks else np.zeros((0, emb.dim), np.float32)
                except (ValueError, OSError) as exc:
                    failed += 1
                    progress(f"[{i}/{len(todo)}] book {book}: FAILED {exc}")
                    continue
                c.execute("DELETE FROM chunks WHERE book=?", (book,))
                c.executemany("INSERT INTO chunks(book, fmt, off, vec) VALUES (?,?,?,?)",
                              [(book, fmt, off, v.astype(np.float16).tobytes()) for (off, _), v in zip(chunks, vecs)])
                c.execute("INSERT OR REPLACE INTO books VALUES (?,?,?,?)", (book, fmt, h, len(chunks)))
                c.commit()
                done += 1
                progress(f"[{i}/{len(todo)}] book {book}: {len(chunks)} chunks")
        self._cache = None
        return {"embedded": done, "failed": failed, "unchanged": unchanged, "removed": len(gone),
                "backend": emb.name, "seconds": round(time.monotonic() - t0, 1)}

    def _matrix(self):
        np = _np()
        mtime = self.path.stat().st_mtime
        wal = self.path.with_name(self.path.name + "-wal")
        if wal.exists():
            mtime = max(mtime, wal.stat().st_mtime)
        with self._lock:
            if self._cache and self._cache[0] == mtime:
                return self._cache[1], self._cache[2]
            with sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True) as c:
                rows = c.execute("SELECT book, fmt, off, vec FROM chunks ORDER BY id").fetchall()
                dim = int(dict(c.execute("SELECT key, val FROM meta")).get("dim", 0))
            if not rows:
                raise ValueError("Embedding index is empty: run  python calibre_mcp.py --build-embeddings")
            mat = np.frombuffer(b"".join(r[3] for r in rows), dtype=np.float16).reshape(len(rows), dim)
            ids = [(r[0], r[1], r[2]) for r in rows]
            self._cache = (mtime, mat, ids)
            return mat, ids

    def search(self, query: str, fold: Callable[[str], str], k: int,
               allowed: Optional[set[int]] = None) -> list[tuple[int, str, int, float]]:
        np = _np()
        if not self.exists():
            raise ValueError("Semantic index not built. Run:  python calibre_mcp.py --build-embeddings "
                             "[--max-books N]   (opt-in, CPU heavy)")
        mat, ids = self._matrix()
        with sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True) as c:
            backend = dict(c.execute("SELECT key, val FROM meta")).get("backend")
        emb = get_embedder(fold)
        if emb.name != backend:
            raise ValueError(f"Index built with {backend}, current backend is {emb.name}: rebuild with "
                             "--build-embeddings --rebuild")
        q = emb.embed([query])[0].astype(np.float32)
        scores = mat.astype(np.float32) @ q
        if allowed is not None:
            mask = np.fromiter((i[0] in allowed for i in ids), dtype=bool, count=len(ids))
            scores = np.where(mask, scores, -np.inf)
        k = min(k, len(ids))
        top = np.argpartition(-scores, k - 1)[:k]
        top = top[np.argsort(-scores[top])]
        return [(ids[i][0], ids[i][1], ids[i][2], float(scores[i])) for i in top if np.isfinite(scores[i])]

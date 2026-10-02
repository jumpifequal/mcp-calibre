"""Library-wide figure search by caption / alt text.

Built explicitly (calibre_mcp.py --index-figures), incrementally (unchanged files are skipped), into
<sidecar>/figures.db. Keyword search (FTS5) always works; if the semantic backend is available at
build time, captions are also embedded and search becomes hybrid (reciprocal rank fusion).
Covers EPUB and PDF; other formats would need a conversion per book, so they are left out.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

RRF_K = 60


class FigureIndex:
    def __init__(self, side_dir: Path):
        self.path = side_dir / "figures.db"

    def exists(self) -> bool:
        return self.path.is_file()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=30)
        c.execute("PRAGMA journal_mode=WAL")
        contentless = tuple(map(int, sqlite3.sqlite_version.split("."))) >= (3, 43, 0)
        opts = ", content='', contentless_delete=1" if contentless else ""
        c.executescript(f"""
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, val TEXT);
            CREATE TABLE IF NOT EXISTS books (book INTEGER PRIMARY KEY, fmt TEXT, stamp TEXT, n INTEGER);
            CREATE TABLE IF NOT EXISTS figs (id INTEGER PRIMARY KEY, book INTEGER, fmt TEXT, fig_id TEXT,
                                             caption TEXT, alt TEXT, place TEXT, vec BLOB);
            CREATE INDEX IF NOT EXISTS figs_book ON figs(book);""")
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='figs_fts'").fetchone():
            c.execute(f"CREATE VIRTUAL TABLE figs_fts USING fts5(body, tokenize='unicode61 remove_diacritics 2'{opts})")
        return c

    def info(self) -> dict[str, Any]:
        if not self.exists():
            return {"built": False}
        with sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True) as c:
            books, figs = c.execute("SELECT COUNT(*), COALESCE(SUM(n),0) FROM books").fetchone()
            vec = c.execute("SELECT COUNT(*) FROM figs WHERE vec IS NOT NULL").fetchone()[0]
            meta = dict(c.execute("SELECT key, val FROM meta"))
        return {"built": True, "books": books, "figures": figs, "with_vectors": vec, "backend": meta.get("backend")}

    def build(self, sources: Iterable[tuple[int, str, str]], list_figs: Callable[[int, str], list[dict]],
              embed: Optional[Callable[[list[str]], Any]] = None, backend: Optional[str] = None,
              max_books: int = 0, progress: Callable[[str], None] = print) -> dict[str, Any]:
        """sources: (book, fmt, stamp) where stamp changes when the file changes.
        list_figs(book, fmt) -> [{fig_id, caption, alt, place}] (only captioned/alt-texted figures)."""
        t0, done, failed = time.monotonic(), 0, 0
        sources = list(sources)
        with self._conn() as c:
            meta = dict(c.execute("SELECT key, val FROM meta"))
            if (backend or "") != meta.get("backend", ""):   # vectors from another model are not comparable
                c.executescript("DELETE FROM books;")
            c.execute("INSERT OR REPLACE INTO meta VALUES ('backend', ?)", (backend or "",))
            have = dict(c.execute("SELECT book, stamp FROM books"))
            todo = [s for s in sources if have.get(s[0]) != s[2]]
            live = {s[0] for s in sources}
            for b in [b for b in have if b not in live]:
                self._drop(c, b)
            if max_books:
                todo = todo[:max_books]
            for i, (book, fmt, stamp) in enumerate(todo, 1):
                try:
                    figs = [f for f in list_figs(book, fmt) if (f.get("caption") or f.get("alt"))]
                except (ValueError, OSError) as exc:
                    failed += 1
                    progress(f"[{i}/{len(todo)}] book {book}: FAILED {exc}")
                    continue
                self._drop(c, book)
                texts = [" ".join(x for x in (f.get("caption"), f.get("alt"), f.get("place")) if x) for f in figs]
                vecs = None
                if embed and texts:
                    import numpy as np
                    v = embed(texts)
                    vecs = np.clip(np.rint(v * 127), -127, 127).astype(np.int8)
                for j, (f, t) in enumerate(zip(figs, texts)):
                    cur = c.execute("INSERT INTO figs(book, fmt, fig_id, caption, alt, place, vec) VALUES (?,?,?,?,?,?,?)",
                                    (book, fmt, f["fig_id"], f.get("caption"), f.get("alt"), f.get("place"),
                                     vecs[j].tobytes() if vecs is not None else None))
                    c.execute("INSERT INTO figs_fts(rowid, body) VALUES (?,?)", (cur.lastrowid, t))
                c.execute("INSERT OR REPLACE INTO books VALUES (?,?,?,?)", (book, fmt, stamp, len(figs)))
                c.commit()
                done += 1
                progress(f"[{i}/{len(todo)}] book {book}: {len(figs)} captioned figures")
        return {"indexed_books": done, "failed": failed, "unchanged": len(sources) - len(todo),
                "vectors": bool(embed), "seconds": round(time.monotonic() - t0, 1)}

    @staticmethod
    def _drop(c: sqlite3.Connection, book: int) -> None:
        for (rid,) in c.execute("SELECT id FROM figs WHERE book=?", (book,)).fetchall():
            c.execute("DELETE FROM figs_fts WHERE rowid=?", (rid,))
        c.execute("DELETE FROM figs WHERE book=?", (book,))
        c.execute("DELETE FROM books WHERE book=?", (book,))

    def search(self, match: Optional[str], qvecs: Optional[list] = None, allowed: Optional[set[int]] = None,
               k: int = 20) -> list[dict]:
        if not self.exists():
            raise ValueError("Figure index not built. Run:  python calibre_mcp.py --index-figures")
        with sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True) as c:
            rows = {r[0]: r for r in c.execute("SELECT id, book, fmt, fig_id, caption, alt, place, vec FROM figs")}
            kw: dict[int, int] = {}
            if match:
                sql = "SELECT f.rowid FROM figs_fts f JOIN figs g ON g.id=f.rowid WHERE figs_fts MATCH ?"
                args: list[Any] = [match]
                if allowed is not None:
                    sql += " AND g.book IN (SELECT value FROM json_each(?))"
                    args.append(json.dumps(sorted(allowed)))
                sql += " ORDER BY bm25(figs_fts) LIMIT 200"
                kw = {rid: r for r, (rid,) in enumerate(c.execute(sql, args))}
        vec: dict[int, int] = {}
        sims: dict[int, float] = {}
        if qvecs is not None:
            import numpy as np
            ids = [i for i, r in rows.items() if r[7] is not None and (allowed is None or r[1] in allowed)]
            if ids:
                mat = np.frombuffer(b"".join(rows[i][7] for i in ids), dtype=np.int8).reshape(len(ids), -1)
                best = np.full(len(ids), -np.inf, dtype=np.float32)
                for q in qvecs:
                    best = np.maximum(best, (mat.astype(np.float32) @ q.astype(np.float32)) / 127.0)
                order = np.argsort(-best)[:200]
                vec = {ids[int(j)]: r for r, j in enumerate(order)}
                sims = {ids[int(j)]: float(best[int(j)]) for j in order}
        fused: dict[int, float] = {}
        for d in (kw, vec):
            for rid, r in d.items():
                fused[rid] = fused.get(rid, 0.0) + 1.0 / (RRF_K + r + 1)
        out = []
        for rid, sc in sorted(fused.items(), key=lambda x: -x[1])[:k]:
            r = rows[rid]
            out.append({"book_id": r[1], "format": r[2], "figure_id": r[3], "caption": r[4], "alt": r[5],
                        "place": r[6], "score": round(sc, 4), "keyword_match": rid in kw,
                        "similarity": round(sims[rid], 3) if rid in sims else None})
        return out

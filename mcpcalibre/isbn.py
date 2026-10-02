"""ISBN validation and discovery in book text (read-only: results are suggestions)."""
from __future__ import annotations

import re
from typing import Optional

_DIGITS = re.compile(r"[^0-9Xx]")
# 13-digit (978/979) or 10-character, with optional hyphens/spaces between groups
_CAND = re.compile(r"(?<![0-9Xx])(?:97[89][\s\-‐‑–]?(?:[0-9][\s\-‐‑–]?){9}[0-9]|(?:[0-9][\s\-‐‑–]?){9}[0-9Xx])(?![0-9Xx])")
_LABEL = re.compile(r"ISBN(?:[\s\-]*1[03])?(?:\s*\((?:[^)]{0,30})\))?\s*[:#]?\s*$", re.IGNORECASE)


def normalise(raw: str) -> str:
    return _DIGITS.sub("", raw or "").upper()


def valid10(s: str) -> bool:
    if not re.fullmatch(r"[0-9]{9}[0-9X]", s):
        return False
    total = sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(s))
    return total % 11 == 0


def valid13(s: str) -> bool:
    if not re.fullmatch(r"97[89][0-9]{10}", s):
        return False
    total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(s))
    return total % 10 == 0


def to13(s: str) -> Optional[str]:
    s = normalise(s)
    if valid13(s):
        return s
    if valid10(s):
        core = "978" + s[:9]
        check = (10 - sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(core)) % 10) % 10
        return core + str(check)
    return None


def check(raw: str) -> dict:
    """Validation verdict for a stored identifier."""
    s = normalise(raw)
    if len(s) == 13:
        return {"valid": valid13(s), "isbn13": s if valid13(s) else None, "problem": None if valid13(s) else "bad checksum or prefix"}
    if len(s) == 10:
        return {"valid": valid10(s), "isbn13": to13(s), "problem": None if valid10(s) else "bad checksum"}
    return {"valid": False, "isbn13": None, "problem": f"wrong length ({len(s)} digits)"}


def scan(text: str, head: int = 60_000, tail: int = 40_000) -> list[dict]:
    """ISBNs found in the text. Copyright pages sit near the start (sometimes the end), so the
    head and tail are scanned; ISBNs inside the body (bibliographies, citations) are reported
    separately and ranked lower. Only checksum-valid ISBNs are returned."""
    n = len(text)
    regions = [(0, min(n, head))]
    if n > head:
        regions.append((max(head, n - tail), n))
    found: dict[str, dict] = {}
    for a, b in regions:
        for m in _CAND.finditer(text, a, b):
            i13 = to13(m.group(0))
            if not i13:
                continue
            before = text[max(0, m.start() - 40):m.start()]
            labeled = bool(_LABEL.search(before))
            ctx = " ".join(text[max(0, m.start() - 80):m.end() + 60].split())
            where = "front" if m.start() < n * 0.1 or m.start() < head // 2 else ("back" if m.start() > n * 0.9 else "body")
            hit = found.get(i13)
            if hit is None:
                found[i13] = hit = {"isbn13": i13, "as_printed": m.group(0).strip(), "offset": m.start(),
                                    "labeled": labeled, "where": where, "occurrences": 0, "context": ctx}
            hit["occurrences"] += 1
            if labeled and not hit["labeled"]:
                hit.update(labeled=True, offset=m.start(), context=ctx, where=where)
    # the book's own ISBN: labeled, near the front, then most frequent
    rank = {"front": 0, "back": 1, "body": 2}
    return sorted(found.values(), key=lambda h: (not h["labeled"], rank[h["where"]], -h["occurrences"], h["offset"]))

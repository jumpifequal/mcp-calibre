"""Legal gate: mechanical checks that a text derived from books (notes, a distilled skill, a summary)
does not reproduce them. Read-only. A PASS is evidence of transformation, not legal advice.

Checks (thresholds are parameters; defaults are conservative)
  verbatim_overlap   share of the text's 8-word shingles (outside declared quotes) found in the sources
  longest_run        longest stretch copied word for word outside quotes
  quote_budget       each quote short, and few quotes in total
  compression        the text is much shorter than its sources
  heading_mirroring  headings do not replicate the sources' chapter titles or their order
  attribution        every source book is credited (title, an author surname, or its ISBN)
"""
from __future__ import annotations

import re
from typing import Callable, Optional

N = 8
_QUOTE_RX = re.compile(r"“[^”]{1,2000}”|\"[^\"\n]{1,2000}\"|«[^»]{1,2000}»|^>.*$", re.MULTILINE)
_HEAD_RX = re.compile(r"^#{1,6}\s+(.+?)\s*#*$", re.MULTILINE)
_CODE_RX = re.compile(r"```.*?```", re.DOTALL)

DEFAULTS = {"max_overlap": 0.03, "max_run_words": 20, "max_quote_words": 25, "max_quotes": 20,
            "max_ratio": 0.15, "max_heading_mirror": 0.5, "max_ordered_headings": 5}


def _tokens(text: str, fold: Callable[[str], str]) -> list[str]:
    return re.findall(r"[^\W_]+", fold(text).casefold())


def _shingles(tokens: list[str]) -> set[str]:
    return {" ".join(tokens[i:i + N]) for i in range(len(tokens) - N + 1)}


def _norm_title(t: str, fold: Callable[[str], str]) -> str:
    return " ".join(_tokens(re.sub(r"^\s*(chapter|capitolo|part|parte)?\s*[0-9ivxlc]+[.:)]?\s+", "", t, flags=re.I), fold))


def check(text: str, sources: list[dict], fold: Callable[[str], str], **limits) -> dict:
    """sources: [{book_id, title, authors: [..], isbn: str|None, text: str, chapters: [titles]}]"""
    lim = {**DEFAULTS, **{k: v for k, v in limits.items() if v is not None}}
    body = _CODE_RX.sub(" ", text)
    quotes = [m.group(0) for m in _QUOTE_RX.finditer(body)]
    unquoted = _QUOTE_RX.sub(" ", body)
    toks = _tokens(unquoted, fold)
    src_tokens = [_tokens(s["text"], fold) for s in sources]
    src_shingles: set[str] = set()
    for st in src_tokens:
        src_shingles |= _shingles(st)
    mine = [" ".join(toks[i:i + N]) for i in range(len(toks) - N + 1)]
    hits = [sh in src_shingles for sh in mine]
    overlap = (sum(hits) / len(mine)) if mine else 0.0
    best_run, run, best_at = 0, 0, None
    for i, h in enumerate(hits):
        run = run + 1 if h else 0
        if run > best_run:
            best_run, best_at = run, i - run + 1
    run_words = best_run + N - 1 if best_run else 0
    longest = " ".join(toks[best_at:best_at + run_words]) if best_at is not None else ""
    q_words = [len(_tokens(q, fold)) for q in quotes]
    total_text = len(_tokens(body, fold))
    total_src = sum(len(t) for t in src_tokens) or 1
    ratio = total_text / total_src
    heads = [h for h in (_norm_title(m.group(1), fold) for m in _HEAD_RX.finditer(text)) if h]
    chap = []
    for s in sources:
        chap += [c for c in (_norm_title(t, fold) for t in s.get("chapters") or []) if c and len(c) > 3]
    chapset = set(chap)
    mirrored = [h for h in heads if h in chapset]
    ordered = 0
    if mirrored:
        pos = [chap.index(h) for h in heads if h in chapset]
        cur = 1
        for a, b in zip(pos, pos[1:]):
            cur = cur + 1 if b == a + 1 else 1
            ordered = max(ordered, cur)
        ordered = max(ordered, 1)
    folded_text = " ".join(_tokens(text, fold))
    missing = []
    for s in sources:
        title_ok = bool(s.get("title")) and " ".join(_tokens(s["title"], fold)[:4]) in folded_text
        surname_ok = any(_tokens(a, fold) and _tokens(a, fold)[-1] in folded_text.split() for a in s.get("authors") or [])
        isbn_ok = bool(s.get("isbn")) and re.sub(r"\D", "", s["isbn"]) in re.sub(r"\D", "", text)
        if not (title_ok or surname_ok or isbn_ok):
            missing.append(s.get("title") or f"book {s.get('book_id')}")
    checks = {
        "verbatim_overlap": {"pass": overlap <= lim["max_overlap"], "value": round(overlap, 4),
                             "limit": lim["max_overlap"], "detail": f"{sum(hits)} of {len(mine)} 8-word sequences found in the sources"},
        "longest_run": {"pass": run_words <= lim["max_run_words"], "value": run_words, "limit": lim["max_run_words"],
                        "detail": (longest[:240] + ("…" if len(longest) > 240 else "")) if run_words else "no copied run"},
        "quote_budget": {"pass": len(quotes) <= lim["max_quotes"] and all(w <= lim["max_quote_words"] for w in q_words),
                         "value": {"quotes": len(quotes), "longest_quote_words": max(q_words, default=0)},
                         "limit": {"max_quotes": lim["max_quotes"], "max_quote_words": lim["max_quote_words"]}},
        "compression": {"pass": ratio <= lim["max_ratio"], "value": round(ratio, 4), "limit": lim["max_ratio"],
                        "detail": f"{total_text} words vs {total_src} in the sources"},
        "heading_mirroring": {"pass": (not heads or len(mirrored) / len(heads) <= lim["max_heading_mirror"])
                              and ordered < lim["max_ordered_headings"],
                              "value": {"mirrored": len(mirrored), "headings": len(heads), "longest_in_order": ordered},
                              "detail": ", ".join(mirrored[:8]) or "none"},
        "attribution": {"pass": not missing, "value": len(sources) - len(missing), "detail":
                        ("missing: " + "; ".join(missing)) if missing else "all sources credited"},
    }
    return {"pass": all(c["pass"] for c in checks.values()), "checks": checks, "words": total_text,
            "sources": [{"book_id": s.get("book_id"), "title": s.get("title")} for s in sources],
            "note": "Mechanical evidence of transformation, not legal advice."}

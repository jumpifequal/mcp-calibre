"""Query-aware snippet selection for full-text results.

The FTS5 index says *which* books match, not *where*. Snippets are therefore recomputed on the
book text: the query is turned into clauses (phrases, prefix terms, NEAR groups; NOT branches are
excluded), every clause is located in the text, and the windows covering the most -- and the most
specific -- clauses are returned, best first. A phrase such as "system prompt" is never reduced to
its single words, so a stray "prompt" in the front matter cannot win over the real match.
"""
from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from typing import Callable, Optional

MAX_HITS_PER_CLAUSE = 3000   # bound work on very long books / very common words
_OPS = {"AND", "OR", "NOT"}


@dataclass
class Clause:
    label: str
    pattern: "re.Pattern[str]"
    weight: float


def _word_rx(word: str, prefix: bool, fold: Callable[[str], str]) -> str:
    w = re.escape(fold(word).casefold())
    return r"(?<!\w)" + w + ("" if prefix else r"(?!\w)")


def _phrase_clause(words: list[str], prefix_last: bool, fold, loose_end: bool) -> Optional[Clause]:
    words = [w for w in words if w]
    if not words:
        return None
    parts = [_word_rx(w, prefix=(loose_end or (prefix_last and i == len(words) - 1)), fold=fold)
             for i, w in enumerate(words)]
    rx = re.compile(r"\W+".join(parts), re.IGNORECASE)
    label = " ".join(words) + ("*" if prefix_last else "")
    # specific clauses weigh more: a 2-word phrase beats any single common word
    return Clause(label if len(words) == 1 else f'"{label}"', rx, 1.0 if len(words) == 1 else 2.0 + len(words))


def _near_clause(groups: list[tuple[list[str], bool]], dist: int, fold, loose_end: bool) -> Optional[Clause]:
    subs = [_phrase_clause(w, p, fold, loose_end) for w, p in groups]
    subs = [s for s in subs if s]
    if len(subs) < 2:
        return subs[0] if subs else None
    if len(subs) > 2:  # proximity of 3+ groups: highlight the pair of the first two (still specific)
        subs = subs[:2]
    a, b = (s.pattern.pattern for s in subs)
    gap = r"(?:\W+\w+){0,%d}\W+" % max(0, dist)
    rx = re.compile(f"(?:{a}){gap}(?:{b})|(?:{b}){gap}(?:{a})", re.IGNORECASE)  # NEAR is order-free
    return Clause(f"NEAR({subs[0].label} {subs[1].label}, {dist})", rx, 4.0 + subs[0].weight + subs[1].weight)


_TOK = re.compile(r'"(?:[^"]|"")*"\*?|NEAR\s*\(|\(|\)|,|[^\s(),"]+', re.IGNORECASE)


def _split_term(tok: str) -> tuple[list[str], bool]:
    prefix = tok.endswith("*")
    body = tok[:-1] if prefix else tok
    if body.startswith('"'):
        body = body[1:-1].replace('""', '"')          # quoted phrase: taken literally
    else:
        body = re.sub(r"^\w+\s*:\s*", "", body)        # column filter (body:word): drop the column
        body = body.lstrip("^")                       # initial-token marker
    return re.findall(r"\w+", body, re.UNICODE), prefix


def clauses_from_raw(query: str, fold: Callable[[str], str], loose_end: bool = False) -> list[Clause]:
    """Positive clauses of an FTS5 MATCH expression (NOT branches and operators dropped)."""
    toks = _TOK.findall(query)
    out: list[Clause] = []
    i, negate_next = 0, False

    def skip_group(j: int) -> int:  # skip a parenthesised group starting at toks[j] == "("
        depth = 0
        while j < len(toks):
            if toks[j] == "(" or re.match(r"NEAR\s*\(", toks[j], re.I):
                depth += 1
            elif toks[j] == ")":
                depth -= 1
                if depth == 0:
                    return j + 1
            j += 1
        return j

    while i < len(toks):
        t = toks[i]
        up = t.upper()
        if up in _OPS:
            negate_next = up == "NOT"
            i += 1
            continue
        if t in ("(", ")", ","):
            if t == "(" and negate_next:
                i = skip_group(i)
                negate_next = False
                continue
            i += 1
            continue
        if re.match(r"NEAR\s*\(", t, re.I):
            j, groups, dist = i + 1, [], 10
            while j < len(toks) and toks[j] != ")":
                if toks[j] == ",":
                    if j + 1 < len(toks) and toks[j + 1].isdigit():
                        dist = int(toks[j + 1])
                        j += 1
                elif toks[j] not in ("(",):
                    groups.append(_split_term(toks[j]))
                j += 1
            if not negate_next:
                c = _near_clause(groups, dist, fold, loose_end)
                if c:
                    out.append(c)
            negate_next = False
            i = j + 1
            continue
        words, prefix = _split_term(t)
        if not negate_next:
            c = _phrase_clause(words, prefix, fold, loose_end)
            if c:
                out.append(c)
        negate_next = False
        i += 1
    # duplicates add nothing
    seen, uniq = set(), []
    for c in out:
        if c.pattern.pattern not in seen:
            seen.add(c.pattern.pattern)
            uniq.append(c)
    return uniq


def clauses_from_terms(terms: list[str], prefixes: list[bool], phrase: bool, fold,
                       loose_end: bool = False) -> list[Clause]:
    if phrase:
        c = _phrase_clause(" ".join(terms).split(), False, fold, loose_end)
        return [c] if c else []
    return [c for c in (_phrase_clause([t], p, fold, loose_end) for t, p in zip(terms, prefixes)) if c]


def best_snippets(text: str, clauses: list[Clause], n: int, width: int,
                  fold: Callable[[str], str]) -> list[dict]:
    """Up to n non-overlapping windows, ranked by the total weight of DISTINCT clauses they contain
    (ties: earlier offset). Each result carries the clauses it matched."""
    if not clauses or n <= 0:
        return []
    ftext = fold(text)
    hits: list[tuple[int, int, int]] = []  # (start, end, clause index)
    for ci, c in enumerate(clauses):
        for k, m in enumerate(c.pattern.finditer(ftext)):
            if k >= MAX_HITS_PER_CLAUSE:
                break
            hits.append((m.start(), m.end(), ci))
    if not hits:
        return []
    hits.sort()
    starts = [h[0] for h in hits]
    half = width // 2
    scored = []
    for s, e, ci in hits:
        lo, hi = max(0, s - half), e + half
        a, b = bisect.bisect_left(starts, lo), bisect.bisect_right(starts, hi)
        present = {hits[j][2] for j in range(a, b) if hits[j][1] <= hi}
        score = sum(clauses[x].weight for x in present)
        scored.append((-score, s, e, present))
    scored.sort()
    chosen: list[tuple[int, int, set, float]] = []
    for neg, s, e, present in scored:
        lo, hi = max(0, s - half), min(len(text), e + half)
        if any(not (hi <= clo or lo >= chi) for clo, chi, _, _ in chosen):
            continue
        chosen.append((lo, hi, present, -neg))
        if len(chosen) >= n:
            break
    out = []
    for lo, hi, present, score in chosen:
        a = text.rfind(" ", 0, lo) + 1 if lo > 0 else 0
        sp = text.find(" ", hi)
        b = sp if sp != -1 and sp - hi < 40 else hi
        frag = " ".join(text[a:b].split())
        first = min(h[0] for h in hits if lo <= h[0] <= hi)
        out.append({"offset": first, "text": ("…" if a else "") + frag + ("…" if b < len(text) else ""),
                    "matched": [clauses[x].label for x in sorted(present, key=lambda x: -clauses[x].weight)]})
    return out

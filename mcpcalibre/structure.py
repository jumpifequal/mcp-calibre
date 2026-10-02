"""Chapter map built from a book's plain text, for every format.

Two methods, best first:
  toc       the book's own table of contents (EPUB nav/NCX, PDF outline) located in the text, in order
  headings  heading detection on the text itself (EN/IT/FR/DE/ES keywords, numbering, roman
            numerals, short all-caps lines) -- covers LIT/MOBI/AZW3 and PDFs without an outline

Offsets refer to the exact text the caller passes in (calibre_read_text uses the same text), so a
chapter's offset can be read directly. Each chapter is classified as body, front or back matter.
"""
from __future__ import annotations

import re
from typing import Callable, Iterable, Optional

_KW = (r"chapter|capitolo|cap\.|chapitre|kapitel|cap[ií]tulo|part|parte|partie|teil|book|libro|"
       r"section|sezione|appendix|appendice|anhang|ap[eé]ndice|prologue|prologo|prólogo|epilogue|"
       r"epilogo|epílogo|introduction|introduzione|einleitung|introducci[oó]n|preface|prefazione|"
       r"pr[eé]face|vorwort|conclusion|conclusions|conclusioni|interlude|intermezzo")
HEADING_RX = re.compile(
    rf"^(?:(?:{_KW})\b[\s.:]*(?:[0-9]+|[IVXLC]+|[a-z]+)?\b.*"            # Chapter 3 / Capitolo II / Prologue
    r"|[0-9]{1,2}(?:\.[0-9]{1,2}){0,2}\.?\s+\S.*"                         # 3  /  3.2  /  3.  Title
    r"|[IVXLC]{1,6}\.?\s+\S.*"                                             # IV. Title
    r"|[IVXLC]{1,6}|[0-9]{1,3})$",                                         # bare numerals on their own line
    re.IGNORECASE)
FRONT_RX = re.compile(r"^(?:table of contents|contents|indice|sommario|copyright|praise|dedication|dedica|"
                      r"title page|frontespizio|also by|other books by|dello stesso autore|about the authors?|"
                      r"l'autore|gli autori|acknowledg|ringraziamenti|cover|copertina|half title|epigraph|"
                      r"colophon|credits|crediti|foreword by|table des mati[eè]res|inhalt)", re.IGNORECASE)
BACK_RX = re.compile(r"^(?:index|indice analitico|indice dei nomi|bibliography|bibliografia|references|"
                     r"riferimenti|notes|note|endnotes|glossary|glossario|about the publisher|colophon)\b",
                     re.IGNORECASE)
_MIN_GAP = 300   # headings closer than this (chars) are usually a TOC listing, not chapters


_EITHER_RX = re.compile(r"^(?:acknowledg|ringraziamenti|about the authors?|l'autore|gli autori|notes?\b|"
                       r"colophon|credits|crediti)", re.IGNORECASE)


def classify(title: str, rel_pos: float = 0.0) -> str:
    """Front/back/body; titles that can sit at either end (acknowledgments, notes, about the
    author) are decided by their position in the book."""
    t = " ".join((title or "").split())
    if _EITHER_RX.match(t):
        return "back" if rel_pos > 0.5 else "front"
    if FRONT_RX.match(t):
        return "front"
    if BACK_RX.match(t):
        return "back"
    return "body"


def _lines(text: str) -> Iterable[tuple[int, str, bool]]:
    """(offset, stripped line, preceded by a blank line or start of text)."""
    pos, blank_before = 0, True
    for raw in text.split("\n"):
        line = raw.strip()
        if line:
            yield pos + (len(raw) - len(raw.lstrip())), line, blank_before
        blank_before = not line
        pos += len(raw) + 1


def _norm(s: str, fold: Callable[[str], str]) -> str:
    return " ".join(re.findall(r"\w+", fold(s).casefold()))


_PREFIX_RX = re.compile(rf"^(?:(?:{_KW})\s+)?(?:[0-9]+(?:\s[0-9]+){{0,2}}|[ivxlc]{{1,6}})\b\s+", re.IGNORECASE)


def _strip_numbering(normed: str) -> str:
    """'chapter 3 agents in practice' / '1 introduction' -> 'agents in practice' / 'introduction'."""
    return _PREFIX_RX.sub("", normed, count=1).strip()


def align_toc(text: str, titles: list[str], fold: Callable[[str], str]) -> list[tuple[int, str]]:
    """Locate TOC titles in order, each at the start of a line (leading numbering ignored on both
    sides). Titles not found are skipped; a contents listing at the start is skipped too."""
    listing = _listing_spans(text)
    starts = []
    for off, line, _ in _lines(text):
        if len(line) <= 200 and not _in_spans(off, listing):
            n = _norm(line, fold)
            starts.append((off, n, _strip_numbering(n)))
    out, i = [], 0
    for t in titles:
        key = _norm(t, fold)
        bare = _strip_numbering(key) or key
        if not key:
            continue
        j = i
        def hit(line_key: str, line_bare: str) -> bool:
            if line_key.startswith(key) or (bare and line_bare.startswith(bare)):
                return True
            # TOC entries are often longer than the in-text heading: 'Capitolo 1 - Firewall' vs 'Capitolo 1'
            return len(line_key) >= 6 and len(line_key.split()) >= 2 and key.startswith(line_key + " ")
        while j < len(starts) and not hit(starts[j][1], starts[j][2]):
            j += 1
        if j < len(starts):
            out.append((starts[j][0], " ".join(t.split())))
            i = j + 1
    return out


def _listing_spans(text: str, max_gap: int = 160, min_lines: int = 3) -> list[tuple[int, int]]:
    """A table of contents printed in the text: >= min_lines heading-like lines in a row, each
    within max_gap chars of the previous one (real chapters are separated by their body text)."""
    offs = [off for off, line, _ in _lines(text) if len(line) <= 90 and HEADING_RX.match(line)]
    spans: list[tuple[int, int]] = []
    run = offs[:1]
    for off in offs[1:] + [None]:
        if off is not None and off - run[-1] <= max_gap:
            run.append(off)
            continue
        if len(run) >= min_lines:
            spans.append((run[0], run[-1] + 1))
        run = [off] if off is not None else []
    return spans


def _in_spans(off: int, spans: list[tuple[int, int]]) -> bool:
    return any(a <= off <= b for a, b in spans)


def detect_headings(text: str) -> list[tuple[int, str]]:
    listing = _listing_spans(text)
    cands = []
    for off, line, blank in _lines(text):
        if not blank or not 1 <= len(line) <= 90 or line[-1] in ".,;" or _in_spans(off, listing):
            continue
        words = line.split()
        upper = (line.isupper() and 2 <= len(words) <= 10 and sum(c.isalpha() for c in line) >= 4)
        matter = len(words) <= 6 and bool(FRONT_RX.match(line) or BACK_RX.match(line))
        if HEADING_RX.match(line) or upper or matter:
            cands.append((off, line, matter or bool(re.match(rf"^(?:{_KW})\b", line, re.IGNORECASE))))
    out: list[tuple[int, str]] = []
    for off, line, strong in cands:
        if out and off - out[-1][0] < _MIN_GAP and not strong:
            continue
        out.append((off, line))
    return out


def chapter_map(text: str, fold: Callable[[str], str], toc_titles: Optional[list[str]] = None) -> dict:
    """{'method': 'toc'|'headings'|'none', 'chapters': [{index,title,offset,end,chars,kind}]}"""
    n = len(text)
    method, marks = "none", []
    if toc_titles:
        aligned = align_toc(text, toc_titles, fold)
        if len(aligned) >= max(2, len([t for t in toc_titles if t.strip()]) // 2):
            method, marks = "toc", aligned
    if not marks:
        found = detect_headings(text)
        if len(found) >= 2:
            method, marks = "headings", found
    chapters: list[dict] = []
    if marks and marks[0][0] > 200:  # text before the first heading: title page, copyright, praise...
        chapters.append({"title": "(front matter)", "offset": 0, "kind": "front"})
    for off, title in marks:
        chapters.append({"title": title[:160], "offset": off, "kind": classify(title, off / max(n, 1))})
    if not chapters:
        chapters = [{"title": None, "offset": 0, "kind": "body"}]
    for i, ch in enumerate(chapters):
        ch["index"] = i
        ch["end"] = chapters[i + 1]["offset"] if i + 1 < len(chapters) else n
        ch["chars"] = ch["end"] - ch["offset"]
    # Chapters before the first body chapter that look like front matter stay front; anything else
    # that the title does not classify is body.
    return {"method": method, "chapters": chapters}


def chapter_at(chapters: list[dict], offset: int) -> Optional[dict]:
    lo, hi = 0, len(chapters) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if chapters[mid]["offset"] <= offset < chapters[mid]["end"]:
            return chapters[mid]
        if offset < chapters[mid]["offset"]:
            hi = mid - 1
        else:
            lo = mid + 1
    return None

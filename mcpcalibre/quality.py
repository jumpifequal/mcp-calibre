"""Metadata quality audit (read-only). Findings are suggestions to fix in Calibre.

Per-book checks
  missing_authors, missing_tags, missing_language, missing_publisher, missing_pubdate,
  missing_cover, missing_isbn, missing_description, no_formats
  raw_filename_title     title looks like a file name or a number (795731065.pdf, BOOK_12)
  title_noise            store/edition suffixes or whitespace problems in the title
  invalid_isbn           stored ISBN with a bad checksum or length
  author_name_anomaly    author name with |, ;, digits, inverted 'Surname, Name', stray punctuation
  author_sort_unsorted   author sort equal to the plain name ('Glenn Cooper' instead of 'Cooper, Glenn')
Library-wide checks
  author_variants        names that differ only by order/punctuation/case ('Cooper| Glenn' vs 'Glenn Cooper')
  tag_variants           tags that differ only by case/punctuation ('Science-Fiction' vs 'science fiction')
  series_gaps            missing or duplicated numbers inside a series
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any, Callable, Optional

from . import isbn as isbnmod

BOOK_CHECKS = ["missing_authors", "missing_tags", "missing_language", "missing_publisher", "missing_pubdate",
               "missing_cover", "missing_isbn", "missing_description", "no_formats", "raw_filename_title",
               "title_noise", "invalid_isbn", "author_name_anomaly", "author_sort_unsorted"]
LIBRARY_CHECKS = ["author_variants", "tag_variants", "series_gaps"]
ALL_CHECKS = BOOK_CHECKS + LIBRARY_CHECKS

_UNKNOWN = {"unknown", "sconosciuto", "inconnu", "unbekannt", "desconocido", "anonymous", "anonimo"}
_RAW_TITLE = re.compile(r"(^[\w\-. ]+\.(pdf|epub|mobi|azw3?|lit|txt|docx?|rtf|fb2|djvu|cbz|cbr)$)|(^\d{5,}$)|"
                        r"(^[A-Za-z0-9]+(_[A-Za-z0-9]+){2,}$)", re.IGNORECASE)
_NOISE = re.compile(r"\((?:italian|english|french|german|spanish|kindle|ebook|epub)?\s*(?:edition|edizione|ebook)\)|"
                    r"\[(?:e-?book|epub|pdf|mobi|retail)\]|\(retail\)|\bcalibre\b", re.IGNORECASE)


def _key(s: str, fold: Callable[[str], str]) -> str:
    return " ".join(sorted(re.findall(r"[^\W_]+", fold(s or "").casefold())))


def _expected_sort(name: str) -> Optional[str]:
    parts = name.split()
    if len(parts) < 2 or "," in name:
        return None
    return parts[-1] + ", " + " ".join(parts[:-1])


def audit(c: sqlite3.Connection, fold: Callable[[str], str], book_ids: Optional[list[int]] = None,
          checks: Optional[list[str]] = None) -> dict[str, Any]:
    want = set(checks or ALL_CHECKS)
    unknown = [x for x in want if x not in ALL_CHECKS]
    if unknown:
        raise ValueError(f"Unknown check(s): {', '.join(unknown)}. Available: {', '.join(ALL_CHECKS)}")
    scope = set(book_ids) if book_ids is not None else None
    books = {r[0]: {"id": r[0], "title": r[1], "pubdate": r[2], "has_cover": r[3], "author_sort": r[4]}
             for r in c.execute("SELECT id, title, pubdate, has_cover, author_sort FROM books")
             if scope is None or r[0] in scope}
    def per_book(sql: str) -> dict[int, list]:
        out: dict[int, list] = {}
        for b, v in c.execute(sql):
            if b in books:
                out.setdefault(b, []).append(v)
        return out
    authors = per_book("SELECT l.book, a.id || char(31) || a.name || char(31) || a.sort FROM books_authors_link l "
                       "JOIN authors a ON a.id=l.author ORDER BY l.id")
    tags = per_book("SELECT l.book, t.name FROM books_tags_link l JOIN tags t ON t.id=l.tag")
    langs = per_book("SELECT book, lang_code FROM books_languages_link")
    pubs = per_book("SELECT book, publisher FROM books_publishers_link")
    isbns = per_book("SELECT book, val FROM identifiers WHERE type='isbn'")
    descs = per_book("SELECT book, text FROM comments WHERE trim(text) != ''")
    fmts = per_book("SELECT book, format FROM data")
    issues: list[dict[str, Any]] = []

    def add(check: str, b: dict, detail: str) -> None:
        if check in want:
            issues.append({"check": check, "book_id": b["id"], "title": b["title"], "detail": detail})

    for bid, b in books.items():
        al = [x.split("\x1f") for x in authors.get(bid, [])]
        names = [a[1] for a in al]
        if not names or all(n.strip().casefold() in _UNKNOWN for n in names):
            add("missing_authors", b, "no author, or 'Unknown'")
        if not tags.get(bid):
            add("missing_tags", b, "no tags")
        if not langs.get(bid):
            add("missing_language", b, "no language")
        if not pubs.get(bid):
            add("missing_publisher", b, "no publisher")
        if not b["pubdate"] or str(b["pubdate"]).startswith("0101"):
            add("missing_pubdate", b, "no publication date")
        if not b["has_cover"]:
            add("missing_cover", b, "no cover")
        if not isbns.get(bid):
            add("missing_isbn", b, "no ISBN identifier")
        if not descs.get(bid):
            add("missing_description", b, "no description")
        if not fmts.get(bid):
            add("no_formats", b, "the record has no book file")
        title = b["title"] or ""
        if _RAW_TITLE.search(title.strip()):
            add("raw_filename_title", b, f"title looks like a file name: {title!r}")
        noise = _NOISE.search(title)
        if noise or title != title.strip() or "  " in title:
            add("title_noise", b, f"{noise.group(0)!r} in title" if noise else "leading/trailing or double spaces")
        for val in isbns.get(bid, []):
            v = isbnmod.check(val)
            if not v["valid"]:
                add("invalid_isbn", b, f"isbn {val!r}: {v['problem']}")
        for _aid, name, sort in al:
            problems = []
            if re.search(r"[|;]", name):
                problems.append("contains | or ;")
            if re.search(r"\d", name):
                problems.append("contains digits")
            if re.search(r"^[\W_]|[\W_]$", name.strip()) and not name.strip().endswith("."):
                problems.append("leading/trailing punctuation")
            if "," in name and not re.search(r",\s*(jr|sr|ii|iii|iv)\.?$", name, re.IGNORECASE):
                problems.append("inverted 'Surname, Name' form in the name field")
            if name.isupper() and len(name) > 3:
                problems.append("all caps")
            if problems:
                add("author_name_anomaly", b, f"{name!r}: {', '.join(problems)}")
            exp = _expected_sort(name)
            if exp and sort and sort.strip() == name.strip():
                add("author_sort_unsorted", b, f"{name!r} sorts as {sort!r}; expected something like {exp!r}")

    library: list[dict[str, Any]] = []
    if "author_variants" in want:
        groups: dict[str, set] = {}
        for vals in authors.values():
            for v in vals:
                _aid, name, _s = v.split("\x1f")
                k = _key(name, fold)
                if k:
                    groups.setdefault(k, set()).add(name)
        for k, names in groups.items():
            if len(names) > 1:
                library.append({"check": "author_variants", "detail": "same author written differently",
                                "values": sorted(names)})
    if "tag_variants" in want:
        groups = {}
        for vals in tags.values():
            for t in vals:
                k = "".join(re.findall(r"[^\W_]+", fold(t).casefold()))
                if k:
                    groups.setdefault(k, set()).add(t)
        for k, names in groups.items():
            if len(names) > 1:
                library.append({"check": "tag_variants", "detail": "same tag written differently", "values": sorted(names)})
    if "series_gaps" in want:
        ser: dict[str, list[tuple[float, int]]] = {}
        for name, idx, bid in c.execute("SELECT s.name, b.series_index, b.id FROM books_series_link l "
                                        "JOIN series s ON s.id=l.series JOIN books b ON b.id=l.book"):
            if bid in books:
                ser.setdefault(name, []).append((idx or 0, bid))
        for name, items in ser.items():
            nums = [i for i, _ in items]
            whole = sorted({int(i) for i in nums if float(i).is_integer() and i >= 1})
            dups = sorted({i for i in nums if nums.count(i) > 1})
            gaps = [n for n in range(whole[0], whole[-1]) if n not in whole] if len(whole) > 1 else []
            if gaps or dups:
                library.append({"check": "series_gaps", "series": name,
                                "detail": "; ".join(x for x in (f"missing numbers {gaps[:20]}" if gaps else "",
                                                                f"duplicated numbers {dups[:20]}" if dups else "") if x),
                                "book_ids": sorted(b for _, b in items)})
    summary: dict[str, int] = {}
    for it in issues + library:
        summary[it["check"]] = summary.get(it["check"], 0) + 1
    return {"books_checked": len(books), "summary": dict(sorted(summary.items(), key=lambda kv: -kv[1])),
            "book_issues": issues, "library_issues": library}

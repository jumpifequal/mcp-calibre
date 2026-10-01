"""Minimal, dependency-free HTML -> Markdown for EPUB chapters.

Keeps the structure that matters for technical books: headings, paragraphs, ordered/unordered
lists (nested), tables (GFM pipe tables), <pre> code blocks, inline code, blockquotes, emphasis,
links (text only, hrefs inside ebooks are internal) and image alt text as placeholders.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

_BLOCK = {"p", "div", "section", "article", "header", "footer", "aside", "figure", "figcaption",
          "dl", "dt", "dd", "body", "nav"}
_SKIP = {"script", "style", "head", "svg", "math", "title"}


class _MD(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0
        self.pre = 0
        self.lists: list[list] = []     # stack of [kind, counter]
        self.quote = 0
        self.table: list[list[str]] | None = None
        self.row: list[str] | None = None
        self.cell: list[str] | None = None

    # ---- output helpers
    def _w(self, s: str) -> None:
        if self.cell is not None:
            self.cell.append(s)
        else:
            self.out.append(s)

    def _nl(self, n: int = 2) -> None:
        if self.cell is not None:
            self.cell.append(" ")
            return
        prefix = "> " * self.quote
        self.out.append("\n" * n + prefix)

    # ---- parser callbacks
    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        a = dict(attrs)
        if re.fullmatch(r"h[1-6]", tag):
            self._nl()
            self._w("#" * int(tag[1]) + " ")
        elif tag in _BLOCK:
            self._nl()
        elif tag == "br":
            self._w("  \n" if self.cell is None else " ")
        elif tag == "hr":
            self._nl()
            self._w("---")
            self._nl()
        elif tag == "pre":
            self.pre += 1
            self._nl()
            self._w("```\n")
        elif tag == "code" and not self.pre:
            self._w("`")
        elif tag in ("strong", "b"):
            self._w("**")
        elif tag in ("em", "i"):
            self._w("*")
        elif tag == "blockquote":
            self.quote += 1
            self._nl()
        elif tag in ("ul", "ol"):
            self.lists.append([tag, 0])
            if len(self.lists) == 1:
                self._nl()
        elif tag == "li":
            depth = max(0, len(self.lists) - 1)
            kind = self.lists[-1] if self.lists else ["ul", 0]
            kind[1] += 1
            self._nl(1)
            self._w("  " * depth + (f"{kind[1]}. " if kind[0] == "ol" else "- "))
        elif tag == "table":
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
        elif tag == "img":
            alt = (a.get("alt") or "").strip()
            self._w(f"[image: {alt}]" if alt else "[image]")

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if re.fullmatch(r"h[1-6]", tag) or tag in _BLOCK:
            self._nl()
        elif tag == "pre":
            self.pre = max(0, self.pre - 1)
            self._w("\n```")
            self._nl()
        elif tag == "code" and not self.pre:
            self._w("`")
        elif tag in ("strong", "b"):
            self._w("**")
        elif tag in ("em", "i"):
            self._w("*")
        elif tag == "blockquote":
            self.quote = max(0, self.quote - 1)
            self._nl()
        elif tag in ("ul", "ol"):
            if self.lists:
                self.lists.pop()
            if not self.lists:
                self._nl()
        elif tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(" ".join("".join(self.cell).split()).replace("|", "\\|"))
            self.cell = None
        elif tag == "tr" and self.row is not None and self.table is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            rows, self.table = self.table, None
            if rows:
                width = max(len(r) for r in rows)
                rows = [r + [""] * (width - len(r)) for r in rows]
                lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
                lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
                self._nl()
                self._w("\n".join(lines))
                self._nl()

    def handle_data(self, data):
        if self.skip:
            return
        if self.pre:
            self._w(data)
        else:
            self._w(re.sub(r"\s+", " ", data))

    def markdown(self) -> str:
        t = "".join(self.out)
        t = re.sub(r"[ \t]+\n", "\n", t)
        t = re.sub(r"\n{3,}", "\n\n", t)
        t = re.sub(r"\*\*\s*\*\*|(?<!\*)\*\s*\*(?!\*)", "", t)   # empty emphasis
        return t.strip()


def html_to_markdown(raw: bytes) -> str:
    p = _MD()
    p.feed(raw.decode("utf-8", errors="replace"))
    p.close()
    return p.markdown()

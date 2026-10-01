"""
Calibre search language -> parametrised SQL (subset, read-only).

Supported
  bare words / "quoted phrase"      title, authors, tags, series, publisher, comments
  field:value                       contains, case- and accent-insensitive (Calibre default)
  field:=value                      exact
  field:~regex                      regular expression (length-capped, see REGEX_MAX)
  field:true / field:false          has / has no value
  rating:>=4, #pages:>300           numeric comparisons  = != > < >= <=   (ratings in stars)
  pubdate:>2020, date:<2024-03      date prefix comparisons; today, yesterday, thismonth,
                                    thisyear, Ndaysago
  size:>10M                         largest format size (K/M/G suffixes)
  identifiers:isbn:978..., identifiers:isbn:true, identifiers:978...
  formats:pdf, languages:ita, cover:true, id:12, uuid:..., series_index:>=2
  #label:...                        custom columns (text, enumeration, series, comments, int,
                                    float, rating, bool, datetime; composite is not stored).
                                    Lookup name as in Calibre; heading also accepted (#mustread for
                                    'Must Read'). Yes/no columns follow Calibre's tristate rules.
  vl:"Name", search:"Name"          virtual libraries / saved searches (expanded recursively)
  and, or, not, ( )                 implicit AND between terms; precedence not > and > or

Every user value is bound as an SQL parameter; table/column names come only from the fixed
field map or from custom_columns metadata (integer ids), never from user text.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

REGEX_MAX = 200          # cap on user regex length (Python re has no timeout: limits ReDoS blast radius)
REGEX_SUBJECT_MAX = 4000  # regex is evaluated on at most this many chars of each value
MAX_DEPTH = 10            # vl:/search: expansion depth
# a group containing a quantifier, itself quantified: (a+)+  (a*)*  (a|aa)+{2,}  -> catastrophic backtracking
_NESTED_QUANT = re.compile(r"\((?:[^()\\]|\\.)*[+*}](?:[^()\\]|\\.)*\)\s*(?:[+*]|\{\d)")


class QueryError(ValueError):
    pass


# --------------------------------------------------------------------------- tokenizer / parser
@dataclass
class Term:
    field: Optional[str]
    value: str
    quoted: bool = False


@dataclass
class Op:
    op: str            # 'and' | 'or' | 'not'
    args: list


_TOKEN_RX = re.compile(r'\s*(?:(\()|(\))|((?:#?[A-Za-z_][\w]*):)?(?:"((?:[^"\\]|\\.)*)"|([^\s()"]+))?)')


def tokenize(s: str) -> list:
    toks, pos = [], 0
    s = s.strip()
    while pos < len(s):
        m = _TOKEN_RX.match(s, pos)
        if not m or m.end() == pos:
            raise QueryError(f"Cannot parse query near: {s[pos:pos + 30]!r}")
        pos = m.end()
        lp, rp, field, qval, val = m.groups()
        if lp:
            toks.append("(")
        elif rp:
            toks.append(")")
        elif field is not None or qval is not None or val is not None:
            fld = field[:-1].lower() if field else None
            if qval is not None:
                toks.append(Term(fld, re.sub(r'\\(["\\])', r'\1', qval), True))  # only \" and \\ (as Calibre)
            elif val is not None:
                if fld is None and val.lower() in ("and", "or", "not"):
                    toks.append(val.lower())
                else:
                    toks.append(Term(fld, val))
            elif fld is not None:
                raise QueryError(f"Missing value after '{fld}:'")
    return toks


class _Parser:
    def __init__(self, toks: list):
        self.t, self.i = toks, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def parse(self):
        if not self.t:
            raise QueryError("Empty query")
        node = self.or_()
        if self.peek() is not None:
            raise QueryError(f"Unexpected token: {self.peek()!r}")
        return node

    def or_(self):
        args = [self.and_()]
        while self.peek() == "or":
            self.take()
            args.append(self.and_())
        return args[0] if len(args) == 1 else Op("or", args)

    def and_(self):
        args = [self.unary()]
        while self.peek() not in (None, ")", "or"):
            if self.peek() == "and":
                self.take()
            args.append(self.unary())
        return args[0] if len(args) == 1 else Op("and", args)

    def unary(self):
        tok = self.take()
        if tok == "not":
            return Op("not", [self.unary()])
        if tok == "(":
            node = self.or_()
            if self.take() != ")":
                raise QueryError("Missing ')'")
            return node
        if isinstance(tok, Term):
            return tok
        raise QueryError(f"Unexpected token: {tok!r}")


def parse(s: str):
    return _Parser(tokenize(s)).parse()


# --------------------------------------------------------------------------- value helpers
_NUM_RX = re.compile(r'^(>=|<=|!=|=|>|<)?\s*(-?\d+(?:\.\d+)?)\s*([kKmMgG]?)$')
_CMP = {">=": ">=", "<=": "<=", "!=": "!=", "=": "=", ">": ">", "<": "<", None: "="}


def _num(value: str, scale: float = 1.0, units: bool = False) -> tuple[str, float]:
    m = _NUM_RX.match(value.strip())
    if not m or (m.group(3) and not units):
        raise QueryError(f"Expected a number with optional operator (e.g. '>=3'), got {value!r}")
    mult = {"": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}[m.group(3).lower()]
    return _CMP[m.group(1)], float(m.group(2)) * scale * mult


_DATE_RX = re.compile(r'^(>=|<=|!=|=|>|<)?\s*(.+)$')


def _date_prefix(v: str, today: _dt.date) -> str:
    v = v.strip().lower()
    if v == "today":
        return today.isoformat()
    if v == "yesterday":
        return (today - _dt.timedelta(days=1)).isoformat()
    if v == "thismonth":
        return today.isoformat()[:7]
    if v == "thisyear":
        return today.isoformat()[:4]
    m = re.match(r'^(\d+)daysago$', v)
    if m:
        return (today - _dt.timedelta(days=int(m.group(1)))).isoformat()
    m = re.match(r'^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?$', v)
    if not m:
        raise QueryError(f"Bad date {v!r}: use YYYY, YYYY-MM, YYYY-MM-DD, today, yesterday, "
                         "thismonth, thisyear or Ndaysago")
    y, mo, d = m.groups()
    return y + (f"-{int(mo):02d}" if mo else "") + (f"-{int(d):02d}" if d else "")


# --------------------------------------------------------------------------- compiler
@dataclass
class CustomColumn:
    num: int
    label: str
    name: str
    datatype: str
    is_multiple: bool
    normalized: bool

    @property
    def table(self) -> str:
        return f"custom_column_{int(self.num)}"

    @property
    def link(self) -> str:
        return f"books_custom_column_{int(self.num)}_link"


# many-to-many "category" fields: (link table, fk column, value table, value column)
CATEGORY = {
    "authors": ("books_authors_link", "author", "authors", "name"),
    "tags": ("books_tags_link", "tag", "tags", "name"),
    "series": ("books_series_link", "series", "series", "name"),
    "publisher": ("books_publishers_link", "publisher", "publishers", "name"),
    "languages": ("books_languages_link", "lang_code", "languages", "lang_code"),
}
ALIASES = {"author": "authors", "tag": "tags", "publishers": "publisher", "language": "languages",
           "format": "formats", "identifier": "identifiers", "isbn": "isbn", "comment": "comments",
           "timestamp": "date", "added": "date", "modified": "last_modified", "published": "pubdate"}
FIELDS = sorted(set(CATEGORY) | {"title", "comments", "formats", "identifiers", "isbn", "rating", "pubdate",
                                 "date", "last_modified", "id", "uuid", "cover", "size", "series_index",
                                 "vl", "search", "#<custom>"})


class Compiler:
    """Compiles an AST to (sql_condition, params) over `books b`."""

    def __init__(self, custom: dict[str, CustomColumn], prefs: Callable[[str], dict],
                 today: Optional[_dt.date] = None):
        self.custom = custom
        self.prefs = prefs
        self.today = today or _dt.date.today()

    def compile(self, query: str, _depth: int = 0, _seen: frozenset = frozenset()) -> tuple[str, list]:
        if _depth > MAX_DEPTH:
            raise QueryError("vl:/search: nesting too deep")
        self._depth, self._seen = _depth, _seen
        return self._node(parse(query))

    # ---- nodes
    def _node(self, n) -> tuple[str, list]:
        if isinstance(n, Op):
            parts = [self._node(a) for a in n.args]
            params = [p for _, ps in parts for p in ps]
            if n.op == "not":
                return f"(NOT {parts[0][0]})", params
            return "(" + f" {n.op.upper()} ".join(s for s, _ in parts) + ")", params
        return self._term(n)

    def _term(self, t: Term) -> tuple[str, list]:
        field = ALIASES.get(t.field, t.field) if t.field else None
        v = t.value
        if field is None:
            subs = [self._text_field(f, v, t.quoted) for f in ("title", "authors", "tags", "series",
                                                                "publisher", "comments")]
            return "(" + " OR ".join(s for s, _ in subs) + ")", [p for _, ps in subs for p in ps]
        if field in ("vl", "search"):
            key = "virtual_libraries" if field == "vl" else "saved_searches"
            store = self.prefs(key) or {}
            name = next((k for k in store if k.lower() == v.lower()), None)
            if name is None:
                raise QueryError(f"Unknown {'virtual library' if field == 'vl' else 'saved search'} {v!r}. "
                                 f"Available: {', '.join(sorted(store)) or 'none'}")
            ident = (field, name)
            if ident in self._seen:
                raise QueryError(f"Recursive definition: {field}:{name}")
            depth, seen = self._depth, self._seen
            sql, params = Compiler(self.custom, self.prefs, self.today).compile(
                store[name], depth + 1, seen | {ident})
            return sql, params
        if field.startswith("#"):
            return self._custom(field[1:], v, t.quoted)
        if field in CATEGORY or field in ("title", "comments", "uuid"):
            return self._text_field(field, v, t.quoted)
        if field == "formats":
            return self._exists("SELECT 1 FROM data d WHERE d.book=b.id", "d.format", v, t.quoted)
        if field in ("identifiers", "isbn"):
            return self._identifiers(v if field == "identifiers" else f"isbn:{v}", t.quoted)
        if field == "rating":
            return self._numeric_exists("SELECT 1 FROM books_ratings_link l JOIN ratings r ON r.id=l.rating "
                                        "WHERE l.book=b.id AND r.rating > 0", "r.rating", v, scale=2.0)
        if field in ("pubdate", "date", "last_modified"):
            col = {"pubdate": "b.pubdate", "date": "b.timestamp", "last_modified": "b.last_modified"}[field]
            return self._date(col, v)
        if field == "id":
            op, n = _num(v)
            return f"(b.id {op} ?)", [int(n)]
        if field == "series_index":
            if v.lower() in ("true", "false"):
                raise QueryError("series_index needs a number")
            op, n = _num(v)
            return (f"(EXISTS (SELECT 1 FROM books_series_link sl WHERE sl.book=b.id) AND b.series_index {op} ?)",
                    [n])
        if field == "cover":
            return ("(b.has_cover = 1)" if self._bool(v) else "(b.has_cover = 0)"), []
        if field == "size":
            op, n = _num(v, units=True)
            return f"((SELECT MAX(d.uncompressed_size) FROM data d WHERE d.book=b.id) {op} ?)", [n]
        raise QueryError(f"Unsupported field {t.field!r}. Supported: {', '.join(FIELDS)}")

    # ---- matchers
    def _match(self, col: str, v: str, quoted: bool) -> tuple[str, list]:
        if v.startswith("="):
            return f"cfold({col}) = cfold(?)", [v[1:]]
        if v.startswith("~"):
            pat = v[1:]
            if len(pat) > REGEX_MAX:
                raise QueryError(f"Regex longer than {REGEX_MAX} chars")
            if _NESTED_QUANT.search(pat) or re.search(r"\\\d", pat):
                raise QueryError("Regex rejected: nested quantifiers like (a+)+ and backreferences can hang the "
                                 "server (Python 're' has no timeout). Simplify the pattern.")
            try:
                re.compile(pat)
            except re.error as exc:
                raise QueryError(f"Bad regex: {exc}") from exc
            return f"regexp(?, {col})", [pat]
        return f"instr(cfold({col}), cfold(?)) > 0", [v]

    def _bool(self, v: str) -> bool:
        lv = v.lower()
        if lv in ("true", "yes", "1"):
            return True
        if lv in ("false", "no", "0"):
            return False
        raise QueryError(f"Expected true/false, got {v!r}")

    def _is_presence(self, v: str, quoted: bool) -> Optional[bool]:
        return None if quoted or v.lower() not in ("true", "false", "yes", "no") else self._bool(v)

    def _exists(self, base_sql: str, col: str, v: str, quoted: bool) -> tuple[str, list]:
        pres = self._is_presence(v, quoted)
        if pres is not None:
            return (f"({'' if pres else 'NOT '}EXISTS ({base_sql}))", [])
        cond, params = self._match(col, v, quoted)
        return f"(EXISTS ({base_sql} AND {cond}))", params

    def _text_field(self, field: str, v: str, quoted: bool) -> tuple[str, list]:
        if field == "title":
            if self._is_presence(v, quoted) is not None:
                return ("(b.title != '')" if self._bool(v) else "(b.title = '')"), []
            cond, params = self._match("b.title", v, quoted)
            return f"({cond})", params
        if field == "uuid":
            cond, params = self._match("b.uuid", v, quoted)
            return f"({cond})", params
        if field == "comments":
            return self._exists("SELECT 1 FROM comments cm WHERE cm.book=b.id AND cm.text != ''", "cm.text",
                                v, quoted)
        lt, fk, tbl, col = CATEGORY[field]
        return self._exists(f"SELECT 1 FROM {lt} l JOIN {tbl} x ON x.id=l.{fk} WHERE l.book=b.id",
                            f"x.{col}", v, quoted)

    def _identifiers(self, v: str, quoted: bool) -> tuple[str, list]:
        base = "SELECT 1 FROM identifiers i WHERE i.book=b.id"
        if ":" in v and not v.startswith(("=", "~")):
            typ, val = v.split(":", 1)
            base_t = base + " AND i.type = ?"
            if val == "" or val.lower() in ("true", "false"):
                pres = val == "" or self._bool(val)
                return f"({'' if pres else 'NOT '}EXISTS ({base_t}))", [typ.lower()]
            cond, params = self._match("i.val", val, quoted)
            return f"(EXISTS ({base_t} AND {cond}))", [typ.lower()] + params
        return self._exists(base, "i.val", v, quoted)

    def _numeric_exists(self, base_sql: str, col: str, v: str, scale: float = 1.0) -> tuple[str, list]:
        if v.lower() in ("true", "false", "yes", "no"):
            return f"({'' if self._bool(v) else 'NOT '}EXISTS ({base_sql}))", []
        op, n = _num(v, scale)
        return f"(EXISTS ({base_sql} AND {col} {op} ?))", [n]

    def _date(self, col: str, v: str, exists_base: Optional[str] = None) -> tuple[str, list]:
        if v.lower() in ("true", "false", "yes", "no"):
            has = self._bool(v)
            if exists_base:
                return f"({'' if has else 'NOT '}EXISTS ({exists_base}))", []
            cond = f"({col} IS NOT NULL AND substr({col},1,4) != '0101')"
            return (cond if has else f"(NOT {cond})"), []
        m = _DATE_RX.match(v.strip())
        op, prefix = (m.group(1) or "="), _date_prefix(m.group(2), self.today)
        n = len(prefix)
        sql_op = {"=": "=", "!=": "!=", ">": ">", "<": "<", ">=": ">=", "<=": "<="}[op]
        cond = f"substr({col},1,{n}) {sql_op} ? AND substr({col},1,4) != '0101'"
        if exists_base:
            return f"(EXISTS ({exists_base} AND {cond}))", [prefix]
        return f"({cond})", [prefix]

    # Calibre's BooleanSearch semantics (src/calibre/db/search.py), incl. the 'bools_are_tristate' pref:
    #   tristate (default): yes/checked -> Yes; no/unchecked -> No; empty/blank/false -> unset; true -> Yes or No
    #   two-state:          yes/checked/true -> Yes; no/unchecked/false -> No or unset
    _YES = {"yes", "_yes", "checked", "_checked", "si", "sì"}
    _NO = {"no", "_no", "unchecked", "_unchecked"}
    _EMPTY = {"empty", "_empty", "blank", "_blank"}

    def _yes_no(self, base: str, v: str) -> tuple[str, list]:
        q = v.strip().lower()
        if q not in self._YES | self._NO | self._EMPTY | {"true", "false"}:
            raise QueryError(f"Invalid yes/no value {v!r}: use yes, no, true, false, checked, unchecked, empty")
        yes, no = f"EXISTS ({base} AND c.value = 1)", f"EXISTS ({base} AND c.value = 0)"
        unset = f"NOT EXISTS ({base})"
        tristate = self.prefs("bools_are_tristate")
        tristate = True if tristate is None else bool(tristate)
        if not tristate:
            return (f"({yes})", []) if q in self._YES | {"true"} else (f"(NOT {yes})", [])
        if q in self._YES:
            return f"({yes})", []
        if q in self._NO:
            return f"({no})", []
        if q == "true":
            return f"(EXISTS ({base}))", []
        return f"({unset})", []  # false, empty, blank

    def _resolve_custom(self, label: str) -> Optional[CustomColumn]:
        """Lookup name first (as Calibre); then forgiving match on lookup name or column heading,
        ignoring case, spaces and punctuation: #mustread / #must_read / heading 'Must Read'."""
        cc = self.custom.get(label.lower())
        if cc is not None:
            return cc
        key = re.sub(r"[\W_]+", "", label).casefold()
        hits = [c for c in self.custom.values()
                if key in (re.sub(r"[\W_]+", "", c.label).casefold(), re.sub(r"[\W_]+", "", c.name).casefold())]
        return hits[0] if len(hits) == 1 else None

    def _custom(self, label: str, v: str, quoted: bool) -> tuple[str, list]:
        cc = self._resolve_custom(label)
        if cc is None:
            raise QueryError(f"Unknown custom column #{label}. Available: " + (", ".join(
                f"#{c.label} ({c.name})" for c in sorted(self.custom.values(), key=lambda c: c.label)) or "none"))
        dt = cc.datatype
        if dt == "composite":
            raise QueryError(f"#{label} is a computed (composite) column: Calibre does not store its values")
        if cc.normalized:
            base = f"SELECT 1 FROM {cc.link} l JOIN {cc.table} c ON c.id=l.value WHERE l.book=b.id"
        else:
            base = f"SELECT 1 FROM {cc.table} c WHERE c.book=b.id"
        if dt in ("int", "float"):
            return self._numeric_exists(base, "c.value", v)
        if dt == "rating":
            return self._numeric_exists(base + " AND c.value > 0", "c.value", v, scale=2.0)
        if dt == "bool":
            return self._yes_no(base, v)
        if dt == "datetime":
            return self._date("c.value", v, exists_base=base)
        return self._exists(base, "c.value", v, quoted)  # text, enumeration, series, comments


# --------------------------------------------------------------------------- SQLite functions
def register_functions(conn, fold: Callable[[str], str]) -> None:
    """cfold: case+accent folding (Calibre's default matching); regexp: capped, case-insensitive."""
    cache: dict[str, Any] = {}

    def cfold(s):
        return None if s is None else fold(str(s)).casefold()

    def regexp(pattern, value):
        if value is None:
            return 0
        rx = cache.get(pattern)
        if rx is None:
            if len(cache) > 64:
                cache.clear()
            rx = cache[pattern] = re.compile(pattern, re.IGNORECASE)
        return 1 if rx.search(str(value)[:REGEX_SUBJECT_MAX]) else 0

    conn.create_function("cfold", 1, cfold, deterministic=True)
    conn.create_function("regexp", 2, regexp, deterministic=True)

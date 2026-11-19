# SPDX-License-Identifier: GPL-3.0-or-later
"""The spreadsheet's formula engine: cell names, parsing and evaluation.

A cell holds what a person typed. Text starting with "=" is a formula; the
rest is a number, a percentage, a date or text. Formulas support + - * / ^ &,
comparisons, cell references (A1, $B$2, Sheet 2!C3), ranges (A1:B9) and the
functions in FUNCTIONS. Errors are values (#DIV/0!, #REF!, #NAME?, #VALUE!,
#CYCLE!) so one bad cell never stops the sheet.
"""
from __future__ import annotations

import datetime as _dt
import math
import re
from typing import Callable, Iterable

__all__ = ["col_name", "col_index", "cell_name", "parse_ref", "Error", "Workbook", "literal",
           "shift_formula", "FUNCTIONS", "display"]

MAX_ROWS, MAX_COLS = 100_000, 702  # A..ZZ


def col_name(c: int) -> str:
    s = ""
    c += 1
    while c:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


def col_index(name: str) -> int:
    n = 0
    for ch in name.upper():
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def cell_name(r: int, c: int) -> str:
    return f"{col_name(c)}{r + 1}"


_REF = re.compile(r"^\$?([A-Za-z]{1,2})\$?(\d{1,6})$")


def parse_ref(text: str) -> tuple[int, int] | None:
    m = _REF.match(text.strip())
    if not m:
        return None
    r, c = int(m.group(2)) - 1, col_index(m.group(1))
    if r < 0 or r >= MAX_ROWS or c >= MAX_COLS:
        return None
    return r, c


class Error(Exception):
    """A spreadsheet error value. `str()` is what the cell shows."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code

    def __str__(self) -> str:
        return self.code

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Error) and other.code == self.code

    def __hash__(self) -> int:
        return hash(self.code)


DIV0, REF, NAME, VALUE, CYCLE, NA, NUM = (Error(x) for x in
                                          ("#DIV/0!", "#REF!", "#NAME?", "#VALUE!", "#CYCLE!", "#N/A", "#NUM!"))
EPOCH = _dt.date(1899, 12, 30)  # spreadsheet day 0


def literal(raw: str):
    """What a typed non-formula string means: float, bool, date serial or text."""
    s = raw.strip()
    if s == "":
        return None
    t = s.replace(",", "")
    try:
        if t.endswith("%"):
            return float(t[:-1]) / 100
        if t.startswith("$"):
            return float(t[1:])
        return float(t)
    except ValueError:
        pass
    if s.upper() in ("TRUE", "FALSE"):
        return s.upper() == "TRUE"
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            d = _dt.datetime.strptime(s, fmt).date()
            return float((d - EPOCH).days)
        except ValueError:
            pass
    return raw


# ---------------------------------------------------------------- tokenizer
_TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<str>"(?:[^"]|"")*")
  | (?P<sref>(?:'[^']+'|[A-Za-z_][\w ]*?)!\$?[A-Za-z]{1,2}\$?\d+(?::\$?[A-Za-z]{1,2}\$?\d+)?)
  | (?P<range>\$?[A-Za-z]{1,2}\$?\d+:\$?[A-Za-z]{1,2}\$?\d+)
  | (?P<num>\d+(?:\.\d*)?(?:[eE][+-]?\d+)?%?|\.\d+(?:[eE][+-]?\d+)?%?)
  | (?P<func>[A-Za-z][A-Za-z0-9.]*(?=\s*\())
  | (?P<ref>\$?[A-Za-z]{1,2}\$?\d+)
  | (?P<bool>TRUE|FALSE|true|false)
  | (?P<op><>|<=|>=|[-+*/^&=<>(),:;%])
""", re.X)


def tokenize(src: str) -> list[tuple[str, str]]:
    out, i = [], 0
    while i < len(src):
        m = _TOKEN.match(src, i)
        if not m:
            raise Error("#NAME?")
        kind = m.lastgroup
        if kind != "ws":
            out.append((kind, m.group(kind)))
        i = m.end()
    return out


# ---------------------------------------------------------------- parser (to a small AST)
class _Parser:
    PREC = {"=": 1, "<>": 1, "<": 1, ">": 1, "<=": 1, ">=": 1, "&": 2, "+": 3, "-": 3, "*": 4, "/": 4, "^": 5}

    def __init__(self, tokens):
        self.t, self.i = tokens, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def parse(self):
        node = self.expr(0)
        if self.i != len(self.t):
            raise Error("#NAME?")
        return node

    def expr(self, min_prec):
        left = self.unary()
        while True:
            kind, val = self.peek()
            if kind != "op" or val not in self.PREC or self.PREC[val] < min_prec:
                return left
            self.take()
            prec = self.PREC[val]
            right = self.expr(prec + (0 if val == "^" else 1))
            left = ("bin", val, left, right)

    def unary(self):
        kind, val = self.peek()
        if kind == "op" and val in "+-":
            self.take()
            return ("neg", self.unary()) if val == "-" else self.unary()
        node = self.atom()
        while self.peek() == ("op", "%"):
            self.take()
            node = ("bin", "/", node, ("num", 100.0))
        return node

    def atom(self):
        kind, val = self.take()
        if kind == "num":
            if val.endswith("%"):
                return ("num", float(val[:-1]) / 100)
            return ("num", float(val))
        if kind == "str":
            return ("str", val[1:-1].replace('""', '"'))
        if kind == "bool":
            return ("bool", val.upper() == "TRUE")
        if kind == "ref":
            p = parse_ref(val)
            if p is None:
                return ("err", REF)
            return ("ref", None, p)
        if kind == "range":
            a, b = val.split(":")
            pa, pb = parse_ref(a), parse_ref(b)
            if pa is None or pb is None:
                return ("err", REF)
            return ("range", None, pa, pb)
        if kind == "sref":
            sheet, rest = val.rsplit("!", 1)
            sheet = sheet.strip("'")
            if ":" in rest:
                a, b = rest.split(":")
                pa, pb = parse_ref(a), parse_ref(b)
                return ("range", sheet, pa, pb) if pa and pb else ("err", REF)
            p = parse_ref(rest)
            return ("ref", sheet, p) if p else ("err", REF)
        if kind == "func":
            name = val.upper()
            if self.take() != ("op", "("):
                raise Error("#NAME?")
            args = []
            if self.peek() != ("op", ")"):
                while True:
                    args.append(self.expr(0))
                    k, v = self.take()
                    if (k, v) == ("op", ")"):
                        break
                    if (k, v) not in (("op", ","), ("op", ";")):
                        raise Error("#NAME?")
            else:
                self.take()
            return ("call", name, args)
        if (kind, val) == ("op", "("):
            node = self.expr(0)
            if self.take() != ("op", ")"):
                raise Error("#NAME?")
            return node
        raise Error("#NAME?")


def parse(src: str):
    return _Parser(tokenize(src)).parse()


# ---------------------------------------------------------------- values
def _num(v):
    if isinstance(v, Error):
        raise v
    if v is None or v == "":
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    lit = literal(str(v))
    if isinstance(lit, (int, float)) and not isinstance(lit, bool):
        return float(lit)
    raise VALUE


def _text(v):
    if isinstance(v, Error):
        raise v
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        return _fmt_number(v)
    return str(v)


def _bool(v):
    if isinstance(v, Error):
        raise v
    if isinstance(v, str):
        if v.upper() in ("TRUE", "FALSE"):
            return v.upper() == "TRUE"
        raise VALUE
    return bool(_num(v))


def _fmt_number(v: float) -> str:
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return f"{v:.10g}"


def _flat(args) -> Iterable:
    for a in args:
        if isinstance(a, list):
            for row in a:
                yield from row
        else:
            yield a


def _nums(args, *, strict_scalars=True):
    out = []
    for a in args:
        if isinstance(a, list):
            for row in a:
                for v in row:
                    if isinstance(v, Error):
                        raise v
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        out.append(float(v))
        else:
            out.append(_num(a) if strict_scalars else a)
    return out


def _criteria(crit):
    """COUNTIF/SUMIF criteria: ">5", "<>x", "=3", "abc", 5."""
    if isinstance(crit, (int, float)) and not isinstance(crit, bool):
        return lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and float(v) == float(crit)
    s = _text(crit)
    m = re.match(r"^(<=|>=|<>|<|>|=)?(.*)$", s)
    op, rhs = m.group(1) or "=", m.group(2)
    lit = literal(rhs)
    numeric = isinstance(lit, float)

    def test(v):
        if numeric:
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                return op == "<>"
            a, b = float(v), lit
        else:
            a, b = _text(v).lower(), rhs.lower()
        return {"=": a == b, "<>": a != b, "<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]
    return test


def _round(x, digits=0):
    q = 10 ** int(_num(digits))
    x = _num(x)
    return math.floor(abs(x) * q + 0.5) / q * (1 if x >= 0 else -1)


def _date(y, m, d):
    y, m, d = int(_num(y)), int(_num(m)), int(_num(d))
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    try:
        base = _dt.date(y, m, 1)
    except ValueError:
        raise NUM
    return float((base - EPOCH).days + d - 1)


def _serial_date(v) -> _dt.date:
    return EPOCH + _dt.timedelta(days=int(_num(v)))


def _vlookup(key, table, col, approx=True):
    if not isinstance(table, list):
        raise VALUE
    col = int(_num(col)) - 1
    if col < 0 or col >= len(table[0]):
        raise REF
    exact = not _bool(approx)
    best = None
    for row in table:
        v = row[0]
        if exact:
            if (_text(v).lower() == _text(key).lower()) if isinstance(key, str) else (
                    isinstance(v, (int, float)) and not isinstance(v, bool) and float(v) == _num(key)):
                return row[col]
        else:
            try:
                if _num(v) <= _num(key):
                    best = row
                else:
                    break
            except Error:
                continue
    if best is None:
        raise NA
    return best[col]


def _avg(*a):
    n = _nums(a)
    if not n:
        raise DIV0
    return sum(n) / len(n)


def _median(*a):
    n = sorted(_nums(a))
    if not n:
        raise NUM
    m = len(n) // 2
    return n[m] if len(n) % 2 else (n[m - 1] + n[m]) / 2


def _stdev(*a):
    n = _nums(a)
    if len(n) < 2:
        raise DIV0
    mu = sum(n) / len(n)
    return math.sqrt(sum((x - mu) ** 2 for x in n) / (len(n) - 1))


def _sumif(rng, crit, sum_rng=None):
    test = _criteria(crit)
    sum_rng = sum_rng if sum_rng is not None else rng
    total = 0.0
    for r, row in enumerate(rng):
        for c, v in enumerate(row):
            if test(v):
                try:
                    s = sum_rng[r][c]
                except IndexError:
                    continue
                if isinstance(s, (int, float)) and not isinstance(s, bool):
                    total += s
    return total


def _countif(rng, crit):
    test = _criteria(crit)
    return float(sum(1 for v in _flat([rng]) if test(v)))


def _pmt(rate, nper, pv, fv=0, typ=0):
    rate, nper, pv, fv, typ = (_num(x) for x in (rate, nper, pv, fv, typ))
    if nper == 0:
        raise NUM
    if rate == 0:
        return -(pv + fv) / nper
    f = (1 + rate) ** nper
    return -(rate * (fv + pv * f)) / ((1 + rate * typ) * (f - 1))


def _iferror(v, alt):
    return alt if isinstance(v, Error) else v


FUNCTIONS: dict[str, Callable] = {
    "SUM": lambda *a: sum(_nums(a)),
    "AVERAGE": _avg,
    "MIN": lambda *a: min(_nums(a), default=0.0),
    "MAX": lambda *a: max(_nums(a), default=0.0),
    "COUNT": lambda *a: float(sum(1 for v in _flat(a) if isinstance(v, (int, float)) and not isinstance(v, bool))),
    "COUNTA": lambda *a: float(sum(1 for v in _flat(a) if v not in (None, ""))),
    "COUNTBLANK": lambda *a: float(sum(1 for v in _flat(a) if v in (None, ""))),
    "COUNTIF": _countif,
    "SUMIF": _sumif,
    "MEDIAN": _median,
    "STDEV": _stdev,
    "PRODUCT": lambda *a: math.prod(_nums(a)),
    "ROUND": _round,
    "ROUNDUP": lambda x, d=0: math.ceil(_num(x) * 10 ** int(_num(d))) / 10 ** int(_num(d)),
    "ROUNDDOWN": lambda x, d=0: math.floor(_num(x) * 10 ** int(_num(d))) / 10 ** int(_num(d)),
    "INT": lambda x: float(math.floor(_num(x))),
    "ABS": lambda x: abs(_num(x)),
    "SQRT": lambda x: math.sqrt(_num(x)) if _num(x) >= 0 else (_ for _ in ()).throw(NUM),
    "POWER": lambda x, y: _num(x) ** _num(y),
    "MOD": lambda x, y: (_num(x) % _num(y)) if _num(y) else (_ for _ in ()).throw(DIV0),
    "PI": lambda: math.pi,
    "IF": None,  # lazy, handled in eval
    "IFERROR": None,  # lazy
    "AND": lambda *a: all(_bool(v) for v in _flat(a) if v not in (None, "")),
    "OR": lambda *a: any(_bool(v) for v in _flat(a) if v not in (None, "")),
    "NOT": lambda x: not _bool(x),
    "CONCAT": lambda *a: "".join(_text(v) for v in _flat(a)),
    "CONCATENATE": lambda *a: "".join(_text(v) for v in _flat(a)),
    "LEN": lambda x: float(len(_text(x))),
    "UPPER": lambda x: _text(x).upper(),
    "LOWER": lambda x: _text(x).lower(),
    "PROPER": lambda x: _text(x).title(),
    "TRIM": lambda x: " ".join(_text(x).split()),
    "LEFT": lambda x, n=1: _text(x)[:int(_num(n))],
    "RIGHT": lambda x, n=1: _text(x)[-int(_num(n)):] if int(_num(n)) else "",
    "MID": lambda x, s, n: _text(x)[int(_num(s)) - 1:int(_num(s)) - 1 + int(_num(n))],
    "TODAY": lambda: float((_dt.date.today() - EPOCH).days),
    "NOW": lambda: (_dt.datetime.now() - _dt.datetime(1899, 12, 30)).total_seconds() / 86400,
    "DATE": _date,
    "YEAR": lambda d: float(_serial_date(d).year),
    "MONTH": lambda d: float(_serial_date(d).month),
    "DAY": lambda d: float(_serial_date(d).day),
    "VLOOKUP": _vlookup,
    "PMT": _pmt,
    "ISBLANK": lambda v: v in (None, ""),
    "ISNUMBER": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "ISTEXT": lambda v: isinstance(v, str) and v != "",
}


# ---------------------------------------------------------------- the workbook
class Workbook:
    """Sheets of raw cell text, with evaluation and caching.

    `sheets` is a list of (name, cells) where cells maps (row, col) -> raw text.
    """

    def __init__(self):
        self.names: list[str] = []
        self.cells: list[dict[tuple[int, int], str]] = []
        self._cache: dict[tuple[int, int, int], object] = {}
        self._busy: set[tuple[int, int, int]] = set()
        self._ast: dict[str, object] = {}

    def add_sheet(self, name: str, cells: dict | None = None) -> int:
        self.names.append(name)
        self.cells.append(dict(cells or {}))
        self.invalidate()
        return len(self.names) - 1

    def invalidate(self):
        self._cache.clear()

    def set(self, sheet: int, r: int, c: int, raw: str):
        if raw.strip() == "":
            self.cells[sheet].pop((r, c), None)
        else:
            self.cells[sheet][(r, c)] = raw
        self.invalidate()

    def raw(self, sheet: int, r: int, c: int) -> str:
        return self.cells[sheet].get((r, c), "")

    def extent(self, sheet: int) -> tuple[int, int]:
        """(rows, cols) used, at least (1, 1)."""
        keys = self.cells[sheet].keys()
        if not keys:
            return 1, 1
        return max(k[0] for k in keys) + 1, max(k[1] for k in keys) + 1

    def value(self, sheet: int, r: int, c: int):
        key = (sheet, r, c)
        if key in self._cache:
            return self._cache[key]
        raw = self.cells[sheet].get((r, c))
        if raw is None:
            return None
        if not raw.startswith("=") or len(raw) == 1:
            v = literal(raw)
            if isinstance(v, str) and v.startswith("'"):
                v = v[1:]
            self._cache[key] = v
            return v
        if key in self._busy:
            return CYCLE
        self._busy.add(key)
        try:
            ast = self._ast.get(raw)
            if ast is None:
                ast = parse(raw[1:])
                self._ast[raw] = ast
            v = self._eval(ast, sheet)
            if isinstance(v, list):
                v = v[0][0] if v and v[0] else None
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                v = NUM
        except Error as e:
            v = e
        except ZeroDivisionError:
            v = DIV0
        except (OverflowError, ValueError):
            v = NUM
        except RecursionError:
            v = CYCLE
        finally:
            self._busy.discard(key)
        self._cache[key] = v
        return v

    def _sheet_index(self, name):
        if name is None:
            return None
        for i, n in enumerate(self.names):
            if n.lower() == name.lower():
                return i
        raise REF

    def _eval(self, node, sheet):
        kind = node[0]
        if kind in ("num", "str", "bool"):
            return node[1]
        if kind == "err":
            raise node[1]
        if kind == "neg":
            return -_num(self._scalar(self._eval(node[1], sheet)))
        if kind == "ref":
            s = self._sheet_index(node[1])
            s = sheet if s is None else s
            v = self.value(s, *node[2])
            return v
        if kind == "range":
            s = self._sheet_index(node[1])
            s = sheet if s is None else s
            (r1, c1), (r2, c2) = node[2], node[3]
            r1, r2 = sorted((r1, r2))
            c1, c2 = sorted((c1, c2))
            if (r2 - r1 + 1) * (c2 - c1 + 1) > 1_000_000:
                raise REF
            return [[self.value(s, r, c) for c in range(c1, c2 + 1)] for r in range(r1, r2 + 1)]
        if kind == "bin":
            op = node[1]
            a = self._scalar(self._eval(node[2], sheet))
            b = self._scalar(self._eval(node[3], sheet))
            if op == "&":
                return _text(a) + _text(b)
            if op in ("=", "<>", "<", ">", "<=", ">="):
                if isinstance(a, Error):
                    raise a
                if isinstance(b, Error):
                    raise b
                try:
                    x, y = _num(a), _num(b)
                except Error:
                    x, y = _text(a).lower(), _text(b).lower()
                return {"=": x == y, "<>": x != y, "<": x < y, ">": x > y, "<=": x <= y, ">=": x >= y}[op]
            x, y = _num(a), _num(b)
            if op == "+":
                return x + y
            if op == "-":
                return x - y
            if op == "*":
                return x * y
            if op == "/":
                if y == 0:
                    raise DIV0
                return x / y
            if op == "^":
                return x ** y
        if kind == "call":
            name, args = node[1], node[2]
            if name == "IF":
                if len(args) < 2:
                    raise VALUE
                cond = _bool(self._scalar(self._eval(args[0], sheet)))
                if cond:
                    return self._eval(args[1], sheet)
                return self._eval(args[2], sheet) if len(args) > 2 else False
            if name == "IFERROR":
                if len(args) != 2:
                    raise VALUE
                try:
                    v = self._eval(args[0], sheet)
                    v = self._scalar(v) if not isinstance(v, list) else v
                    if isinstance(v, Error):
                        raise v
                    return v
                except Error:
                    return self._eval(args[1], sheet)
            fn = FUNCTIONS.get(name)
            if fn is None:
                raise NAME
            vals = [self._eval(a, sheet) for a in args]
            try:
                return fn(*vals)
            except TypeError:
                raise VALUE
        raise NAME

    @staticmethod
    def _scalar(v):
        if isinstance(v, list):
            if len(v) == 1 and len(v[0]) == 1:
                return v[0][0]
            raise VALUE
        return v


# ---------------------------------------------------------------- moving formulas
_SHIFT = re.compile(r"(\"(?:[^\"]|\"\")*\")|((?:'[^']+'|[A-Za-z_][\w]*)!)?(\$?)([A-Za-z]{1,2})(\$?)(\d{1,6})(?![\w(])")


def shift_formula(raw: str, dr: int, dc: int) -> str:
    """Move a formula's relative references by (dr, dc), as copy and fill do."""
    if not raw.startswith("="):
        return raw

    def sub(m):
        if m.group(1):
            return m.group(1)
        sheet, dcol, col, drow, row = m.group(2) or "", m.group(3), m.group(4), m.group(5), m.group(6)
        if col.upper() in ("TRUE", "FALSE"):
            return m.group(0)
        c = col_index(col) + (0 if dcol else dc)
        r = int(row) - 1 + (0 if drow else dr)
        if c < 0 or r < 0:
            return "#REF!"
        return f"{sheet}{dcol}{col_name(c)}{drow}{r + 1}"
    return _SHIFT.sub(sub, raw)


# ---------------------------------------------------------------- showing values
FORMATS = ("general", "number", "currency", "percent", "date", "text")


def display(value, fmt: str = "general") -> str:
    """The text a cell shows for a value in a number format."""
    if value is None:
        return ""
    if isinstance(value, Error):
        return value.code
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        if fmt == "number":
            return f"{value:,.2f}"
        if fmt == "currency":
            return f"-${-value:,.2f}" if value < 0 else f"${value:,.2f}"
        if fmt == "percent":
            return f"{value * 100:.1f}%".replace(".0%", "%")
        if fmt == "date":
            try:
                return _serial_date(value).isoformat()
            except (OverflowError, ValueError, Error):
                return "#NUM!"
        return _fmt_number(value)
    return str(value)

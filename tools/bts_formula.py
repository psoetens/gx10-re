"""Evaluators for the small DSLs BTS uses inside `effect_parameter.js`:

- `format_value(raw, format_js, factor=None) -> str`
  Apply a BTS `format` expression (e.g. `"value + '%'"`, `"Math.floor(value / 10)"`,
  `"formatHarmonistUserShift('A', value)"`) to a raw integer and return the
  display string. Whitelists the 18 known patterns; raises `UnknownFormat`
  on anything else so a future BTS change surfaces instead of silently
  mis-formatting.

- `evaluate_condition(expr, ctx) -> bool`
  Evaluate a BTS `showConditions` expression like
  `"{type} === 0 || {type} === 1 || {type} === 2"` against a context dict
  like `{"type": 3, "voice": 0}`. Supports the small operator set BTS
  actually uses; raises `UnknownCondition` on anything outside it.

The catalog stores BTS's expressions verbatim (`display.format_js`,
`show_when`); downstream tools call into this module rather than re-parsing
the strings themselves.
"""
from __future__ import annotations
import re
from typing import Any


# ---------------------------------------------------------------------------
# Harmonist shift table (mirrors BTS's SHIFT_ARRAY + HARM_INDEX_ARRAY)
# ---------------------------------------------------------------------------

# Index keys BTS uses in formatHarmonistUserShift('<key>', value)
HARM_INDEX = ["C", "Db", "D", "Eb", "E", "F", "FS", "G", "Ab", "A", "Bb", "B"]

# Reverse lookup: case-tolerant
_HARM_INDEX_MAP = {k.upper(): i for i, k in enumerate(HARM_INDEX)}

# BTS's SHIFT_ARRAY: 4 octaves of chromatic notes for shift display
SHIFT_ARRAY = (
    ["C", "D♭", "D", "E♭", "E", "F", "F#", "G", "A♭", "A", "B♭", "B"] * 4
    + ["C"]  # 49 entries
)


def _harmonist_user_shift(key: str, value: int) -> str:
    """Mirror BTS's `formatHarmonistUserShift(indexString, value)`."""
    index = _HARM_INDEX_MAP.get(key.upper())
    if index is None:
        raise UnknownFormat(f"unknown harmonist index {key!r}")
    if value < 24:
        number_part = "- " + str((value - 24) * -1)
    elif value == 24:
        number_part = str(value - 24)
    else:
        number_part = "+ " + str(value - 24)
    return number_part + SHIFT_ARRAY[(index + value) % len(HARM_INDEX)]


# ---------------------------------------------------------------------------
# format_js
# ---------------------------------------------------------------------------

class UnknownFormat(ValueError):
    pass


# Compiled patterns for the known shapes. Each handler takes (raw, match)
# and returns the display string.

def _h_suffix(raw, m):
    return f"{raw}{m.group(1)}"


def _h_signed(raw, m):
    return ("+" + str(raw)) if raw > 0 else str(raw)


def _h_signed_unit(raw, m):
    s = ("+" + str(raw)) if raw > 0 else str(raw)
    return s + m.group(1)


def _h_signed_offset(raw, m):
    offset = int(m.group(1))
    delta = raw - offset
    return ("+" + str(delta)) if delta > 0 else str(delta)


def _h_floor_scale(raw, m):
    return str(raw // int(m.group(1)))


def _h_harmonist(raw, m):
    return _harmonist_user_shift(m.group(1), raw)


# Order matters — try the more specific patterns first.
_FORMAT_PATTERNS = [
    (re.compile(r"^\s*Math\.floor\(\s*value\s*/\s*(\d+)\s*\)\s*$"), _h_floor_scale),
    (re.compile(r"^\s*formatHarmonistUserShift\(\s*['\"]([A-Za-z#]+)['\"]\s*,\s*value\s*\)\s*$"), _h_harmonist),
    (re.compile(r"^\s*\(\(\s*value\s*-\s*(\d+)\s*\)\s*>\s*0\s*\?\s*'\+'\s*:\s*''\s*\)\s*\+\s*\(\s*value\s*-\s*\1\s*\)\s*$"), _h_signed_offset),
    (re.compile(r"^\s*\(\s*value\s*>\s*0\s*\?\s*'\+'\s*:\s*''\s*\)\s*\+\s*value\s*\+\s*'([^']*)'\s*$"), _h_signed_unit),
    (re.compile(r"^\s*\(\s*value\s*>\s*0\s*\?\s*'\+'\s*:\s*''\s*\)\s*\+\s*value\s*$"), _h_signed),
    (re.compile(r"^\s*value\s*\+\s*'([^']*)'\s*$"), _h_suffix),
]


def format_value(raw: int, format_js: str | None, factor: int | None = None) -> str:
    """Convert raw → display per BTS rules.

    `factor` is BTS's `factor` field (currently always 10 when present);
    when supplied it's the divisor for the `Math.floor(value / factor)`
    pattern. The format string itself encodes the same constant, so
    `factor` here is informational only.
    """
    if format_js is None:
        return str(raw)
    for pat, handler in _FORMAT_PATTERNS:
        m = pat.match(format_js)
        if m:
            return handler(raw, m)
    raise UnknownFormat(f"no rule matches format expression {format_js!r}")


# ---------------------------------------------------------------------------
# showConditions
# ---------------------------------------------------------------------------

class UnknownCondition(ValueError):
    pass


# Tokens: {name}, identifiers, integers, operators, parentheses
_TOKEN_RE = re.compile(r"""
    \s*(
        \{[A-Za-z0-9_:\-]+\}                |   # parameter ref
        getSyncClock\s*\(\s*\)              |   # special call
        ===|!==|==|!=|<=|>=|<|>             |   # comparison operators
        &&|\|\|                              |   # logical operators
        \(|\)                                |   # parens
        -?\d+                                |   # integer literal
        '[^']*'                              |   # string literal (unused in
                                                  # current set but parsed)
        [A-Za-z_][A-Za-z0-9_]*                   # bare identifier (rare)
    )
""", re.VERBOSE)


def _tokenize_condition(expr: str) -> list[str]:
    toks = []
    pos = 0
    while pos < len(expr):
        m = _TOKEN_RE.match(expr, pos)
        if not m:
            if expr[pos].isspace():
                pos += 1
                continue
            raise UnknownCondition(f"unparseable at pos {pos}: {expr!r}")
        toks.append(m.group(1))
        pos = m.end()
    return toks


class _CondParser:
    """Recursive-descent parser for the BTS showCondition mini-language.

    Grammar (ascending precedence):
        or   := and ('||' and)*
        and  := cmp ('&&' cmp)*
        cmp  := atom OP atom            (OP is ===, ==, !=, !==, <, <=, >, >=)
              | atom                    (rare: bare boolean atom)
        atom := '{' name '}'            -> ctx[name]
              | getSyncClock()          -> ctx['getSyncClock'] (default 0)
              | integer literal
              | '(' or ')'
    """

    def __init__(self, tokens: list[str], ctx: dict[str, Any]):
        self.toks = tokens
        self.i = 0
        self.ctx = ctx

    def _peek(self, k=0):
        j = self.i + k
        return self.toks[j] if j < len(self.toks) else None

    def _eat(self, t=None):
        if t is not None and self._peek() != t:
            raise UnknownCondition(f"expected {t!r}, got {self._peek()!r}")
        self.i += 1
        return self.toks[self.i - 1]

    def parse_or(self):
        left = self.parse_and()
        while self._peek() == "||":
            self._eat()
            right = self.parse_and()
            left = bool(left) or bool(right)
        return left

    def parse_and(self):
        left = self.parse_cmp()
        while self._peek() == "&&":
            self._eat()
            right = self.parse_cmp()
            left = bool(left) and bool(right)
        return left

    def parse_cmp(self):
        left = self.parse_atom()
        op = self._peek()
        if op in ("===", "==", "!==", "!=", "<", "<=", ">", ">="):
            self._eat()
            right = self.parse_atom()
            return _apply_cmp(op, left, right)
        return left

    def parse_atom(self):
        t = self._peek()
        if t is None:
            raise UnknownCondition("unexpected end of expression")
        if t == "(":
            self._eat("(")
            v = self.parse_or()
            self._eat(")")
            return v
        self._eat()
        if t.startswith("{") and t.endswith("}"):
            name = t[1:-1]
            if name not in self.ctx:
                raise UnknownCondition(f"context missing parameter {name!r}")
            return self.ctx[name]
        if t == "getSyncClock()":
            return self.ctx.get("getSyncClock", 0)
        if t.lstrip("-").isdigit():
            return int(t)
        if t.startswith("'") and t.endswith("'"):
            return t[1:-1]
        # Bare identifier: look up in ctx (used by patterns like
        # `{DIVIDER:mode} == 1`, where DIVIDER:mode is a qualified name).
        if name_match := re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", t):
            if t in self.ctx:
                return self.ctx[t]
            raise UnknownCondition(f"unknown identifier {t!r}")
        raise UnknownCondition(f"unparseable atom {t!r}")


def _apply_cmp(op, l, r):
    if op == "===" or op == "==":
        return l == r
    if op == "!==" or op == "!=":
        return l != r
    if op == "<":
        return l < r
    if op == "<=":
        return l <= r
    if op == ">":
        return l > r
    if op == ">=":
        return l >= r
    raise UnknownCondition(f"unsupported operator {op!r}")


def evaluate_condition(expr: str, ctx: dict[str, Any]) -> bool:
    """Evaluate a BTS showCondition string against a parameter-value context.

    `ctx` keys are the parameter names BTS references inside `{ ... }`,
    e.g. `{"type": 3, "voice": 0, "sp-type": 2}`. `getSyncClock()` calls
    consult `ctx["getSyncClock"]` (default 0).
    """
    parser = _CondParser(_tokenize_condition(expr), ctx)
    result = parser.parse_or()
    if parser.i != len(parser.toks):
        raise UnknownCondition(
            f"trailing tokens after parse: {parser.toks[parser.i:]} in {expr!r}")
    return bool(result)


def all_conditions_pass(exprs: list[str] | None, ctx: dict[str, Any]) -> bool:
    """A parameter is visible iff ALL its `showConditions` evaluate true."""
    if not exprs:
        return True
    return all(evaluate_condition(e, ctx) for e in exprs)


# ---------------------------------------------------------------------------
# Self-test (`python -m tools.bts_formula` or `python tools/bts_formula.py`)
# ---------------------------------------------------------------------------

def _selftest():
    # format_value
    assert format_value(50, "value + '%'") == "50%"
    assert format_value(120, "value + 'ms'") == "120ms"
    assert format_value(0, "(value > 0 ? '+' : '') + value") == "0"
    assert format_value(5, "(value > 0 ? '+' : '') + value") == "+5"
    assert format_value(-3, "(value > 0 ? '+' : '') + value") == "-3"
    assert format_value(10, "(value > 0 ? '+' : '') + value + 'dB'") == "+10dB"
    assert format_value(40, "((value - 50) > 0 ? '+' : '') + (value - 50)") == "-10"
    assert format_value(70, "((value - 50) > 0 ? '+' : '') + (value - 50)") == "+20"
    assert format_value(1200, "Math.floor(value / 10)") == "120"
    # Harmonist: C + 24 (unison) -> '0C'
    assert format_value(24, "formatHarmonistUserShift('C', value)") == "0C"
    # C - 1 semitone = 23 -> '- 1B'  (index C=0, 0+23=23, SHIFT_ARRAY[23%12]=SHIFT_ARRAY[11]='B')
    assert format_value(23, "formatHarmonistUserShift('C', value)") == "- 1B"

    # evaluate_condition
    assert evaluate_condition("{type} === 3", {"type": 3}) is True
    assert evaluate_condition("{type} === 3", {"type": 0}) is False
    assert evaluate_condition(
        "{type} === 0 || {type} === 1 || {type} === 2", {"type": 1}) is True
    assert evaluate_condition(
        "{sp-type} >= 1 && {sp-type} <= 13 ", {"sp-type": 7}) is True
    assert evaluate_condition(
        "{sp-type} !== 0 && {sp-type} <= 13", {"sp-type": 0}) is False
    assert evaluate_condition(
        "({voice} === 1 || {voice} === 2) && {hr2-harmony} === 29",
        {"voice": 1, "hr2-harmony": 29}) is True
    assert evaluate_condition("getSyncClock() > 0", {"getSyncClock": 1}) is True
    assert evaluate_condition("getSyncClock() === 0", {"getSyncClock": 0}) is True

    print("ok")


if __name__ == "__main__":
    _selftest()

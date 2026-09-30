"""Number formatting and float semantics the generated files rely on.

The paper's tables, data files and the validation report were first written
by Rust; these helpers reproduce Rust's `{}`, `{:.N}`, `{:e}`, `{:.Ne}` and
`{:?}` for `f64`, IEEE division (`x / 0` is `±inf` or `NaN`, not an error)
and `f64::round` (half away from zero), so that regenerating them changes no
byte.
"""

from __future__ import annotations

import math
from decimal import Decimal

import numpy as np


def div(a: float, b: float) -> float:
    """IEEE `a / b`."""
    if b == 0.0:
        if a == 0.0 or math.isnan(a):
            return math.nan
        return math.copysign(math.inf, a) * math.copysign(1.0, b)
    return a / b


def fmin(a: float, b: float) -> float:
    """`f64::min`: a NaN operand is ignored."""
    if math.isnan(a):
        return b
    if math.isnan(b):
        return a
    return a if a <= b else b


def fmax(a: float, b: float) -> float:
    """`f64::max`: a NaN operand is ignored."""
    if math.isnan(a):
        return b
    if math.isnan(b):
        return a
    return a if a >= b else b


def fold_min(xs, init: float = math.inf) -> float:
    """`xs.fold(init, f64::min)`."""
    acc = init
    for x in xs:
        acc = fmin(acc, x)
    return acc


def fold_max(xs, init: float = -math.inf) -> float:
    """`xs.fold(init, f64::max)`."""
    acc = init
    for x in xs:
        acc = fmax(acc, x)
    return acc


def rround(x: float) -> float:
    """`f64::round`: half away from zero."""
    if not math.isfinite(x):
        return x
    f = math.floor(abs(x))
    r = f + 1.0 if abs(x) - f >= 0.5 else f
    return math.copysign(r, x)


def ssum(xs) -> float:
    """Sequential left-to-right sum, as Rust's `Iterator::sum` (Python's
    `sum` of floats is compensated since 3.12, numpy's is pairwise)."""
    a = np.asarray(xs, dtype=np.float64)
    if a.size == 0:
        return 0.0
    return float(np.cumsum(a)[-1])


def _special(x: float) -> str | None:
    if math.isnan(x):
        return "NaN"
    if math.isinf(x):
        return "inf" if x > 0 else "-inf"
    return None


def disp(x) -> str:
    """Rust `{}` of an `f64` (shortest round trip, no exponent); ints as is."""
    if isinstance(x, (int, np.integer)) and not isinstance(x, bool):
        return str(int(x))
    x = float(x)
    s = _special(x)
    if s is not None:
        return s
    t = format(Decimal(repr(x)), "f")
    if "." in t:
        t = t.rstrip("0").rstrip(".")
    return t


def dbg(x: float) -> str:
    """Rust `{:?}` of an `f64`."""
    x = float(x)
    s = _special(x)
    if s is not None:
        return s
    a = abs(x)
    if a != 0.0 and (a < 1e-4 or a >= 1e16):
        return sci(x)
    t = disp(x)
    return t if "." in t else t + ".0"


def fixed(x: float, d: int) -> str:
    """Rust `{:.d}` of an `f64`."""
    x = float(x)
    s = _special(x)
    if s is not None:
        return s
    return format(x, f".{d}f")


def signed(x: float, d: int) -> str:
    """Rust `{:+.d}`."""
    x = float(x)
    s = _special(x)
    if s is not None:
        return ("+" + s) if s == "inf" else s
    return format(x, f"+.{d}f")


def sci(x: float) -> str:
    """Rust `{:e}`: shortest digits, `1.5e-3`, `5e3`, no `+`."""
    x = float(x)
    s = _special(x)
    if s is not None:
        return s
    if x == 0.0:
        return "-0e0" if math.copysign(1.0, x) < 0 else "0e0"
    sign, digits, exp = Decimal(repr(x)).normalize().as_tuple()
    ds = "".join(map(str, digits))
    e = exp + len(ds) - 1
    mant = ds[0] + ("." + ds[1:] if len(ds) > 1 else "")
    return ("-" if sign else "") + f"{mant}e{e}"


def sci_fixed(x: float, d: int) -> str:
    """Rust `{:.de}`: `4.0e6`, `2.00e7`, `5e3`."""
    x = float(x)
    s = _special(x)
    if s is not None:
        return s
    m, e = format(x, f".{d}e").split("e")
    return f"{m}e{int(e)}"


def number(x: float) -> str:
    """A literal serQ parses back to exactly `x` (`inf` is a serQ constant)."""
    return sci(x)

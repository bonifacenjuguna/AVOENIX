"""Exact arithmetic over expression trees. No ``eval`` anywhere."""

from __future__ import annotations

from fractions import Fraction
from typing import Union

Number = Union[int, float, Fraction]
Tree = Union[Number, tuple]   # (op, child, child...)

MAX_ABS = 10 ** 30


class ArithmeticError_(ArithmeticError):
    pass


def _frac(x: Number) -> Fraction:
    if isinstance(x, Fraction):
        return x
    if isinstance(x, float):
        return Fraction(str(x))     # decimal-faithful: 0.1 -> 1/10
    return Fraction(x)


def evaluate(tree: Tree) -> Fraction:
    """Evaluate a tree like ``('add', 2, ('mul', 3, 4))`` exactly."""
    if isinstance(tree, (int, float, Fraction)) and not isinstance(tree, bool):
        return _frac(tree)
    if not isinstance(tree, tuple) or not tree:
        raise ArithmeticError_(f"bad expression: {tree!r}")
    op, *args = tree
    vals = [evaluate(a) for a in args]
    if op == "add":
        res = sum(vals, Fraction(0))
    elif op == "sub":
        res = vals[0] - sum(vals[1:], Fraction(0))
    elif op == "mul":
        res = Fraction(1)
        for v in vals:
            res *= v
    elif op == "div":
        res = vals[0]
        for v in vals[1:]:
            if v == 0:
                raise ArithmeticError_("division by zero")
            res /= v
    elif op == "neg":
        res = -vals[0]
    elif op == "pow":
        base, exp = vals
        if exp.denominator != 1:
            raise ArithmeticError_("fractional exponents are not supported")
        if abs(exp) > 64 or abs(base) > MAX_ABS:
            raise ArithmeticError_("exponent too large")
        if base == 0 and exp < 0:
            raise ArithmeticError_("division by zero")
        res = base ** int(exp)
    elif op == "percent_of":
        pct, whole = vals
        res = pct / 100 * whole
    elif op == "sqrt":
        v = vals[0]
        if v < 0:
            raise ArithmeticError_("square root of a negative number")
        num, den = _isqrt_exact(v.numerator), _isqrt_exact(v.denominator)
        if num is None or den is None:
            raise ArithmeticError_("irrational result not supported exactly")
        res = Fraction(num, den)
    else:
        raise ArithmeticError_(f"unknown operator {op!r}")
    if abs(res) > MAX_ABS:
        raise ArithmeticError_("result too large")
    return res


def _isqrt_exact(n: int) -> int | None:
    import math

    r = math.isqrt(n)
    return r if r * r == n else None


def render(value: Fraction, *, places: int = 6) -> str:
    """Human-friendly exact rendering: integers plainly, terminating decimals exactly,
    otherwise a fraction plus a rounded decimal."""
    if value.denominator == 1:
        return str(value.numerator)
    d = value.denominator
    for p in (2, 5):
        while d % p == 0:
            d //= p
    if d == 1:  # terminating decimal
        s = f"{float(value):.{places}f}".rstrip("0").rstrip(".")
        return s
    return f"{value.numerator}/{value.denominator} (about {float(value):.{min(places, 4)}f})"

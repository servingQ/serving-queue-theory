"""A law of `theory.dist` as an expression in serQ's sampler."""

from __future__ import annotations

from fmt import number
from theory.dist import (
    Bernoulli,
    Deterministic,
    Discrete,
    Dist,
    Erlang,
    Exponential,
    HitMiss,
    HyperExp,
    Uniform,
)


def expr(d: Dist) -> str:
    """The law `d` as an expression in serQ's sampler."""
    if isinstance(d, Deterministic):
        return f"~det({number(d.x)})"
    if isinstance(d, Exponential):
        return f"~exp({number(d.mean_)})"
    if isinstance(d, Erlang):
        return f"~erlang({d.k}, {number(d.mean_)})"
    if isinstance(d, HyperExp):
        return f"(~bernoulli({number(d.p)}) ? ~exp({number(d.mean1)}) : ~exp({number(d.mean2)}))"
    if isinstance(d, Uniform):
        return f"~uniform({number(d.lo)}, {number(d.hi)})"
    if isinstance(d, Discrete):
        assert d.values and len(d.values) == len(d.probs)
        tail = number(d.values[-1])
        suffix = d.probs[-1]
        for value, prob in reversed(list(zip(d.values[:-1], d.probs[:-1], strict=True))):
            suffix += prob
            if prob > 0.0:
                tail = f"(~bernoulli({number(prob / suffix)}) ? {number(value)} : {tail})"
        return tail
    if isinstance(d, HitMiss):
        return f"(~bernoulli({number(d.p_hit)}) ? {number(d.hit)} : {number(d.miss)})"
    if isinstance(d, Bernoulli):
        return f"~bernoulli({number(d.p)})"
    raise TypeError(f"no serQ sampler for {d!r}")

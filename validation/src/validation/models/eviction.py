"""Offline eviction instances (paper §3.1, Props. blind and guarded; the
eviction-replay experiment's offline part).

Problem (evict): choose a subset of suspended programs with context lengths
`c_i` freeing at least `ΔC`, minimising `Σ w_i`. With `Item`, `w_i = p_i c_i²`
(`p_i = 1` recovers ThunderAgent Def. 4.1); with `Weighted`, `w_i ≥ 0` is
arbitrary (e.g. the congestion price `p_i Φ_i`). `optimal_weighted` solves it
exactly by dynamic programming over freed tokens, so heuristics can be scored
as cost/OPT on many random instances. `guarded_density` is the guarded
density greedy (`guardedGreedy_two_approx` in DensityGreedy.lean).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np

from ..fmt import fmax, rround
from ..rng import StdRng


@dataclass(frozen=True)
class Item:
    """A suspended program: context length and resume probability."""

    c: int
    p: float

    @classmethod
    def uniform(cls, c: int) -> Item:
        return cls(c, 1.0)

    def cost(self) -> float:
        """Expected recompute cost `p c²` (`expectedEvictCost`)."""
        c = float(self.c)
        return self.p * (c * c)

    def density(self) -> float:
        """Cost per token freed, `p c` (`evictDensity`)."""
        return self.p * float(self.c)

    def weighted(self) -> Weighted:
        return Weighted(self.c, self.cost())


@dataclass(frozen=True)
class Weighted:
    """A suspended program with an arbitrary nonnegative eviction weight."""

    c: int
    w: float

    def density(self) -> float:
        return self.w / float(self.c)


def evict_cost(s) -> int:
    """`evictCost`: `Σ c²` (Eviction.lean)."""
    return sum(c * c for c in s)


def shortest_first_lean(ctx, delta: int) -> list[int]:
    """`shortestFirst` exactly as defined in Eviction.lean."""
    if delta == 0 or not ctx:
        return []
    c, rest = ctx[0], ctx[1:]
    if delta <= c:
        return [c]
    return [c, *shortest_first_lean(rest, delta - c)]


def _take_until(items, order, delta: int) -> list[int]:
    freed, out = 0, []
    for i in order:
        if freed >= delta:
            break
        freed += items[i].c
        out.append(i)
    return out


def _sorted_by_key(items, key) -> list[int]:
    return sorted(range(len(items)), key=lambda i: (key(items[i]), i))


def _weighted(items) -> list[Weighted]:
    return [it.weighted() for it in items]


def shortest_first(items, delta: int) -> list[int]:
    return shortest_first_weighted(_weighted(items), delta)


def density_first(items, delta: int) -> list[int]:
    return density_weighted(_weighted(items), delta)


def shortest_first_weighted(items, delta: int) -> list[int]:
    """SF on general weights (the order ignores the weights)."""
    return _take_until(items, _sorted_by_key(items, lambda it: float(it.c)), delta)


def density_weighted(items, delta: int) -> list[int]:
    """Plain density greedy: increasing `w_i / c_i` until `delta` is freed."""
    return _take_until(items, _sorted_by_key(items, Weighted.density), delta)


def weighted_cost(items, s) -> float:
    acc = 0.0
    for i in s:
        acc += items[i].w
    return acc


def weighted_freed(items, s) -> int:
    return sum(items[i].c for i in s)


def subset_cost(items, s) -> float:
    acc = 0.0
    for i in s:
        acc += items[i].cost()
    return acc


def subset_freed(items, s) -> int:
    return sum(items[i].c for i in s)


def guarded_density(items, delta: int) -> list[int] | None:
    """Guarded density greedy (paper Prop. guarded): for each candidate `e`
    (the guess for the heaviest item of an optimum), take `e` and then the
    items `j ≠ e` with `w_j ≤ w_e` in increasing `w_j / c_j` until `ΔC` is
    freed; return the cheapest candidate. `None` iff infeasible."""
    if delta == 0:
        return []
    order = _sorted_by_key(items, Weighted.density)
    best = None
    for e, it in enumerate(items):
        s, freed = [e], it.c
        for j in order:
            if freed >= delta:
                break
            if j != e and items[j].w <= it.w:
                freed += items[j].c
                s.append(j)
        if freed < delta:
            continue
        cost = weighted_cost(items, s)
        if best is None or cost < best[0]:
            best = (cost, s)
    return None if best is None else best[1]


def guarded_density_items(items, delta: int):
    return guarded_density(_weighted(items), delta)


def optimal(items, delta: int):
    return optimal_weighted(_weighted(items), delta)


def optimal_weighted(items, delta: int) -> tuple[float, list[int]] | None:
    """Exact optimum by 0/1 covering-knapsack DP, `O(n·ΔC)`. `None` if
    evicting everything does not free `delta`."""
    d, n = int(delta), len(items)
    idx = np.arange(d + 1)
    rows = [np.full(d + 1, np.inf)]
    rows[0][0] = 0.0
    for it in items:
        prev = rows[-1]
        with_ = prev[np.maximum(idx - it.c, 0)] + it.w
        rows.append(np.minimum(prev, with_))
    opt = float(rows[n][d])
    if not np.isfinite(opt):
        return None
    s, j = [], d
    for k in range(n - 1, -1, -1):
        if rows[k + 1][j] != rows[k][j]:
            s.append(k)
            j = max(j - items[k].c, 0)
    s.reverse()
    return opt, s


class ResumeModel(Enum):
    Uniform = "Uniform"  # all p_i = 1
    Varied = "Varied"  # p_i i.i.d. uniform on [lo, 1]
    ShorterResumes = "ShorterResumes"  # p_i falls with c_i


@dataclass(frozen=True)
class Resume:
    model: ResumeModel
    lo: float = 0.0


UNIFORM = Resume(ResumeModel.Uniform)
SHORTER_RESUMES = Resume(ResumeModel.ShorterResumes)


def varied(lo: float) -> Resume:
    return Resume(ResumeModel.Varied, lo)


@dataclass
class Instance:
    items: list[Item]
    delta: int


def _delta(rng: StdRng, total: int) -> int:
    frac = rng.range_f64(0.1, 0.6)
    return max(int(rround(total * frac)), 1)


def random_instance(rng: StdRng, n: int, max_c: int, resume: Resume) -> Instance:
    """`n` programs with `c_i` uniform on `1..=max_c`, `ΔC` a uniform fraction
    in `[0.1, 0.6]` of the total."""
    items = []
    for _ in range(n):
        c = rng.range_u64(1, max_c)
        if resume.model == ResumeModel.Uniform:
            p = 1.0
        elif resume.model == ResumeModel.Varied:
            p = rng.range_f64(resume.lo, 1.0)
        else:
            x = c / float(max_c)
            p = fmax(1.0 - 0.95 * x * x, 0.05)
        items.append(Item(c, p))
    return Instance(items, _delta(rng, sum(i.c for i in items)))


@dataclass
class WeightedInstance:
    items: list[Weighted]
    delta: int


def random_weighted_instance(rng: StdRng, n: int, max_c: int) -> WeightedInstance:
    """`c_i` uniform on `1..=max_c`, `w_i` log-uniform on `[1e-4, 1e5]`."""
    items = []
    for _ in range(n):
        c = rng.range_u64(1, max_c)
        w = 10.0 ** rng.range_f64(-4.0, 5.0)
        items.append(Weighted(c, w))
    return WeightedInstance(items, _delta(rng, sum(i.c for i in items)))


@dataclass(frozen=True)
class Ratios:
    """Cost/OPT of SF, of the density rule and of the guarded greedy."""

    shortest_first: float
    density_first: float
    guarded_density: float


def ratios_weighted(items, delta: int) -> Ratios:
    opt, _ = optimal_weighted(items, delta)

    def r(s):
        c = weighted_cost(items, s)
        if opt == 0.0:
            return 1.0 if c == 0.0 else float("inf")
        return c / opt

    return Ratios(
        r(shortest_first_weighted(items, delta)),
        r(density_weighted(items, delta)),
        r(guarded_density(items, delta)),
    )


def ratios(inst: Instance) -> Ratios:
    return ratios_weighted(_weighted(inst.items), inst.delta)


def sweep(count: int, n: int, max_c: int, resume: Resume, seed: int) -> list[Ratios]:
    """Score the heuristics on `count` random instances."""
    rng = StdRng.seed_from_u64(seed)
    return [ratios(random_instance(rng, n, max_c, resume)) for _ in range(count)]


def sweep_weighted(count: int, n: int, max_c: int, seed: int) -> list[Ratios]:
    rng = StdRng.seed_from_u64(seed)
    out = []
    for _ in range(count):
        inst = random_weighted_instance(rng, n, max_c)
        out.append(ratios_weighted(inst.items, inst.delta))
    return out


def density_counterexample(k: int) -> tuple[list[Weighted], int]:
    """`(c=1, w=0)`, `(c=K, w=K)`, `(c=1, w=2)` with `ΔC = 2`
    (`densityFirst_unbounded`): plain density pays `K` against 2."""
    assert k >= 2
    return [Weighted(1, 0.0), Weighted(k, float(k)), Weighted(1, 2.0)], 2

"""Probability laws of the scenarios: exact moments and sampling with rand's
`StdRng` (serQ's `Dist`, `engine/dist.rs`). `sim.laws` writes a law in
serQ's sampler."""

from __future__ import annotations

import math
from dataclasses import dataclass

from theory.rng import StdRng


class Dist:
    def mean(self) -> float:
        raise NotImplementedError

    def second_moment(self) -> float:
        raise NotImplementedError

    def variance(self) -> float:
        m = self.mean()
        return self.second_moment() - m * m

    def cv2(self) -> float:
        m = self.mean()
        return self.variance() / (m * m)

    def sample(self, rng: StdRng) -> float:
        raise NotImplementedError


def _sample_exp(rng: StdRng, mean: float) -> float:
    # 1 - U is in (0, 1], so the logarithm stays finite.
    return -mean * math.log(1.0 - rng.random_f64())


@dataclass(frozen=True)
class Deterministic(Dist):
    x: float

    def mean(self) -> float:
        return self.x

    def second_moment(self) -> float:
        return self.x * self.x

    def sample(self, rng: StdRng) -> float:
        return self.x


@dataclass(frozen=True)
class Exponential(Dist):
    mean_: float

    def mean(self) -> float:
        return self.mean_

    def second_moment(self) -> float:
        return 2.0 * self.mean_ * self.mean_

    def sample(self, rng: StdRng) -> float:
        return _sample_exp(rng, self.mean_)


@dataclass(frozen=True)
class Erlang(Dist):
    k: int
    mean_: float

    def mean(self) -> float:
        return self.mean_

    def second_moment(self) -> float:
        k = float(max(self.k, 1))
        return self.mean_ * self.mean_ * (1.0 + 1.0 / k)

    def sample(self, rng: StdRng) -> float:
        k = max(self.k, 1)
        phase = self.mean_ / k
        acc = 0.0
        for _ in range(k):
            acc += _sample_exp(rng, phase)
        return acc


@dataclass(frozen=True)
class HyperExp(Dist):
    p: float
    mean1: float
    mean2: float

    def mean(self) -> float:
        return self.p * self.mean1 + (1.0 - self.p) * self.mean2

    def second_moment(self) -> float:
        return 2.0 * (self.p * self.mean1 * self.mean1 + (1.0 - self.p) * self.mean2 * self.mean2)

    def sample(self, rng: StdRng) -> float:
        mean = self.mean1 if rng.random_f64() < self.p else self.mean2
        return _sample_exp(rng, mean)


@dataclass(frozen=True)
class Uniform(Dist):
    lo: float
    hi: float

    def mean(self) -> float:
        return 0.5 * (self.lo + self.hi)

    def second_moment(self) -> float:
        lo, hi = self.lo, self.hi
        return (lo * lo + lo * hi + hi * hi) / 3.0

    def sample(self, rng: StdRng) -> float:
        return self.lo + (self.hi - self.lo) * rng.random_f64()


@dataclass(frozen=True)
class Discrete(Dist):
    values: tuple[float, ...]
    probs: tuple[float, ...]

    def mean(self) -> float:
        acc = 0.0
        for v, p in zip(self.values, self.probs, strict=True):
            acc += p * v
        return acc

    def second_moment(self) -> float:
        acc = 0.0
        for v, p in zip(self.values, self.probs, strict=True):
            acc += p * v * v
        return acc

    def sample(self, rng: StdRng) -> float:
        u = rng.random_f64()
        acc = 0.0
        for v, p in zip(self.values, self.probs, strict=True):
            acc += p
            if u < acc:
                return v
        return self.values[-1]


@dataclass(frozen=True)
class HitMiss(Dist):
    p_hit: float
    hit: float
    miss: float

    def mean(self) -> float:
        return self.p_hit * self.hit + (1.0 - self.p_hit) * self.miss

    def second_moment(self) -> float:
        return self.p_hit * self.hit * self.hit + (1.0 - self.p_hit) * self.miss * self.miss

    def sample(self, rng: StdRng) -> float:
        return self.hit if rng.random_f64() < self.p_hit else self.miss


@dataclass(frozen=True)
class Bernoulli(Dist):
    p: float

    def mean(self) -> float:
        return self.p

    def second_moment(self) -> float:
        return self.p

    def sample(self, rng: StdRng) -> float:
        return 1.0 if rng.random_f64() < self.p else 0.0


def exp(mean: float) -> Exponential:
    return Exponential(mean)


def hyperexp_balanced(mean: float, cv2: float) -> HyperExp:
    """Two-phase balanced hyperexponential with the requested mean and CV²."""
    assert cv2 >= 1.0, f"hyperexponential needs CV² ≥ 1, got {cv2}"
    p = 0.5 * (1.0 + math.sqrt((cv2 - 1.0) / (cv2 + 1.0)))
    return HyperExp(p, mean / (2.0 * p), mean / (2.0 * (1.0 - p)))


def discrete(values, probs) -> Discrete:
    values, probs = tuple(map(float, values)), tuple(map(float, probs))
    assert len(values) == len(probs) and values
    total = 0.0
    for p in probs:
        total += p
    assert abs(total - 1.0) < 1e-9, f"probabilities sum to {total}"
    assert all(p >= 0.0 for p in probs)
    return Discrete(values, probs)

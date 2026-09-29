"""Output analysis: running moments, batch-means and replication intervals."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .fmt import div, fixed, ssum


class Welford:
    """Running mean and variance (Welford); also the raw second moment,
    which is what the PK formula consumes. Built from a sample sequence it
    is computed on first use, in the sequence's order."""

    def __init__(self, xs=None):
        self._xs = xs
        self._n = 0
        self._mean = 0.0
        self._m2 = 0.0

    def _force(self) -> None:
        if self._xs is not None:
            xs, self._xs = self._xs, None
            for x in np.asarray(xs, dtype=np.float64).tolist():
                self.push(x)

    def push(self, x: float) -> None:
        self._force()
        self._n += 1
        d = x - self._mean
        self._mean += d / self._n
        self._m2 += d * (x - self._mean)

    def n(self) -> int:
        self._force()
        return self._n

    def mean(self) -> float:
        self._force()
        return self._mean

    def variance(self) -> float:
        """Population variance `E[(X - E X)^2]`."""
        self._force()
        return 0.0 if self._n == 0 else self._m2 / self._n

    def second_moment(self) -> float:
        m = self.mean()
        return self.variance() + m * m

    def cv2(self) -> float:
        m = self.mean()
        return div(self.variance(), m * m)


@dataclass(frozen=True)
class Estimate:
    """A point estimate with a 95 % confidence half-width."""

    mean: float
    half_width: float

    def lo(self) -> float:
        return self.mean - self.half_width

    def hi(self) -> float:
        return self.mean + self.half_width

    def agrees_with(self, x: float, rel: float) -> bool:
        """Does the interval, widened by a relative slack `rel`, contain `x`?"""
        slack = rel * abs(x)
        return self.lo() - slack <= x and x <= self.hi() + slack

    def relative_error(self, x: float) -> float:
        return abs(self.mean - x) / abs(x)

    def __str__(self) -> str:
        return f"{fixed(self.mean, 4)} ± {fixed(self.half_width, 4)}"


NAN_ESTIMATE = Estimate(math.nan, math.inf)

_T = [
    12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179, 2.160,
    2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056,
    2.052, 2.048, 2.045, 2.042,
]  # fmt: skip


def t975(df: int) -> float:
    """Two-sided 97.5 % Student-t quantile."""
    if df == 0:
        return math.inf
    if df <= 30:
        return _T[df - 1]
    if df <= 60:
        return 2.000
    if df <= 120:
        return 1.980
    return 1.960


def _interval(means: list[float]) -> Estimate:
    k = float(len(means))
    m = ssum(means) / k
    var = ssum([(x - m) * (x - m) for x in means]) / (k - 1.0)
    return Estimate(m, t975(len(means) - 1) * math.sqrt(var / k))


def batch_means(xs, batches: int) -> Estimate:
    """Batch-means estimate of the steady-state mean of a (possibly
    autocorrelated) output sequence, split into `batches` contiguous batches."""
    assert batches >= 2, "need at least two batches"
    a = np.asarray(xs, dtype=np.float64)
    size = a.size // batches
    assert size >= 1, f"{a.size} observations < {batches} batches"
    sums = np.cumsum(a[: batches * size].reshape(batches, size), axis=1)[:, -1]
    return _interval([s / size for s in sums.tolist()])


def replications(xs) -> Estimate:
    """Mean and 95 % half-width across independent replications."""
    xs = [float(x) for x in xs]
    assert len(xs) >= 2, "need at least two replications"
    return _interval(xs)


def quantile(xs, q: float) -> float:
    """Empirical quantile (nearest rank) of an unsorted sequence."""
    v = np.sort(np.asarray(xs, dtype=np.float64))
    assert v.size
    idx = min(max(math.ceil(q * v.size), 1), v.size) - 1
    return float(v[idx])

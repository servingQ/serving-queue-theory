"""Run serQ programs in process with pyserq and read their reports.

`scripts/fetch_serq.sh` (`make serq`) checks out the release pinned in
`validation/pyproject.toml` into `.serq/src`, whose `examples/` hold the
general programs (`mg1`, `ps`, `closed`, `pd_tandem`, `pd_open`, `routing`,
...) and whose `pyserq/` is the binding `uv sync` builds. A run is
`pyserq.compile` then `pyserq.run`, whose report has the fields of
`serq run --json` by name. This module adds only what pyserq lacks: an
observation's samples as numpy arrays.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from functools import cached_property
from pathlib import Path

import numpy as np
import pyserq

REPO = Path(__file__).resolve().parents[3]
PROGRAMS = REPO / "programs"
DATA = REPO / "validation" / "data"
SERQ_HOME = Path(os.environ.get("SERQ_HOME", REPO / ".serq"))
EXAMPLES = SERQ_HOME / "src" / "examples"


class SerqError(RuntimeError):
    pass


def program_path(name: str) -> Path:
    """`examples/<group>/<name>.sq` of the pinned serQ checkout."""
    hits = sorted(EXAMPLES.glob(f"*/{name}.sq"))
    if not hits:
        raise FileNotFoundError(f"no {EXAMPLES}/*/{name}.sq (run `make serq`)")
    return hits[0]


class Observe:
    """pyserq's `Observe`, its samples read once, as numpy arrays."""

    def __init__(self, o: pyserq.Observe):
        self._o = o

    def __getattr__(self, name: str):
        return getattr(self._o, name)

    @cached_property
    def samples(self) -> np.ndarray:
        return np.asarray(self._o.samples, dtype=np.float64)

    @cached_property
    def times(self) -> np.ndarray:
        return np.asarray(self._o.times, dtype=np.float64)

    @cached_property
    def sessions(self) -> np.ndarray:
        return np.asarray(self._o.sessions, dtype=np.int64)

    @cached_property
    def turns(self) -> np.ndarray:
        return np.asarray(self._o.turns, dtype=np.int64)


class Report:
    """pyserq's `Report`, its observations as `Observe`."""

    def __init__(self, r: pyserq.Report):
        self._r = r

    def __getattr__(self, name: str):
        return getattr(self._r, name)

    @cached_property
    def observes(self) -> dict[str, Observe]:
        return {name: Observe(o) for name, o in self._r.observes.items()}

    def observe(self, name: str) -> Observe | None:
        return self.observes.get(name)


def run(
    path: Path | str | None = None,
    *,
    source: str | None = None,
    sets: dict[str, object] | None = None,
    defs: dict[str, str] | None = None,
    seed: int | None = None,
    horizon: float | None = None,
    warmup: float | None = None,
    arrivals: int | None = None,
    trace: str | Path | None = None,
) -> Report:
    """Run a program file, or program text (`source`), with `--set`
    overrides (a numeric override is that number; a string is an
    expression) and `--def` bodies of its expression definitions."""
    try:
        program = pyserq.compile(
            path,
            source=source,
            sets=sets or {},
            defs=defs or {},
            seed=seed,
            horizon=None if horizon is None else float(horizon),
            warmup=None if warmup is None else float(warmup),
            arrivals=arrivals,
            trace=None if trace is None else str(trace),
        )
        r = pyserq.run(program)
    except ValueError as e:
        raise SerqError(str(e)) from None
    return Report(r)


_POOL = ThreadPoolExecutor(max_workers=max(1, os.cpu_count() or 1))


def parallel(fn, items):
    """`[fn(x) for x in items]`, run concurrently (each serQ run is
    independent and deterministic, and releases the GIL, so the results do
    not depend on the worker count)."""
    return list(_POOL.map(fn, items))

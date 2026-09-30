"""Run serQ programs in process with pyserq and read their reports.

`scripts/fetch_serq.sh` (`make serq`) checks out the release pinned in
`validation/pyproject.toml` into `.serq/src`, whose `examples/` hold the
general programs (`mg1`, `ps`, `closed`, `pd_tandem`, `pd_open`, `routing`,
...) and whose `pyserq/` is the binding `uv sync` builds. A run is
`pyserq.compile` then `pyserq.run`: the report's JSON gives the observe
statistics, stages and pools, and each observation's samples are read from
the run itself, only when a caller asks for them.
"""

from __future__ import annotations

import json
import math
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyserq

REPO = Path(__file__).resolve().parents[2]
PROGRAMS = REPO / "programs"
DATA = REPO / "validation" / "data"
SERQ_HOME = Path(os.environ.get("SERQ_HOME", REPO / ".serq"))
EXAMPLES = SERQ_HOME / "src" / "examples"


class SerqError(RuntimeError):
    pass


def program_path(name: str) -> Path:
    """`examples/<group>/<name>.serq` of the pinned serQ checkout."""
    hits = sorted(EXAMPLES.glob(f"*/{name}.sq"))
    if not hits:
        raise FileNotFoundError(f"no {EXAMPLES}/*/{name}.sq (run `make serq`)")
    return hits[0]


def _num(x) -> float:
    return math.nan if x is None else float(x)


@dataclass
class Observe:
    name: str
    count: int
    mean: float
    ci: float  # batch-means 95 % half-width (NaN below 40 samples)
    cv2: float
    p99: float
    _run: object | None = field(default=None, repr=False)
    _data: np.ndarray | None = field(default=None, repr=False)

    def _load(self) -> np.ndarray:
        """`time, session, turn, value` per sample, as `serq run --dump` writes them."""
        if self._data is None:
            if self._run is None:
                self._data = np.zeros((0, 4))
            else:
                values, times, sessions, turns = self._run.observe(self.name)
                self._data = np.column_stack(
                    [
                        np.asarray(times, dtype=np.float64),
                        np.asarray(sessions, dtype=np.float64),
                        np.asarray(turns, dtype=np.float64),
                        np.asarray(values, dtype=np.float64),
                    ]
                ).reshape(-1, 4)
        return self._data

    @property
    def samples(self) -> np.ndarray:
        return self._load()[:, 3]

    @property
    def times(self) -> np.ndarray:
        return self._load()[:, 0]

    @property
    def sessions(self) -> np.ndarray:
        return self._load()[:, 1].astype(np.int64)

    @property
    def turns(self) -> np.ndarray:
        return self._load()[:, 2].astype(np.int64)


@dataclass
class Stage:
    name: str
    mean_number: float
    utilization: float
    completed: int
    throughput: float
    mean_wait: float
    mean_service: float
    iterations: int


@dataclass
class Pool:
    name: str
    mean_used: float
    mean_cached: float
    mean_queue: float
    mean_holders: float
    mean_wait: float
    admissions: int
    evicted_entries: int
    evicted_units: float
    preemptions: int
    spills: int
    rejected: int
    stuck: int


class Report:
    """What a run reports (serQ `engine/report.rs`)."""

    def __init__(self, js: dict, run: object | None):
        for k in ("horizon", "end", "warmup", "mean_live"):
            setattr(self, k, _num(js[k]))
        for k in ("seed", "events", "arrivals", "ended", "turns"):
            setattr(self, k, int(js[k]))
        self.observes = {
            name: Observe(
                name,
                int(o["count"]),
                _num(o["mean"]),
                _num(o["ci"]),
                _num(o["cv2"]),
                _num(o["p99"]),
                run,
            )
            for name, o in js["observes"].items()
        }
        self.stages = [
            Stage(
                **{k: (_num(v) if isinstance(v, float) or v is None else v) for k, v in s.items()}
            )
            for s in js["stages"]
        ]
        self.pools = [
            Pool(**{k: (_num(v) if isinstance(v, float) or v is None else v) for k, v in p.items()})
            for p in js["pools"]
        ]

    def observe(self, name: str) -> Observe | None:
        return self.observes.get(name)

    def stage(self, name: str) -> Stage | None:
        return next((s for s in self.stages if s.name == name), None)

    def stages_named(self, name: str) -> list[Stage]:
        return [s for s in self.stages if s.name == name]

    def pool(self, name: str) -> Pool | None:
        return next((p for p in self.pools if p.name == name), None)


def _set_value(v: object) -> str | float:
    """A number as itself, except an infinity, which pyserq's numbers refuse
    and serQ spells `inf`; a string is an expression."""
    if isinstance(v, str):
        return v
    x = float(v)
    if math.isinf(x):
        return "inf" if x > 0 else "-inf"
    return x


def run(
    path: Path | str | None = None,
    *,
    source: str | None = None,
    sets: dict[str, object] | None = None,
    seed: int | None = None,
    horizon: float | None = None,
    warmup: float | None = None,
    arrivals: int | None = None,
    trace: str | Path | None = None,
    dump: bool = True,
) -> Report:
    """Run a program file, or program text (`source`), with `--set`
    overrides. A numeric override is that number; a string is an
    expression. With `dump`, each observation's samples can be read."""
    try:
        program = pyserq.compile(
            path,
            source=source,
            sets={k: _set_value(v) for k, v in (sets or {}).items()},
            seed=seed,
            horizon=None if horizon is None else float(horizon),
            warmup=None if warmup is None else float(warmup),
            arrivals=arrivals,
            trace=None if trace is None else str(trace),
        )
        r = pyserq.run(program)
    except ValueError as e:
        raise SerqError(str(e)) from None
    return Report(json.loads(r.json()), r if dump else None)


_POOL = ThreadPoolExecutor(max_workers=max(1, os.cpu_count() or 1))


def parallel(fn, items):
    """`[fn(x) for x in items]`, run concurrently (each serQ run is
    independent and deterministic, and releases the GIL, so the results do
    not depend on the worker count)."""
    return list(_POOL.map(fn, items))


def have_serq() -> bool:
    """pyserq reads the IR of the pinned release."""
    return pyserq.IR_VERSION >= 1

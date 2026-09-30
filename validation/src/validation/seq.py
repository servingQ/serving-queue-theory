"""Run seQ programs with the pinned CLI and read their reports.

`scripts/fetch_seq.sh` (`make seq`) installs the release pinned in
`validation/pyproject.toml` into `.seq/`: the CLI `.seq/bin/serq` and the
source checkout `.seq/src`, whose `examples/` hold the general programs
(`mg1`, `ps`, `closed`, `pd_tandem`, `pd_open`, `routing`, ...). A run is
`serq run FILE --json --dump DIR`: the JSON summary gives the observe
statistics, stages and pools; the dump gives every observation as
`time,session,turn,value`, loaded only when a caller asks for samples.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .fmt import number

REPO = Path(__file__).resolve().parents[3]
PROGRAMS = REPO / "programs"
DATA = REPO / "validation" / "data"
SEQ_HOME = Path(os.environ.get("SEQ_HOME", REPO / ".seq"))
SEQ_BIN = Path(os.environ.get("SEQ_LANG", SEQ_HOME / "bin" / "serq"))
EXAMPLES = SEQ_HOME / "src" / "examples"


class SeqError(RuntimeError):
    pass


def program_path(name: str) -> Path:
    """`examples/<group>/<name>.sq` of the pinned serQ checkout."""
    hits = sorted(EXAMPLES.glob(f"*/{name}.sq"))
    if not hits:
        raise FileNotFoundError(f"no {EXAMPLES}/*/{name}.sq (run `make seq`)")
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
    _file: Path | None = field(default=None, repr=False)
    _data: np.ndarray | None = field(default=None, repr=False)

    def _load(self) -> np.ndarray:
        if self._data is None:
            if self._file is None or not self._file.exists():
                self._data = np.zeros((0, 4))
            else:
                a = np.loadtxt(self._file, delimiter=",", skiprows=1, ndmin=2, dtype=np.float64)
                self._data = a.reshape(-1, 4)
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
    """What a run reports (seQ `engine/report.rs`)."""

    def __init__(self, js: dict, dump: Path | None, tmp: tempfile.TemporaryDirectory | None):
        self._tmp = tmp  # keeps the dump alive as long as the report
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
                (dump / f"{name}.csv") if dump else None,
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
    overrides. A numeric override is written so that seQ parses exactly the
    same `f64`; a string is passed as the expression itself."""
    if not SEQ_BIN.exists():
        raise SeqError(f"{SEQ_BIN} not found: run `make seq`")
    tmp = tempfile.TemporaryDirectory(prefix="seq-run-")
    tdir = Path(tmp.name)
    if source is not None:
        path = tdir / "program.seq"
        path.write_text(source)
    args = [str(SEQ_BIN), "run", str(path), "--json"]
    if seed is not None:
        args += ["--seed", str(seed)]
    if horizon is not None:
        args += ["--horizon", number(horizon)]
    if warmup is not None:
        args += ["--warmup", number(warmup)]
    if arrivals is not None:
        args += ["--arrivals", str(arrivals)]
    if trace is not None:
        args += ["--trace", str(trace)]
    for k, v in (sets or {}).items():
        args += ["--set", f"{k}={v if isinstance(v, str) else number(float(v))}"]
    ddir = tdir / "dump" if dump else None
    if ddir is not None:
        args += ["--dump", str(ddir)]
    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode != 0:
        tmp.cleanup()
        raise SeqError((p.stderr or p.stdout).strip())
    return Report(json.loads(p.stdout), ddir, tmp)


_POOL = ThreadPoolExecutor(max_workers=max(1, os.cpu_count() or 1))


def parallel(fn, items):
    """`[fn(x) for x in items]`, run concurrently (each seQ run is an
    independent, deterministic process, so the results do not depend on
    the worker count)."""
    return list(_POOL.map(fn, items))


def have_seq() -> bool:
    return SEQ_BIN.exists() and shutil.which(str(SEQ_BIN)) is not None

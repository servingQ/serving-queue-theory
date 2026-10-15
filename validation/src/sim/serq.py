"""Run serQ programs in process with pyserq and read their reports.

`scripts/fetch_serq.sh` (`make serq`) checks out the release pinned in
`validation/pyproject.toml` into `.serq/src` for oracle vectors and the CLI.
Configurable queueing models live in `programs/models/`, derived from that
release's examples, with explicit `args.number` inputs. pyserq, from PyPI,
is the same release. A program is a deployment, and its workload a file of
its own given when it runs (serQ v0.1.6, `docs/design/paired-workload.md`):
`programs/pairs.json` maps each deployment here to its workload, as serQ's
`examples/pairs.json` does its examples. A run is
`pyserq.compile` then `pyserq.run`, whose report has the fields of
`serq run --json` by name. This module adds only what pyserq lacks: an
observation's samples as numpy arrays.
"""

from __future__ import annotations

import json
import os
import re
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


def workload_path(path: Path | str) -> Path:
    """The workload a deployment of this repository runs (`programs/pairs.json`)."""
    key = str(Path(path).resolve().relative_to(REPO))
    pairs = json.loads((PROGRAMS / "pairs.json").read_text())
    if key not in pairs:
        raise KeyError(f"no workload for {key} in programs/pairs.json")
    return REPO / pairs[key]


def program_path(name: str) -> Path:
    """Configurable SQT model derived from the pinned release's example."""
    path = PROGRAMS / "models" / f"{name}.sq"
    if not path.exists():
        raise FileNotFoundError(f"no SQT model {path}")
    return path


def execution(path: Path | str) -> dict[str, int | float]:
    """Explicitly select the recorded execution conditions for a model."""
    key = str(Path(path).resolve().relative_to(REPO))
    return json.loads((PROGRAMS / "executions.json").read_text())[key]


def _splice_def(text: str, name: str, body: str) -> str | None:
    """`text` with the body of its `def name() { … }` replaced by `body`, or
    None when `text` declares no such def."""
    m = re.search(rf"\bdef\s+{re.escape(name)}\s*\(\s*\)\s*\{{", text)
    if m is None:
        return None
    depth, i = 1, m.end()
    while depth:
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
    return f"{text[: m.end()]} {body} }}{text[i:]}"


def _inline_defs(deployment: str, workload: str, defs: dict[str, str]) -> tuple[str, str]:
    """STOPGAP for serQ v0.1.6: in a paired program a `--def` body (pyserq
    `defs=`) cannot read its file's constants (`let`s): the pair renames each
    file's names apart (`d·a`, `w·Z`) and the body given on the command line
    is not renamed, so `--def evict_key='a * size'` fails to link with
    "unknown name `a`". Splicing the bodies into the text, as the adapters
    did before serQ had `--def`, gives the IR the defs would; drop this when
    serQ renames a `--def` body with its def's file."""
    for name, body in defs.items():
        d = _splice_def(deployment, name, body)
        w = _splice_def(workload, name, body) if d is None else None
        if d is None and w is None:
            raise SerqError(f"no `def {name}()` in the deployment or its workload")
        deployment, workload = d or deployment, w or workload
    return deployment, workload


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
    workload: Path | str | None = None,
    workload_source: str | None = None,
    sets: dict[str, object] | None = None,
    defs: dict[str, str] | None = None,
    seed: int | None = None,
    horizon: float | None = None,
    warmup: float | None = None,
    arrivals: int | None = None,
    trace: str | Path | None = None,
) -> Report:
    """Run a deployment file, or deployment text (`source`), under a workload
    file (`workload`) or workload text (`workload_source`), with declared
    `args.number` inputs (a numeric input is that number; a string is an
    expression) and `--def` bodies of its expression definitions. A file of
    this repository with neither runs the workload `programs/pairs.json`
    gives it."""
    if workload is None and workload_source is None:
        if path is None:
            raise ValueError("deployment text needs `workload` or `workload_source`")
        workload = workload_path(path)
    if defs:
        source, workload_source = _inline_defs(
            source if source is not None else Path(path).read_text(),
            workload_source if workload_source is not None else Path(workload).read_text(),
            defs,
        )
        path, workload, defs = None, None, {}
    try:
        program = pyserq.compile(
            None if path is None else str(path),
            source=source,
            workload=None if workload is None else str(workload),
            workload_source=workload_source,
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

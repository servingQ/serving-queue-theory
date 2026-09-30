"""WEKA trace inputs and summaries for the paper's scenarios.

The bundled WEKA corpus holds 183 production Claude Code sessions, exported
from `semianalysisai/cc-traces-weka-061326` by
`scripts/trace_stats_weka.py --export-csv`. It includes main-agent requests,
measures `new` as tokens beyond the longest earlier prefix in a session, and
splits sessions at gaps over ten minutes. The CSV format and its parser are
serQ's (`ir/trace.rs`, `pyserq.read_trace`): a session is a list of turns
`(new, out, think, forced)`.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import pyserq

from fmt import ssum
from sim.serq import DATA


@dataclass
class TraceCorpus:
    sessions: list[list[tuple[float, float, float, float]]]

    @classmethod
    def load(cls, path: Path) -> TraceCorpus:
        return cls(pyserq.read_trace(path))

    def turns(self) -> int:
        return sum(len(s) for s in self.sessions)

    def mean_turns(self) -> float:
        return self.turns() / len(self.sessions)

    def mean_think(self) -> float:
        total, count = 0.0, 0
        for s in self.sessions:
            n = max(len(s) - 1, 0)
            total += ssum([think for _, _, think, _ in s[:n]])
            count += n
        return total / max(count, 1)

    def resume_fraction(self) -> float:
        n = float(self.turns())
        return (n - len(self.sessions)) / n

    def mean_final_context(self) -> float:
        total = ssum([ssum([new + out for new, out, _, _ in s]) for s in self.sessions])
        return total / len(self.sessions)


WEKA = DATA / "weka-sessions.csv"
WEKA_30MIN = DATA / "weka-sessions-1800.csv"


@cache
def weka() -> TraceCorpus:
    return TraceCorpus.load(WEKA)


@cache
def weka_split_30min() -> TraceCorpus:
    return TraceCorpus.load(WEKA_30MIN)

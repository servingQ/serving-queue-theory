"""WEKA trace inputs and summaries for the paper's scenarios.

The bundled WEKA corpus holds 183 production Claude Code sessions, exported
from `semianalysisai/cc-traces-weka-061326` by
`scripts/trace_stats_weka.py --export-csv`. It includes main-agent requests,
measures `new` as tokens beyond the longest earlier prefix in a session, and
splits sessions at gaps over ten minutes. The CSV format and its parser are
serQ's (`ir/trace.rs`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from fmt import ssum
from sim.serq import DATA


@dataclass(frozen=True)
class Turn:
    new: float
    out: float
    think: float
    forced: float = 0.0


@dataclass
class TraceSession:
    turns: list[Turn] = field(default_factory=list)


@dataclass
class TraceCorpus:
    sessions: list[TraceSession]

    @classmethod
    def from_csv(cls, text: str) -> TraceCorpus:
        sessions: list[TraceSession] = []
        last = None
        for ln, line in enumerate(text.splitlines()):
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("session"):
                continue
            f = line.split(",")
            if len(f) not in (5, 6):
                raise ValueError(f"line {ln + 1}: expected 5 or 6 fields, got {len(f)}")
            sid = int(float(f[0]))
            if last != sid:
                sessions.append(TraceSession())
                last = sid
            sessions[-1].turns.append(
                Turn(float(f[2]), float(f[3]), float(f[4]), float(f[5]) if len(f) == 6 else 0.0)
            )
        if not sessions:
            raise ValueError("empty trace")
        return cls(sessions)

    @classmethod
    def load(cls, path: Path) -> TraceCorpus:
        return cls.from_csv(path.read_text())

    def turns(self) -> int:
        return sum(len(s.turns) for s in self.sessions)

    def mean_turns(self) -> float:
        return self.turns() / len(self.sessions)

    def mean_think(self) -> float:
        total, count = 0.0, 0
        for s in self.sessions:
            n = max(len(s.turns) - 1, 0)
            total += ssum([t.think for t in s.turns[:n]])
            count += n
        return total / max(count, 1)

    def resume_fraction(self) -> float:
        n = float(self.turns())
        return (n - len(self.sessions)) / n

    def mean_final_context(self) -> float:
        total = ssum([ssum([t.new + t.out for t in s.turns]) for s in self.sessions])
        return total / len(self.sessions)


WEKA = DATA / "weka-sessions.csv"
WEKA_30MIN = DATA / "weka-sessions-1800.csv"


@cache
def weka() -> TraceCorpus:
    return TraceCorpus.load(WEKA)


@cache
def weka_split_30min() -> TraceCorpus:
    return TraceCorpus.load(WEKA_30MIN)

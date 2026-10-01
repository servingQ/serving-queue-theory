"""Colocated vs split engines on the same requests (serQ #208, issue #28).

Two programs of the pinned serQ release, `examples/pd-disaggregation/`:

* `pd_ps.sq`, the processor-sharing idealisation: each of `N` colocated
  engines gives its decodes the fraction `f` of its time and takes a
  random `N`-th of the requests; split, `N f` decode engines serve all of
  them as one station of capacity `N f`. The split is the colocated
  station with the arrival rate and the capacity multiplied by `N`
  (`DecodeScaling.lean`).
* `pd_batching.sq`, the step engines: `N` colocated engines, or `NP`
  prefill and `N - NP` decode engines with a free hand-over, vLLM's
  admission and KV rules without a prefix cache. The baseline is exclusive
  prefill steps, memory that never binds, a free transfer, no
  specialisation; a variation is a `--set` (`omega`, `chunk_cap`, `Bw`,
  `x0`, `blocksD`, `blocksE`, `gP`) or one of two lines of the program
  (`serve exclusive prefill;` deleted, `let NP = 3;`), which the adapter
  edits in the text it compiles, as serQ's `tools/pd_batching/sweep.py`
  does.

Both modes of a program draw the same requests from a seed. Every result
is a simulation of the programs, not a measurement of a serving system.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from fmt import fmax
from sim import serq

MIN_POSITIVE = 2.2250738585072014e-308

EXCLUSIVE_LINE = "    serve exclusive prefill;\n"
NP_LINE = "let NP = 3;"


def stable(ended: int, rate: float, span: float) -> bool:
    """Did the run keep up with its arrivals: the requests ended after
    warm-up within four Poisson deviations of what the rate brings in that
    span. A run that falls behind fails this; one that is merely far from
    steady state near saturation may not."""
    expected = rate * span
    return ended >= expected - 4.0 * math.sqrt(expected)


def token_weighted_tpot(r: serq.Report) -> float:
    """All decode time over all inter-token gaps, the requests paired by
    (session, turn)."""
    dec, out = r.observe("decode_time"), r.observe("output_tokens")
    assert dec is not None and out is not None
    assert np.array_equal(dec.sessions, out.sessions) and np.array_equal(dec.turns, out.turns)
    gaps = float(np.sum(out.samples - 1.0))
    return float(np.sum(dec.samples)) / fmax(gaps, MIN_POSITIVE)


# ------------------------------------------------------------ pd_ps.sq --


@dataclass(frozen=True)
class PsConfig:
    """`pd_ps.sq`: the program's `N = 4` colocated engines at a decode
    share `share`, or the pooled station of capacity `N * share`, at `rate`
    requests per second (`N` sizes the station array, which a `--set`
    cannot change)."""

    split: bool
    rate: float
    seed: int
    share: float = 0.25
    horizon: float = 300.0
    warmup: float = 30.0


@dataclass
class PsReport:
    stable: bool
    decoding_per_station: float  # time-average number decoding at one station
    decode_time: float  # mean sojourn (s)
    tpot_request: float  # mean over requests of (last - first) / (o - 1)
    tpot_token: float  # all decode time over all gaps
    output_tokens_per_s: float


def simulate_ps(cfg: PsConfig) -> PsReport:
    r = serq.run(
        serq.program_path("pd_ps"),
        sets={"mode": 1.0 if cfg.split else 0.0, "Lambda": cfg.rate, "f": cfg.share},
        seed=cfg.seed,
        horizon=cfg.horizon,
        warmup=cfg.warmup,
    )  # fmt: skip
    span = r.end - r.warmup
    stations = r.stages_named("dec" if cfg.split else "colo")
    out = r.observe("output_tokens")
    return PsReport(
        stable(r.ended, cfg.rate, span),
        float(np.mean([s.mean_number for s in stations])),
        r.observe("decode_time").mean,
        r.observe("tpot").mean,
        token_weighted_tpot(r),
        float(np.sum(out.samples)) / span,
    )


# ------------------------------------------------------ pd_batching.sq --


@dataclass(frozen=True)
class StepConfig:
    """`pd_batching.sq`: 4 colocated engines or `prefill_engines` prefill
    + the rest decode, at `rate` requests per second; `prompt_len` and
    `output` are the laws' bodies (serQ expressions); `sets` the program's
    constants; `exclusive` keeps or deletes `serve exclusive prefill;`."""

    split: bool
    rate: float
    seed: int
    prompt_len: str = "2000"
    output: str | None = None
    sets: dict[str, float] = field(default_factory=dict)
    exclusive: bool = True
    prefill_engines: int = 3
    horizon: float = 300.0
    warmup: float = 30.0


@dataclass
class StepReport:
    stable: bool
    requests_per_s: float
    output_tokens_per_s: float
    ttft: float
    response: float
    decode_time: float
    tpot_request: float
    tpot_token: float
    itl_p99: float  # the largest of the decoding engines'
    batch: float  # decodes of an iteration that carried any, on a decoding engine
    decoding: float  # time average of decodes in the running iteration, per decoding engine
    decode_step: float  # mean duration of an iteration that carried decodes (s)
    prefill_share: float  # of wall-clock time, on the engines that prefill
    decode_share: float  # of wall-clock time, on the engines that decode
    mixed_share: float  # on the engines that prefill
    idle_share: float  # on the engines that prefill
    admit_wait: float  # split: the decode engine's admission after the prefill (s)
    transfer: float  # split: the read, wait included (s)
    preemptions_per_s: float  # on the decoding engines
    prefill_kv_leased: float  # split: tokens the prefill engines hold, leased until read


def _program_text(cfg: StepConfig) -> str:
    text = serq.program_path("pd_batching").read_text()
    if not cfg.exclusive:
        assert text.count(EXCLUSIVE_LINE) == 2, "pd_batching.sq: two exclusive-step lines expected"
        text = text.replace(EXCLUSIVE_LINE, "")
    if cfg.prefill_engines != 3:
        assert text.count(NP_LINE) == 1
        text = text.replace(NP_LINE, f"let NP = {cfg.prefill_engines};")
    return text


def _mean(xs) -> float:
    xs = [x for x in xs if x is not None and not math.isnan(x)]
    return float(np.mean(xs)) if xs else math.nan


def simulate_step(cfg: StepConfig) -> StepReport:
    defs = {"prompt_len": cfg.prompt_len}
    if cfg.output is not None:
        defs["output"] = cfg.output
    r = serq.run(
        source=_program_text(cfg),
        sets={"mode": 1.0 if cfg.split else 0.0, "Lambda": cfg.rate, **cfg.sets},
        defs=defs,
        seed=cfg.seed,
        horizon=cfg.horizon,
        warmup=cfg.warmup,
    )
    span = r.end - r.warmup
    obs = r.observes
    prefilling = r.stages_named("P" if cfg.split else "E")
    decoding = r.stages_named("D" if cfg.split else "E")
    pre = _mean([s.prefill_only for s in prefilling])
    mix = _mean([s.mixed for s in prefilling])
    dec_on_prefilling = _mean([s.decode_only for s in prefilling])
    kv_pools = r.pools_named("D.kv" if cfg.split else "E.kv")

    def mean_obs(name: str) -> float:
        o = obs.get(name)
        return o.mean if o is not None and o.count else math.nan

    return StepReport(
        stable(r.ended, cfg.rate, span),
        r.ended / span,
        float(np.sum(obs["output_tokens"].samples)) / span,
        obs["ttft"].mean,
        obs["response"].mean,
        obs["decode_time"].mean,
        obs["tpot"].mean,
        token_weighted_tpot(r),
        max((s.itl_p99 for s in decoding if s.itl_p99 is not None), default=math.nan),
        _mean([s.mean_decode_batch for s in decoding]),
        _mean([s.mean_decodes for s in decoding]),
        _mean([s.mean_decode_step for s in decoding]),
        pre,
        _mean([s.decode_only + s.mixed for s in decoding]),
        mix,
        max(0.0, 1.0 - pre - mix - dec_on_prefilling),
        mean_obs("admit_wait"),
        mean_obs("transfer"),
        sum(p.preemptions for p in kv_pools) / span,
        sum(p.mean_used for p in r.pools_named("P.kv")) if cfg.split else 0.0,
    )

"""Colocated vs split engines on the same requests (serQ #208, issue #28).

Two programs in `programs/models/`, adapted from the pinned serQ
release's `examples/pd-disaggregation/` (`f` and `tok` of `pd_ps.sq`
made inputs):

* `pd_ps.sq`, the processor-sharing idealisation: each of `N = 4`
  colocated engines gives its decodes the fraction `f` of its time and
  takes a random `N`-th of the requests; split, `N f` decode engines serve
  all of them as one station of capacity `N f`. The split is the colocated
  station with the arrival rate and the capacity multiplied by `N`
  (`DecodeScaling.lean`).
* `pd_batching.sq`, the step engines: `N = 4` colocated engines, or `NP`
  prefill and `N - NP` decode engines with a free hand-over, vLLM's
  admission and KV rules without a prefix cache. The baseline is exclusive
  prefill steps, memory that never binds, a free transfer, no
  specialisation; a variation is a `--set` (`omega`, `chunk_cap`, `Bw`,
  `x0`, `blocksD`, `blocksE`, `gP`) or one of two lines of the program
  (`serve exclusive prefill;` deleted, `let NP = 3;`), which the adapter
  edits in the text it compiles, as serQ's `tools/pd_batching/sweep.py`
  does. The prompt law is the program's (`floor(~uniform(1000, 3000))`)
  unless `prompt_len` gives another, such as the sweep's `fixed` case
  `2000`.

Both modes of a program draw the same requests from a seed. A run is
`stable` only if it kept up with its arrivals and the engines that
prefill were not at saturation (their prefill share below 99 %; an engine
whose decodes never drain is busy all the time without being overloaded).
Every result is a simulation of the programs, not a measurement of a
serving system.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field

import numpy as np

from fmt import fold_max
from sim import serq

EXCLUSIVE_LINE = "      serve exclusive prefill;\n"
NP_LINE = "let NP = 3;"
ENGINES = 4  # `N` of both programs: the size of their station arrays, which a `--set` cannot change
SATURATED = 0.99  # a prefill capacity busy more than this share of the time is at saturation


def kept_up(ended: int, rate: float, span: float) -> bool:
    """Did the run keep up with its arrivals: the requests ended after
    warm-up within four Poisson deviations of what the rate brings in that
    span. A run that falls behind fails this; one near saturation may pass
    it and still be far from steady state, which `stable` catches by the
    prefill capacity's share."""
    expected = rate * span
    return ended >= expected - 4.0 * math.sqrt(expected)


def token_weighted_tpot(r: serq.Report) -> float:
    """All decode time over all inter-token gaps, the requests paired by
    (session, turn)."""
    dec, out = r.observe("decode_time"), r.observe("output_tokens")
    assert dec is not None and out is not None
    assert np.array_equal(dec.sessions, out.sessions) and np.array_equal(dec.turns, out.turns)
    gaps = float(np.sum(out.samples - 1.0))
    return float(np.sum(dec.samples)) / max(gaps, sys.float_info.min)


def _mean(xs) -> float:
    """The mean of the finite values, NaN if there is none (a share that
    was not measured must not read as zero)."""
    xs = [x for x in xs if x is not None and math.isfinite(x)]
    return float(np.mean(xs)) if xs else math.nan


def _max(xs) -> float:
    xs = [x for x in xs if x is not None and math.isfinite(x)]
    return fold_max(xs) if xs else math.nan


_RUNS: dict[tuple, object] = {}


def _memo(key: tuple, run):
    """The same configuration is run once; checks share runs."""
    if key not in _RUNS:
        _RUNS[key] = run()
    return _RUNS[key]


# ------------------------------------------------------------ pd_ps.sq --


@dataclass(frozen=True)
class PsConfig:
    """`pd_ps.sq`: the `ENGINES` colocated engines at a decode share
    `share`, or the pooled station of capacity `ENGINES * share`, at `rate`
    requests per second; `tok` seconds per decode token at a whole engine,
    output lengths `floor(exp(output_mean)) + 2`."""

    split: bool
    rate: float
    seed: int
    share: float = 0.25
    tok: float = 2e-4
    output_mean: float = 200.0
    horizon: float = 300.0
    warmup: float = 30.0

    def output_law(self) -> str:
        return f"floor(~exp({self.output_mean})) + 2"


@dataclass
class PsReport:
    stable: bool
    busy: float  # the busiest station's utilisation
    decoding_per_station: float  # time-average number decoding at one station
    decode_time: float  # mean sojourn (s)
    tpot_request: float  # mean over requests of (last - first) / (o - 1)
    tpot_token: float  # all decode time over all gaps
    output_tokens_per_s: float


def simulate_ps(cfg: PsConfig) -> PsReport:
    return _memo(("ps", cfg), lambda: _simulate_ps(cfg))


def _simulate_ps(cfg: PsConfig) -> PsReport:
    r = serq.run(
        serq.program_path("pd_ps"),
        sets={"mode": 1.0 if cfg.split else 0.0, "Lambda": cfg.rate, "f": cfg.share, "tok": cfg.tok},
        defs={"output": cfg.output_law()},
        seed=cfg.seed,
        horizon=cfg.horizon,
        warmup=cfg.warmup,
    )  # fmt: skip
    span = r.end - r.warmup
    stations = r.stages_named("dec" if cfg.split else "colo")
    busy = _max(s.utilization for s in stations)
    out = r.observe("output_tokens")
    return PsReport(
        kept_up(r.ended, cfg.rate, span) and busy < SATURATED,
        busy,
        _mean(s.mean_number for s in stations),
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
    `output` replace the laws' bodies (serQ expressions) when given;
    `sets` the program's constants; `exclusive` keeps or deletes
    `serve exclusive prefill;`."""

    split: bool
    rate: float
    seed: int
    prompt_len: str | None = None
    output: str | None = None
    sets: dict[str, float] = field(default_factory=dict)
    exclusive: bool = True
    prefill_engines: int = 3
    horizon: float = 300.0
    warmup: float = 30.0

    def key(self) -> tuple:
        return (
            "step", self.split, self.rate, self.seed, self.prompt_len, self.output,
            tuple(sorted(self.sets.items())), self.exclusive, self.prefill_engines,
            self.horizon, self.warmup,
        )  # fmt: skip


@dataclass
class StepReport:
    stable: bool
    prefill_busy: float  # the busiest prefilling engine's share of time with a prefill in the step
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
    idle_share: float  # on the engines that prefill (NaN when a share was not measured)
    admit_wait: float  # split: the decode engine's admission after the prefill (s)
    transfer: float  # split: the read, wait included (s)
    preemptions_per_s: float  # on the decoding engines
    prefill_kv_used: float  # split: tokens the prefill engines hold, running prefills and leases awaiting the read


def _program_text(cfg: StepConfig) -> str:
    text = serq.program_path("pd_batching").read_text()
    if not cfg.exclusive:
        assert text.count(EXCLUSIVE_LINE) == 2, "pd_batching.sq: two exclusive-step lines expected"
        text = text.replace(EXCLUSIVE_LINE, "")
    if cfg.prefill_engines != 3:
        assert text.count(NP_LINE) == 1
        text = text.replace(NP_LINE, f"let NP = {cfg.prefill_engines};")
    return text


def simulate_step(cfg: StepConfig) -> StepReport:
    return _memo(cfg.key(), lambda: _simulate_step(cfg))


def _simulate_step(cfg: StepConfig) -> StepReport:
    defs = {}
    if cfg.prompt_len is not None:
        defs["prompt_len"] = cfg.prompt_len
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
    prefill_busy = _max(s.prefill_only + s.mixed for s in prefilling)
    pre = _mean(s.prefill_only for s in prefilling)
    mix = _mean(s.mixed for s in prefilling)
    dec_on_prefilling = _mean(s.decode_only for s in prefilling)
    idle = 1.0 - pre - mix - dec_on_prefilling  # NaN if a share was not measured
    kv_pools = r.pools_named("D.kv" if cfg.split else "E.kv")

    def mean_obs(name: str) -> float:
        o = obs.get(name)
        return o.mean if o is not None and o.count else math.nan

    return StepReport(
        kept_up(r.ended, cfg.rate, span) and prefill_busy < SATURATED,
        prefill_busy,
        r.ended / span,
        float(np.sum(obs["output_tokens"].samples)) / span,
        obs["ttft"].mean,
        obs["response"].mean,
        obs["decode_time"].mean,
        obs["tpot"].mean,
        token_weighted_tpot(r),
        _max(s.itl_p99 for s in decoding),
        _mean(s.mean_decode_batch for s in decoding),
        _mean(s.mean_decodes for s in decoding),
        _mean(s.mean_decode_step for s in decoding),
        pre,
        _mean(s.decode_only + s.mixed for s in decoding),
        mix,
        idle if math.isnan(idle) else max(0.0, idle),
        mean_obs("admit_wait"),
        mean_obs("transfer"),
        sum(p.preemptions for p in kv_pools) / span,
        sum(p.mean_used for p in r.pools_named("P.kv")) if cfg.split else 0.0,
    )

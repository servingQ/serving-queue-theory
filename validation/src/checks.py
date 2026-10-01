"""Named checks of the paper's propositions by simulation.

Each `Check` states which proposition and Lean theorems it exercises, what
the theory predicts, what the simulation observed, and whether they agree.
`tests/test_propositions.py` asserts every check; `report` prints
them as a report. Scenarios live here once so the two cannot drift.

Two kinds of check:
* **in-model**: the simulation satisfies the proposition's assumptions, so
  disagreement means a bug (in the simulator or in the closed form);
* **beyond-model**: an assumption is dropped (non-Poisson arrivals, emergent
  hit rate, tandem pools, integer splits, heuristic control) and the check
  asks whether the *decision* the proposition implies survives.

`observations` reports quantities with no prediction attached; they are
printed, never asserted.

The `lean=[...]` lists are read by `scripts/check_sim.sh`, which fails if a
cited name is not a Lean theorem or definition.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from functools import cache

from pyserq import Rng

from constants import TRACE_CAP_FACTORS, TRACE_POOLS, TRACE_RATES
from fmt import disp, fixed, fmax, fmin, fold_max, sci_fixed, ssum
from sim import agentic, batch, pd, pd_batching, price_vllm, queue, replay_vllm, routing, serq
from sim.agentic import (
    AgenticConfig,
    EvictionPolicy,
    FetchMode,
    OffloadPolicy,
    Open,
    ProgramClass,
)
from sim.batch import BatchConfig, BatchReport, Fifo, Ps
from sim.pd import Aggregated, Disaggregated, PdConfig, Poisson, Saturated
from sim.pd_batching import PsConfig, StepConfig
from sim.queue import QueueConfig
from sim.replay_vllm import TraceRow, trace_cap
from sim.routing import RoutePolicy, RoutingConfig
from sim.stats import Estimate, Welford, batch_means, paired_differences, replications
from sim.workload import weka
from theory import eviction
from theory.analytic import (
    agg_capacity,
    agg_capacity_i,
    exp_fit,
    finite_source_mm1,
    finite_source_nu_for_utilization,
    irtl_response,
    kingman_bound,
    miss_price,
    mixture_utilization,
    mixture_wait,
    mm1_wait,
    num_in_system,
    pd_full_capacity,
    pk_wait,
    ps_num,
    ps_price,
)
from theory.batch import Constant, Saturating, fifo_admitted, phi_limit, ps_mean_number
from theory.dist import (
    Deterministic,
    Dist,
    Erlang,
    HitMiss,
    Uniform,
    discrete,
    exp,
    hyperexp_balanced,
)
from theory.eviction import Item, varied
from theory.pd import floor_exp_mean, ps_decode_load, split_capacity


class Kind(Enum):
    InModel = "in-model"
    BeyondModel = "beyond-model"


@dataclass
class Check:
    id: str
    paper: str  # paper label, e.g. `prop:pk`
    lean: list[str]  # Lean theorems whose statement the check exercises
    kind: Kind
    claim: str
    expected: str
    observed: str
    passed: bool


def rel(a: float, b: float) -> float:
    return abs(a - b) / abs(b)


def mg1(lam: float, service: Dist, customers: int, seed: int) -> queue.QueueReport:
    return queue.simulate(QueueConfig.mg1(lam, service, customers, seed))


# -------------------------------------------------------------- §2.2 ----


def mm1_response_time() -> Check:
    """Prop. mm1 (i): M/M/1 response time equals `1/(μ-λ)`."""
    mu, obs, ok = 10.0, [], True
    for i, lam in enumerate([5.0, 8.0, 9.0]):
        r = mg1(lam, exp(1.0 / mu), 2_000_000, 10 + i)
        w = mm1_wait(mu, lam)
        ok &= r.sojourn.agrees_with(w, 0.01)
        obs.append(f"λ={disp(lam)}: {r.sojourn} vs {fixed(w, 4)}")
    return Check(
        "mm1_response_time", "sec:intro (M/M/1)", ["mm1Wait_eq_rho_form"], Kind.InModel,
        "M/M/1 mean response time is 1/(μ-λ)",
        "simulated W within its 95% CI (+1%) of 1/(μ-λ), μ=10", "; ".join(obs), ok,
    )  # fmt: skip


def mm1_blowup() -> Check:
    """Prop. mm1 (ii)-(iii): W rises steeply toward μ; the 10× ratio."""
    mu = 10.0
    w = [mg1(lam, exp(1.0 / mu), 4_000_000, 20).sojourn.mean for lam in (9.0, 9.5, 9.9)]
    ratio = w[2] / w[0]
    return Check(
        "mm1_blowup", "sec:intro (M/M/1 example)",
        ["mm1Wait_strictMono", "mm1Wait_unbounded", "mm1Wait_example_ratio"], Kind.InModel,
        "W is increasing and W(9.9)/W(9) = 10 at μ=10",
        "W(9)<W(9.5)<W(9.9); ratio within 15% of 10 (ρ=0.99 converges slowly)",
        f"W = {fixed(w[0], 3)}, {fixed(w[1], 3)}, {fixed(w[2], 3)}; ratio {fixed(ratio, 2)}",
        w[0] < w[1] < w[2] and rel(ratio, 10.0) < 0.15,
    )  # fmt: skip


WORKLOAD_B = discrete([0.1, 0.1, 0.1, 3.7], [0.25] * 4)


def pk_formula() -> Check:
    """Theorem pk, used by Prop. pk: the PK mean wait for several laws."""
    lam = 0.7
    dists = [
        ("D", Deterministic(1.0)),
        ("E4", Erlang(4, 1.0)),
        ("H2(cv²=4)", hyperexp_balanced(1.0, 4.0)),
        ("workloadB", WORKLOAD_B),
    ]
    ok, obs = True, []
    for i, (name, d) in enumerate(dists):
        r = mg1(lam, d, 2_000_000, 30 + i)
        pk = pk_wait(lam, d.second_moment(), lam * d.mean())
        ok &= r.wait.agrees_with(pk, 0.02)
        obs.append(f"{name}: {r.wait} vs {fixed(pk, 4)}")
    return Check(
        "pk_formula", "eq:pk, prop:pk", ["secondMoment_eq_variance_add_sq"], Kind.InModel,
        "M/G/1 mean wait equals λE[S²]/(2(1-ρ))",
        "simulated Wq within its 95% CI (+2%) of PK at ρ=0.7", "; ".join(obs), ok,
    )  # fmt: skip


def variance_orders_delay() -> Check:
    """Prop. pk (ii)-(iii): equal mean, larger variance, longer wait."""
    a, b = Deterministic(1.0), WORKLOAD_B
    ok, obs = True, []
    for rho in (0.3, 0.6, 0.9):
        wa = mg1(rho, a, 1_000_000, 40).wait
        wb = mg1(rho, b, 1_000_000, 40).wait
        ok &= wa.hi() < wb.lo()
        obs.append(
            f"ρ={disp(rho)}: A {fixed(wa.mean, 3)} < B {fixed(wb.mean, 3)} "
            f"(×{fixed(wb.mean / wa.mean, 2)}, PK ×3.43)"
        )
    return Check(
        "variance_orders_delay", "prop:pk, ex:pk",
        ["pkWait_strictMono_secondMoment", "pkWait_lt_of_variance_lt", "workloadB_wait_ratio"],
        Kind.InModel,
        "equal mean, Var[A] < Var[B] ⇒ Wq(A) < Wq(B) at every stable load",
        "CI of Wq(A) entirely below CI of Wq(B) at ρ ∈ {0.3, 0.6, 0.9}", "; ".join(obs), ok,
    )  # fmt: skip


def cache_reuse_lowers_delay() -> Check:
    """Prop. cache: raising the hit rate lowers ρ and the PK delay."""
    lam, hit, miss = 1.8, 0.05, 0.5
    waits, ok, obs = [], True, []
    for i, p in enumerate([0.0, 0.2, 0.4, 0.6, 0.8, 1.0]):
        r = mg1(lam, HitMiss(p, hit, miss), 1_000_000, 50 + i)
        pk = mixture_wait(lam, p, hit, miss)
        ok &= r.wait.agrees_with(pk, 0.03) or (pk < 1e-3 and r.wait.mean < 1e-3)
        ok &= rel(r.utilization, mixture_utilization(lam, p, hit, miss)) < 0.01
        waits.append(r.wait.mean)
        obs.append(f"p={disp(p)}: ρ={fixed(r.utilization, 3)} Wq={fixed(r.wait.mean, 4)}")
    ok &= all(b < a for a, b in zip(waits, waits[1:], strict=False))
    return Check(
        "cache_reuse_lowers_delay", "prop:cache, ex:cache",
        ["utilization_antitone", "pkWait_mixture_antitone", "utilization_example_hit80"],
        Kind.InModel, "ρ and the PK delay are non-increasing in the hit rate p",
        "Wq strictly decreasing in p, each within CI (+3%) of mixtureWait; ρ(0)=0.9, ρ(0.8)=0.252",
        "; ".join(obs), ok,
    )  # fmt: skip


def cv2_ratio() -> Check:
    """Ex. cv2 / Eq. cv2: the M/G/1 to M/M/1 delay ratio is (1+CV²)/2."""
    d = HitMiss(0.96, 0.05, 5.0)
    lam = 0.5 / d.mean()
    g = mg1(lam, d, 4_000_000, 60).wait
    m = mg1(lam, exp(d.mean()), 4_000_000, 60).wait
    want = (1.0 + d.cv2()) / 2.0
    got = g.mean / m.mean
    return Check(
        "cv2_ratio", "ex:cv2, eq:cv2", ["pkWait_ratio_to_exponential", "mixtureCV2_agentic_example"],
        Kind.InModel, "96% hits at 50 ms, misses at 5 s: CV² > 15, delay > 8× exponential",
        f"ratio (1+CV²)/2 = {fixed(want, 2)} within 6%, at ρ=0.5",
        f"CV²={fixed(d.cv2(), 2)}; Wq {fixed(g.mean, 4)} / {fixed(m.mean, 4)} = {fixed(got, 2)}",
        d.cv2() > 15.0 and rel(got, want) < 0.06,
    )  # fmt: skip


MISS_PRICE_SH = 0.05
MISS_PRICE_SM = 0.5


@dataclass(frozen=True)
class MissPriceRun:
    phi: float
    dl: Estimate  # simulated ΔL = λΔT, batch-means CI of per-turn differences
    lo: float  # λδΦ
    hi: float  # (1-ρ)/(1-ρ')·λδΦ
    exact: float  # exact PK difference of L


@cache
def miss_price_scenario(delta: float) -> MissPriceRun:
    """M/G/1 with hit/miss service 0.05/0.5, hit rate 0.8 at ρ = 0.6, against
    hit rate `0.8 - δ` (common random numbers, 4M turns)."""
    s_h, s_m, p = MISS_PRICE_SH, MISS_PRICE_SM, 0.8
    base = HitMiss(p, s_h, s_m)
    lam = 0.6 / base.mean()
    rho = lam * base.mean()
    phi = miss_price(lam, base.second_moment(), rho, s_h, s_m)
    d = HitMiss(p - delta, s_h, s_m)
    r0 = mg1(lam, base, 4_000_000, 150)
    r1 = mg1(lam, d, 4_000_000, 150)
    diffs = lam * (r1.sojourns - r0.sojourns)
    lo = lam * delta * phi
    rho1 = rho + lam * delta * (s_m - s_h)
    return MissPriceRun(
        phi,
        batch_means(diffs, 20),
        lo,
        (1.0 - rho) / (1.0 - rho1) * lo,
        num_in_system(lam, d.second_moment(), rho1) - num_in_system(lam, base.second_moment(), rho),
    )


def miss_price_bracket() -> Check:
    """Prop. price (the prefill stage as an M/G/1 FIFO queue): turning a
    fraction `δ` of turns from hit to miss raises `L` by between `λδΦ` and
    `(1-ρ)/(1-ρ')·λδΦ`, `Φ = missPrice`. Common random numbers make the
    per-turn sojourn differences a tight batch-means CI for `ΔL = λΔT`."""
    ok, obs, phi = True, [], 0.0
    for delta in (0.01, 0.05):
        m = miss_price_scenario(delta)
        phi = m.phi
        ok &= m.dl.lo() <= m.hi and m.dl.hi() >= m.lo and m.dl.agrees_with(m.exact, 0.01)
        obs.append(
            f"δ={disp(delta)}: ΔL {m.dl} vs bracket [{fixed(m.lo, 4)}, {fixed(m.hi, 4)}], "
            f"exact {fixed(m.exact, 4)}"
        )
    return Check(
        "miss_price_bracket", "prop:price", ["missPrice_lower", "missPrice_upper"], Kind.InModel,
        "λδΦ ≤ ΔL ≤ (1-ρ)/(1-ρ')·λδΦ when a fraction δ of turns changes from hit to miss",
        f"M/G/1, s_h={disp(MISS_PRICE_SH)}, s_m={disp(MISS_PRICE_SM)}, p=0.8, ρ=0.6, Φ={fixed(phi, 3)}: "
        "95% CI of ΔL overlaps the bracket and contains the exact PK difference (+1%)",
        "; ".join(obs), ok,
    )  # fmt: skip


def prefill_pays_the_miss() -> Check:
    """Props. price and decode on a replica with the vLLM v1 engine's rules
    (`price_vllm`): forcing a fraction `δ` of turns to miss raises the number
    in the prefill stage by an amount bracketed by the M/G/1 price at the
    stage's effective service `P/r̄`, and changes the number in the decode
    stage by less than 1 %."""
    ok, obs, head = True, [], ""
    for delta in (0.01, 0.05):
        m = price_vllm.price_scenario(delta)
        if not head:
            head = (
                f"r̄={fixed(m.avail, 3)}, ρ_P={fixed(m.rho_p, 3)}, L_P {m.l_p} vs M/G/1 "
                f"{fixed(m.l_p_theory, 3)}, L_D {m.l_d}"
            )
        ok &= m.dl_p.lo() <= 1.05 * m.hi and m.dl_p.hi() >= 0.95 * m.lo
        ok &= abs(m.dl_d.mean) <= 0.01 * m.l_d.mean
        obs.append(
            f"δ={disp(delta)}: ΔL_P {m.dl_p} vs [{fixed(m.lo, 4)}, {fixed(m.hi, 4)}], ΔL_D {m.dl_d} "
            f"({fixed(100.0 * m.dl_d.mean / m.l_d.mean, 2)}% of L_D)"
        )
    return Check(
        "prefill_pays_the_miss", "prop:price, prop:decode",
        ["missPrice_lower", "missPrice_upper", "stationaryMean"], Kind.BeyondModel,
        "on a replica with vLLM's engine rules the price of a miss is paid in the prefill queue (FIFO bracket at the stage's effective service) and hardly in the decode batch",
        "vLLM rules, testbed cost, hit/miss prefill 512/5120 tokens, λE[P]=0.6: 95% CI of λΔTTFT overlaps [λδΦ, (1-ρ)/(1-ρ')λδΦ] (5% slack) at service P/r̄; |λΔ(R-TTFT)| below 1% of λE[R-TTFT]",
        f"{head}; {'; '.join(obs)}", ok,
    )  # fmt: skip


def kingman_bursty_arrivals() -> Check:
    """§2 Kingman's bound and §7: bursty arrivals add delay beyond PK."""
    s = HitMiss(0.96, 0.05, 5.0)
    rho = 0.7
    lam = rho / s.mean()
    ok, obs = True, []
    for i, ca2 in enumerate([2.0, 4.0, 8.0]):
        ia = hyperexp_balanced(1.0 / lam, ca2)
        w = queue.simulate(QueueConfig(ia, s, 1, 4_000_000, 200_000, 70 + i)).wait
        bound = kingman_bound(lam, ia.variance(), s.variance(), rho)
        pk = pk_wait(lam, s.second_moment(), rho)
        ok &= w.mean <= bound and w.lo() > pk
        obs.append(
            f"c_a²={disp(ca2)}: PK {fixed(pk, 2)} < Wq {fixed(w.mean, 2)} ≤ Kingman {fixed(bound, 2)}"
        )
    return Check(
        "kingman_bursty_arrivals", "sec:model (Kingman), sec:limits", [], Kind.BeyondModel,
        "with non-Poisson arrivals PK underestimates delay; Kingman still bounds it",
        "PK < simulated Wq ≤ Kingman bound for H2 arrivals", "; ".join(obs), ok,
    )  # fmt: skip


def little_law() -> Check:
    """Thm. little: L = λW in the simulated queue."""
    r = mg1(0.8, hyperexp_balanced(1.0, 6.0), 1_000_000, 80)
    return Check(
        "little_law", "sec:model (Little)", [], Kind.InModel, "L = λW", "|L-λW|/L < 1%",
        f"L={fixed(r.mean_in_system, 4)}, λW={fixed(r.arrival_rate * r.sojourn.mean, 4)}",
        r.little_residual() < 0.01,
    )  # fmt: skip


# ------------------------------------------------ batching server -------

PS_RHO = 0.7


def ps_services() -> list[tuple[str, Dist]]:
    """Two turn-work laws with mean 0.14 s."""
    return [("D", Deterministic(0.14)), ("hit/miss", HitMiss(0.8, 0.05, 0.5))]


def little_number(r: BatchReport, lam: float) -> Estimate:
    """Mean number at the replica by Little's law, `λ·R`."""
    return Estimate(lam * r.response_ci.mean, lam * r.response_ci.half_width)


@dataclass(frozen=True)
class InsensitivityRow:
    name: str
    ps: Estimate
    ps_theory: float
    fifo: Estimate
    fifo_theory: float


@cache
def insensitivity_scenario() -> tuple[InsensitivityRow, ...]:
    """Open Poisson turns at `ρ = 0.7`, no memory limit, 1M turns per run."""
    rows = []
    for i, (name, d) in enumerate(ps_services()):
        lam = PS_RHO / d.mean()

        def run(server, d=d, lam=lam, i=i):
            c = BatchConfig.poisson_turns(lam, d, server, 1.0e6 / lam, 200 + i)
            return little_number(batch.simulate(c), lam)

        rows.append(
            InsensitivityRow(
                name, run(Ps(Constant(1.0))), ps_num(1.0, PS_RHO), run(Fifo()),
                num_in_system(lam, d.second_moment(), PS_RHO),
            )
        )  # fmt: skip
    return tuple(rows)


def ps_insensitivity() -> Check:
    """PS insensitivity: under PS the mean number depends on the work law only
    through the load; under FIFO it follows PK."""
    rows = insensitivity_scenario()
    ok, obs = True, []
    for r in rows:
        ok &= r.ps.agrees_with(r.ps_theory, 0.02) and r.fifo.agrees_with(r.fifo_theory, 0.02)
        obs.append(
            f"{r.name}: PS {r.ps} vs {fixed(r.ps_theory, 4)}, FIFO {r.fifo} vs PK {fixed(r.fifo_theory, 4)}"
        )
    ok &= rows[0].fifo.hi() < rows[1].fifo.lo()
    return Check(
        "ps_insensitivity", "sec:batch, prop:decode", ["psNum"], Kind.InModel,
        "at a PS server L = ρ/(C-ρ) for every work law with the same mean; at a FIFO server L follows PK",
        "ρ=0.7, φ≡1, work D or hit/miss (mean 0.14 s): PS L within CI (+2%) of ρ/(1-ρ) for both; FIFO L within CI (+2%) of λW_q+ρ and FIFO(D) < FIFO(hit/miss)",
        "; ".join(obs), ok,
    )  # fmt: skip


@dataclass(frozen=True)
class BcmpRow:
    phi: batch.Phi
    rho: float
    lam: float  # turn rate Λ/(1-p)
    throughput: float
    sim: Estimate
    theory: float


@cache
def bcmp_scenario() -> tuple[BcmpRow, ...]:
    """Sessions arrive Poisson at `Λ`; each turn is followed by an H2 tool call
    (mean 2 s, CV² 4) and another turn w.p. 0.8; hit/miss work."""
    s = ps_services()[1][1]
    p = 0.8
    rows = []
    for i, (phi, rho) in enumerate([(Constant(1.0), PS_RHO), (Saturating(0.25, None), 3.0)]):
        lam = rho / s.mean()
        c = BatchConfig.poisson_turns(lam * (1.0 - p), s, Ps(phi), 8.0e5 / lam, 210 + i)
        c.classes[0].resume_prob = p
        c.classes[0].tool_time = hyperexp_balanced(2.0, 4.0)
        r = batch.simulate(c)
        rows.append(
            BcmpRow(phi, rho, lam, r.throughput, little_number(r, lam), ps_mean_number(phi, rho))
        )
    return tuple(rows)


def bcmp_feedback() -> Check:
    """BCMP: with feedback through a general tool delay, the mean number at a
    PS replica is that of an isolated PS queue fed at `λ = Λ/(1-p)`."""
    ok, obs = True, []
    for r in bcmp_scenario():
        ok &= r.sim.agrees_with(r.theory, 0.02) and rel(r.throughput, r.lam) < 0.01
        obs.append(
            f"{r.phi!r}, ρ={disp(r.rho)}: L {r.sim} vs {fixed(r.theory, 4)}; "
            f"X {fixed(r.throughput, 3)} vs λ {fixed(r.lam, 3)}"
        )
    return Check(
        "bcmp_feedback", "sec:sessions, prop:decode", ["psNum", "stationaryMean"], Kind.InModel,
        "open sessions with feedback: L at the PS replica equals Σ n π(n), π(n) ∝ ρⁿ/Π φ(k), with λ = Λ/(1-p)",
        "p=0.8, H2 tool time (CV² 4), hit/miss work: L within CI (+2%) of the formula for φ≡1 and a saturating φ; turn throughput within 1% of Λ/(1-p)",
        "; ".join(obs), ok,
    )  # fmt: skip


@cache
def ps_price_scenario(delta: float) -> MissPriceRun:
    """The PS analogue of `miss_price_scenario`: M/G/1-PS with `φ ≡ 1`,
    common random numbers, 1M turns."""
    s_h, s_m, p = MISS_PRICE_SH, MISS_PRICE_SM, 0.8
    base = HitMiss(p, s_h, s_m)
    lam = 0.6 / base.mean()
    rho = lam * base.mean()
    d = HitMiss(p - delta, s_h, s_m)
    server = Ps(Constant(1.0))
    r0 = batch.simulate(BatchConfig.poisson_turns(lam, base, server, 1.0e6 / lam, 220))
    r1 = batch.simulate(BatchConfig.poisson_turns(lam, d, server, 1.0e6 / lam, 220))
    diffs = [lam * x for x in paired_differences(r0.responses, r1.responses)]
    phi = ps_price(1.0, rho, s_m - s_h)
    lo = lam * delta * phi
    rho1 = rho + lam * delta * (s_m - s_h)
    return MissPriceRun(
        phi, batch_means(diffs, 20), lo, (1.0 - rho) / (1.0 - rho1) * lo,
        ps_num(1.0, rho1) - ps_num(1.0, rho),
    )  # fmt: skip


def ps_price_bracket() -> Check:
    """Prop. decode: at a PS server of capacity `C`, a fraction `δ` of misses
    raises `L` by between `λδΦ_PS` and `(C-ρ)/(C-ρ')·λδΦ_PS`."""
    ok, obs = True, []
    for delta in (0.01, 0.05):
        m = ps_price_scenario(delta)
        ok &= m.dl.lo() <= m.hi and m.dl.hi() >= m.lo and m.dl.agrees_with(m.exact, 0.01)
        obs.append(
            f"δ={disp(delta)}: ΔL {m.dl} vs bracket [{fixed(m.lo, 4)}, {fixed(m.hi, 4)}], "
            f"exact {fixed(m.exact, 4)}"
        )
    return Check(
        "ps_price_bracket", "prop:decode", ["psPrice_lower", "psPrice_upper", "psNum_diff_exact"],
        Kind.InModel, "λδΦ_PS ≤ ΔL ≤ (C-ρ)/(C-ρ')·λδΦ_PS at a PS server, Φ_PS = CΔS/(C-ρ)²",
        "M/G/1-PS, C=1, s_h=0.05, s_m=0.5, p=0.8, ρ=0.6: 95% CI of ΔL overlaps the bracket and contains the exact difference ρ'/(1-ρ')-ρ/(1-ρ) (+1%)",
        "; ".join(obs), ok,
    )  # fmt: skip


@dataclass(frozen=True)
class FootprintRow:
    law: str
    theory: float
    sim: Estimate


@cache
def footprint_scenario() -> tuple[FootprintRow, ...]:
    """`M = 12`; footprints 6, {5,7}, 7, {2,12}; 1M draws each."""
    m = 12.0
    laws = [
        ("$K\\equiv 6$", [(6.0, 1.0)]),
        ("$K\\in\\{5,7\\}$", [(5.0, 0.5), (7.0, 0.5)]),
        ("$K\\equiv 7$", [(7.0, 1.0)]),
        ("$K\\in\\{2,12\\}$", [(2.0, 0.5), (12.0, 0.5)]),
    ]
    rows = []
    for i, (law, d) in enumerate(laws):
        dist = discrete([x[0] for x in d], [x[1] for x in d])
        rng = Rng(230 + i)
        w = Welford()
        for _ in range(1_000_000):
            w.push(float(fifo_admitted(m, dist, rng)))
        rows.append(
            FootprintRow(
                law, exp_fit(d, m), Estimate(w.mean(), 1.96 * math.sqrt(w.variance() / w.n()))
            )
        )
    return tuple(rows)


def footprint_batch_size() -> Check:
    """Prop. footprint: with memory `M` and FIFO admission, the expected number
    admitted depends on the footprint law; more variance can lower or raise it."""
    rows = footprint_scenario()
    ok = all(r.sim.agrees_with(r.theory, 1e-3) or r.sim.half_width == 0.0 for r in rows)
    ok &= all(abs(r.sim.mean - r.theory) < 0.01 for r in rows)
    ok &= rows[1].sim.hi() < rows[0].sim.lo() and rows[2].sim.hi() < rows[3].sim.lo()
    return Check(
        "footprint_batch_size", "prop:footprint",
        ["footprint_variance_hurts", "footprint_variance_helps"], Kind.InModel,
        "M=12: K≡6 admits 2, K∈{5,7} admits 7/4; K≡7 admits 1, K∈{2,12} admits 95/64",
        "Monte Carlo means (1M draws) within CI of expFit, and ordered as the proposition says",
        "; ".join(f"{r.law}: {r.sim} vs {fixed(r.theory, 4)}" for r in rows), ok,
    )  # fmt: skip


@dataclass(frozen=True)
class LpsRow:
    service: str
    cv2: float
    u: float  # load relative to φ(B)
    theory: float
    ps: Estimate
    lps: Estimate


LPS_CAP = 8
LPS_BETA = 0.1


@cache
def lps_scenario() -> tuple[LpsRow, ...]:
    """Poisson turns; exact LPS (at most `B = 8` in the batch at
    `φ(n) = n/(1+0.1(n-1))`) against PS with `φ` flattened at `B`, for work
    laws D, Exp and H2 (CV² 4) of mean 1 and loads `u = ρ/φ(B)`."""
    base = Saturating(LPS_BETA, None)
    capped = Saturating(LPS_BETA, LPS_CAP)
    rows = []
    for i, (service, d) in enumerate(
        [("D", Deterministic(1.0)), ("Exp", exp(1.0)), ("H2", hyperexp_balanced(1.0, 4.0))]
    ):
        for j, u in enumerate([0.5, 0.8, 0.9]):
            rho = u * phi_limit(capped)
            lam = rho / d.mean()
            seed = 240 + 3 * i + j
            lps = BatchConfig.poisson_turns(lam, d, Ps(base), 4.0e5 / lam, seed)
            lps.batch_cap = LPS_CAP
            ps = BatchConfig.poisson_turns(lam, d, Ps(capped), 4.0e5 / lam, seed)
            rows.append(
                LpsRow(
                    service, d.cv2(), u, ps_mean_number(capped, rho),
                    little_number(batch.simulate(ps), lam), little_number(batch.simulate(lps), lam),
                )
            )  # fmt: skip
    return tuple(rows)


def lps_vs_saturating_phi() -> Check:
    """How far is the theory's "φ saturating at B" from the exact batch cap?"""
    ok, obs = True, []
    for r in lps_scenario():
        ok &= r.ps.agrees_with(r.theory, 0.03)
        if r.service == "Exp":
            ok &= r.lps.agrees_with(r.theory, 0.03)
        elif r.service == "D" and r.u >= 0.8:
            ok &= r.lps.hi() < r.theory
        elif r.service == "H2" and r.u >= 0.8:
            ok &= r.lps.lo() > r.theory
        obs.append(
            f"{r.service} u={disp(r.u)}: formula {fixed(r.theory, 3)}, PS {fixed(r.ps.mean, 3)}, "
            f"LPS {fixed(r.lps.mean, 3)} ({format(100.0 * (r.lps.mean / r.theory - 1.0), '+.1f')}%)"
        )
    return Check(
        "lps_vs_saturating_phi", "sec:batch", ["stationaryMean"], Kind.BeyondModel,
        "a batch cap B is modelled by φ flattened at B; the exact cap (LPS) is not insensitive, so the error depends on the work law",
        "B=8, β=0.1: PS with flattened φ within CI (+3%) of Σnπ(n) for every law; LPS equals it for Exp (+3%), is below it for D and above it for H2 (CV² 4) at u ≥ 0.8",
        "; ".join(obs), ok,
    )  # fmt: skip


# ---------------------------------------------------------- §2.3 / §3.2 -


def _decreasing(xs) -> bool:
    return all(b < a for a, b in zip(xs, xs[1:], strict=False))


def closed_throughput_falls_with_concurrency() -> Check:
    """§2.3: in a closed system with finite KV, throughput falls with N
    because the hit rate falls and E[S] rises."""
    ns = [16, 32, 64, 96]
    rs = [agentic.simulate(AgenticConfig.example(n, 6.0e5)) for n in ns]
    ok = (
        _decreasing([r.throughput for r in rs])
        and _decreasing([r.hit_rate for r in rs])
        and _decreasing([-r.service.mean() for r in rs])
    )
    obs = "; ".join(
        f"N={n}: X={fixed(r.throughput, 2)}/s hit={fixed(r.hit_rate, 2)} E[S]={fixed(r.service.mean(), 2)}s"
        for n, r in zip(ns, rs, strict=True)
    )
    return Check(
        "closed_throughput_falls_with_concurrency", "sec:model (closed network), sec:offload",
        ["meanService_antitone"], Kind.BeyondModel,
        "a throughput that falls with N signals per-step demand growing with N, via a falling hit rate",
        "X, hit rate decreasing and E[S] increasing in N (hit rate emergent, not assumed)", obs, ok,
    )  # fmt: skip


def closed_throughput_nondecreasing_fixed_demand() -> Check:
    """§2.3, fixed-demand side: with ample KV every follow-up turn hits, the
    per-visit demand does not depend on N, and throughput is non-decreasing
    in N and below `min(N/(D+Z), 1/D)` (Lazowska et al.)."""
    ok, prev, obs = True, 0.0, []
    for n in [1, 2, 4, 8, 16, 32]:
        cfg = AgenticConfig.example(n, 1.0e9)
        cfg.max_context = 2.0e5
        r = agentic.simulate(cfg)
        d, z = r.service.mean(), r.think.mean()
        bound = fmin(n / (d + z), 1.0 / d)
        ok &= r.hit_rate == 1.0 and r.throughput >= 0.99 * prev and r.throughput <= 1.01 * bound
        prev = r.throughput
        obs.append(f"N={n}: X={fixed(r.throughput, 2)} ≤ {fixed(bound, 2)}")
    return Check(
        "closed_throughput_nondecreasing_fixed_demand", "sec:model (closed network)", [],
        Kind.InModel, "with fixed per-visit demand, closed-network throughput does not decrease with N",
        "ample KV (hit rate 1): X non-decreasing in N (1% slack) and ≤ min(N/(D+Z), 1/D) (+1%)",
        "; ".join(obs), ok,
    )  # fmt: skip


def interactive_response_time_law() -> Check:
    """Thm. irtl: R = N/X − Z in the closed agentic system."""
    worst, obs = 0.0, []
    for n in [8, 32, 96]:
        r = agentic.simulate(AgenticConfig.example(n, 6.0e5))
        worst = fmax(worst, r.irtl_residual(float(n)))
        obs.append(
            f"N={n}: R={fixed(r.response.mean(), 2)} N/X-Z={fixed(irtl_response(float(n), r.throughput, r.think.mean()), 2)}"
        )
    return Check(
        "interactive_response_time_law", "sec:model (closed network)", [], Kind.InModel,
        "R = N/X - Z", "|N - X(R+Z)|/N < 1%",
        f"{'; '.join(obs)} (worst residual {fixed(100.0 * worst, 2)}%)", worst < 0.01,
    )  # fmt: skip


def offload_cfg(n: int, bw: float, policy: OffloadPolicy) -> AgenticConfig:
    """Closed example workload with blocking fetches over a tier of `bw` tokens/s."""
    cfg = AgenticConfig.example(n, 6.0e5)
    cfg.offload = policy
    cfg.fetch = FetchMode.Blocking
    cfg.tier_bandwidth = bw
    return cfg


def always_offload_can_be_worse() -> Check:
    """Prop. option, second part: always-offload can be strictly worse
    (blocking fetches over a slow tier, the regime of ThunderAgent App. A.2)."""
    never = agentic.simulate(offload_cfg(32, 5.0e3, OffloadPolicy.Never))
    always = agentic.simulate(offload_cfg(32, 5.0e3, OffloadPolicy.Always))
    return Check(
        "always_offload_can_be_worse", "sec:offload (option value)", ["always_offload_can_be_worse"],
        Kind.BeyondModel, "always-offload can be strictly worse than never offloading",
        "N=32, 5k tok/s tier, blocking fetch: X(always) < X(never)",
        f"X never={fixed(never.throughput, 3)}/s (hit {fixed(never.hit_rate, 2)}), always={fixed(always.throughput, 3)}/s "
        f"(hit {fixed(always.hit_rate, 2)}, tier util {fixed(always.tier_utilization, 2)}, stall {fixed(always.stall_load, 2)})",
        always.throughput < never.throughput,
    )  # fmt: skip


def selective_offload_never_worse() -> Check:
    """Prop. option, first part, for a heuristic controller."""
    ok, obs = True, []
    for bw in (5.0e3, 2.0e4, 1.0e5):
        for n in (32, 64):

            def x(p, n=n, bw=bw):
                return agentic.simulate(offload_cfg(n, bw, p)).throughput

            nv, al, se = x(OffloadPolicy.Never), x(OffloadPolicy.Always), x(OffloadPolicy.Selective)
            ok &= se >= 0.97 * fmax(nv, al)
            obs.append(
                f"bw={sci_fixed(bw, 0)} N={n}: never {fixed(nv, 2)} always {fixed(al, 2)} selective {fixed(se, 2)}"
            )
    return Check(
        "selective_offload_never_worse", "sec:offload (option value)",
        ["optimal_cost_antitone_in_actions", "enabling_offload_never_hurts"], Kind.BeyondModel,
        "enabling offloading never hurts when the choice is made per program",
        "X(selective) ≥ 0.97·max(X(never), X(always)) on all 6 cells", "; ".join(obs), ok,
    )  # fmt: skip


# ---------------------------------------------------------------- §3.1 --


def shortest_first_counterexample() -> Check:
    """Prop. blind (i)."""
    it = [Item.uniform(c) for c in (4, 5, 6)]
    sf = eviction.subset_cost(it, eviction.shortest_first(it, 6))
    opt, _ = eviction.optimal(it, 6)
    return Check(
        "shortest_first_counterexample", "sec:evict (SF counterexample)",
        ["shortestFirst_not_optimal", "shortestFirst_optimality_claim_false"], Kind.InModel,
        "c={4,5,6}, ΔC=6: SF costs 41, {6} costs 36", "SF=41, OPT=36",
        f"SF={disp(sf)}, OPT={disp(opt)}", sf == 41.0 and opt == 36.0,
    )  # fmt: skip


def shortest_first_two_approx() -> Check:
    """Prop. blind (ii): SF/OPT ≤ 2 with uniform resume probabilities."""
    worst, means = 0.0, []
    for i, (n, max_c) in enumerate([(6, 20), (12, 200), (18, 60)]):
        v = eviction.sweep(3000, n, max_c, eviction.UNIFORM, 90 + i)
        worst = fold_max((r.shortest_first for r in v), worst)
        means.append(ssum([r.shortest_first for r in v]) / len(v))
    return Check(
        "shortest_first_two_approx", "prop:blind (ii)",
        ["shortestFirst_feasible", "shortestFirst_two_approx"], Kind.InModel,
        "SF is a 2-approximation when all p_i are equal", "max SF/OPT ≤ 2 over 9000 random instances",
        f"max {fixed(worst, 3)}; mean {fixed(means[0], 3)}, {fixed(means[1], 3)}, {fixed(means[2], 3)}",
        worst <= 2.0 + 1e-12,
    )  # fmt: skip


def shortest_first_tightness() -> Check:
    """Prop. blind (ii), tightness: c={K,K+1}, ΔC=K+1."""
    ok, last = True, 0.0
    for k in (1, 2, 5, 10, 100, 1000):
        it = [Item.uniform(k), Item.uniform(k + 1)]
        sf = eviction.subset_cost(it, eviction.shortest_first(it, k + 1))
        opt, _ = eviction.optimal(it, k + 1)
        r = sf / opt
        want = float(k * k + (k + 1) * (k + 1)) / float((k + 1) * (k + 1))
        ok &= abs(r - want) < 1e-12 and r > last and r < 2.0
        last = r
    return Check(
        "shortest_first_tightness", "prop:blind (ii)", ["shortestFirst_two_approx_tight"],
        Kind.InModel, "the factor 2 is tight", "ratio (K²+(K+1)²)/(K+1)², increasing to 2",
        f"ratio at K=1000: {fixed(last, 5)}", ok and last > 1.99,
    )  # fmt: skip


def shortest_first_unbounded_with_resume_prob() -> Check:
    """Prop. blind (i): with resume probabilities SF has no constant ratio,
    and the density rule is much closer to optimal on random instances."""
    ok = True
    for m in (10, 100, 1000):
        mf = float(m)
        it = [Item(2, 1.0), Item(m, 1.0 / (mf * mf * mf))]
        sf = eviction.subset_cost(it, eviction.shortest_first(it, 2))
        opt, _ = eviction.optimal(it, 2)
        ok &= sf / opt > mf
    v = eviction.sweep(3000, 12, 200, varied(0.05), 99)
    max_sf = fold_max((r.shortest_first for r in v), 0.0)
    mean_sf = ssum([r.shortest_first for r in v]) / len(v)
    mean_d = ssum([r.density_first for r in v]) / len(v)
    ok &= max_sf > 2.0 and mean_d < mean_sf
    return Check(
        "shortest_first_unbounded_with_resume_prob", "prop:blind (i), sec:evict (Dantzig)",
        ["shortestFirst_unbounded_with_resume_prob", "shortestFirst_wrong_with_resume_prob"],
        Kind.InModel,
        "with p_i c_i² costs SF has no constant ratio; the density order p_i c_i is the relaxation's greedy",
        "witness ratio > M for M=10,100,1000; on random p_i: max SF/OPT > 2 and mean(density) < mean(SF)",
        f"random p_i∈[0.05,1]: SF max {fixed(max_sf, 2)} mean {fixed(mean_sf, 3)}; density mean {fixed(mean_d, 3)}",
        ok,
    )  # fmt: skip


def guarded_density_two_approx() -> Check:
    """Prop. guarded: with arbitrary weights plain density greedy has no
    constant ratio, while the guarded density greedy stays within 2."""
    ok = True
    for k in (10, 1000, 100_000):
        it, delta = eviction.density_counterexample(k)
        d = eviction.weighted_cost(it, eviction.density_weighted(it, delta))
        g = eviction.guarded_density(it, delta)
        opt, _ = eviction.optimal_weighted(it, delta)
        ok &= d == float(k) and opt == 2.0 and eviction.weighted_cost(it, g) == 2.0
    v = []
    for i, (n, max_c) in enumerate([(6, 20), (12, 200), (18, 60)]):
        v += eviction.sweep_weighted(3000, n, max_c, 160 + i)
    q = []
    for i in range(3):
        q += eviction.sweep(3000, 12, 200, varied(0.05), 170 + i)

    def mx(xs, f):
        return fold_max((f(r) for r in xs), 0.0)

    gw, dw = mx(v, lambda r: r.guarded_density), mx(v, lambda r: r.density_first)
    gq = mx(q, lambda r: r.guarded_density)
    ok &= gw <= 2.0 + 1e-12 and gq <= 2.0 + 1e-12 and dw > 2.0
    return Check(
        "guarded_density_two_approx", "prop:guarded",
        ["densityFirst_unbounded", "threshold_prefix_le", "guardedGreedy_two_approx"], Kind.InModel,
        "guarded density greedy is a 2-approximation for arbitrary weights; plain density greedy is not",
        "witness (1,0),(K,K),(1,2), ΔC=2: density pays K, guarded and OPT 2; max guarded/OPT ≤ 2 over 9000 general-weight and 9000 p_i c_i² instances; plain density max > 2",
        f"general weights: guarded max {fixed(gw, 3)}, density max {fixed(dw, 1)}; p_i c_i²: guarded max {fixed(gq, 3)}",
        ok,
    )  # fmt: skip


def _memory_instance(rng: Rng, n: int) -> list[eviction.Weighted]:
    """States with price `w_i` and byte-seconds `c_i = tokens × τ_i`."""
    out = []
    for _ in range(n):
        a = rng.range_u64(1, 8)
        b = rng.range_u64(1, 8)
        out.append(eviction.Weighted(a * b, 10.0 ** rng.range_f64(-1.0, 2.0)))
    return out


def memory_threshold_rule() -> Check:
    """Prop. memory: (i) the θ-threshold set costs no more than any set
    freeing at least as many byte-seconds; (ii) at block level, the density
    prefix plus the completing block costs at most OPT plus that block."""
    rng = Rng(180)
    thresholds = ok_i = 0
    ok = True
    for _ in range(2000):
        n = rng.range_u32(4, 12)
        items = _memory_instance(rng, n)
        for theta in [it.density() for it in items] + [0.0]:
            t = [i for i in range(len(items)) if items[i].w <= theta * float(items[i].c)]
            freed = eviction.weighted_freed(items, t)
            opt, _ = eviction.optimal_weighted(items, freed)
            cost = eviction.weighted_cost(items, t)
            thresholds += 1
            if cost <= opt * (1.0 + 1e-12):
                ok_i += 1
    ok &= ok_i == thresholds
    blocks = ok_ii = greedy_beats_opt = 0
    worst_excess = 0.0
    for _ in range(3000):
        n = rng.range_u32(4, 16)
        items = []
        for _ in range(n):
            c = rng.range_u64(1, 8)
            items.append(eviction.Weighted(c, 10.0 ** rng.range_f64(-1.0, 2.0)))
        total = sum(i.c for i in items)
        delta = rng.range_u64(1, total)
        g = eviction.density_weighted(items, delta)
        x = g[-1]
        cost = eviction.weighted_cost(items, g)
        opt, _ = eviction.optimal_weighted(items, delta)
        blocks += 1
        if cost <= opt + items[x].w + 1e-9:
            ok_ii += 1
        if cost > opt * (1.0 + 1e-9):
            greedy_beats_opt += 1
            worst_excess = fmax(worst_excess, (cost - opt) / items[x].w)
    ok &= ok_ii == blocks and greedy_beats_opt > 0
    return Check(
        "memory_threshold_rule", "prop:memory", ["threshold_rule_optimal", "density_prefix_plus_one"],
        Kind.InModel,
        "dropping exactly the states priced at most θ per byte-second is optimal for the memory it frees; block-level density order is optimal up to one block",
        "(i) Σ_T w = OPT(Σ_T c) at every candidate θ of 2000 random instances (4–12 states, c_i = tokens·τ_i); (ii) density prefix + completing block ≤ OPT + w_x on 3000 block instances, with plain density > OPT on some",
        f"(i) {ok_i}/{thresholds} thresholds optimal; (ii) {ok_ii}/{blocks} within one block, density > OPT on {greedy_beats_opt}, worst excess {fixed(worst_excess, 3)} of the completing block's price",
        ok,
    )  # fmt: skip


# ------------------------------------------------------------------ §4 --


def pd_cfg(n, mode, sp, sd, i, g, bnet) -> PdConfig:
    """Saturated PD scenario with exponential work and `E[K] = 1`."""
    c = PdConfig.from_means(n, mode, Saturated(10 * n), sp, sd, i, g, bnet, 1.0)
    c.requests = 100_000
    c.warmup = 10_000
    return c


def pd_capacity_matches() -> Check:
    """Prop. pd (iii), capacity side: the scalar capacities are what a tandem
    of FIFO pools delivers when saturated."""
    ok, obs = True, []
    agg = pd.simulate(pd_cfg(32, Aggregated(), 1.0, 1.0, 0.5, (2.0, 1.0), 1000.0))
    want = agg_capacity_i(32.0, 1.0, 1.0, 0.5)
    ok &= rel(agg.throughput, want) < 0.02
    obs.append(f"agg {fixed(agg.throughput, 2)} vs {fixed(want, 2)}")
    for np_, bnet in [(10, 1000.0), (11, 1000.0), (12, 1000.0), (11, 10.0)]:
        cfg = pd_cfg(32, Disaggregated(np_), 1.0, 1.0, 0.5, (2.0, 1.0), bnet)
        r = pd.simulate(cfg)
        want = split_capacity(32, np_, 1.0, 1.0, 2.0, 1.0, bnet, 1.0)
        ok &= rel(r.throughput, want) < 0.02
        obs.append(f"N_P={np_} B/K={disp(bnet)}: {fixed(r.throughput, 2)} vs {fixed(want, 2)}")
    return Check(
        "pd_capacity_matches", "prop:pd (iii), ex:pd", ["pd_wins_example", "pd_loses_example"],
        Kind.InModel, "capacities N/(s_P+s_D+I) and min(N_P g_P/s_P, N_D g_D/s_D, B/E[K])",
        "saturated throughput within 2% (N=32, s_P=s_D=1, I=0.5, g_P=2)", "; ".join(obs), ok,
    )  # fmt: skip


def pd_no_gain() -> Check:
    """Prop. pd (i)-(ii): without gains or interference no split beats
    aggregation, and the rate-matched split ties."""
    n, sp, sd = 8, 1.0, 3.0
    agg = pd.simulate(pd_cfg(n, Aggregated(), sp, sd, 0.0, (1.0, 1.0), math.inf)).throughput
    ok = rel(agg, agg_capacity(float(n), sp, sd)) < 0.02
    obs = [f"agg {fixed(agg, 3)}"]
    for np_ in range(1, n):
        x = pd.simulate(pd_cfg(n, Disaggregated(np_), sp, sd, 0.0, (1.0, 1.0), math.inf)).throughput
        ok &= x <= agg * 1.01
        if np_ == 2:
            ok &= rel(x, agg) < 0.02
        obs.append(f"N_P={np_}: {fixed(x, 3)}")
    return Check(
        "pd_no_gain", "prop:pd (i)-(ii)",
        ["pd_le_agg", "pd_eq_agg_at_rate_match", "rate_match_optimal", "pdCompute_eq_agg_of_no_gain"],
        Kind.InModel, "μ_PD ≤ μ_A for every split, with equality at N_P = N s_P/(s_P+s_D)",
        "every split ≤ agg (+1%); N_P=2 of 8 ties (s_P=1, s_D=3)", "; ".join(obs), ok,
    )  # fmt: skip


# ------------------------- issue #28: colocated vs split decode engines --

PD_SEEDS = (1, 2, 3)
PD_MS = 1e3
PD_FIXED_PROMPT = "2000"  # the sweep's `fixed` prompt case of the serQ #208 baseline
H2_PROMPT = "max(1, floor(~h2(2000, 9)))"


def _ms(e: Estimate) -> str:
    return f"{fixed(e.mean * PD_MS, 3)} ± {fixed(e.half_width * PD_MS, 3)} ms"


def _finite_below(xs, bound: float) -> bool:
    return all(math.isfinite(x) and x < bound for x in xs)


def pd_ps_scaling_identity() -> Check:
    """DecodeScaling: at `pd_ps.sq` (N = 4, f = 1/4) the pooled decode station
    is the colocated one with arrivals and capacity multiplied by 4. Same
    number decoding per station, the M/G/1-PS closed form ρ/(1-ρ); decode
    time and token-weighted TPOT divided by 4."""
    ok, obs = True, []
    rates = (5.0, 10.0, 15.0, 20.0)
    cfgs = [
        PsConfig(split, rate, s) for rate in rates for s in range(1, 6) for split in (False, True)
    ]
    reports = dict(zip(cfgs, serq.parallel(pd_batching.simulate_ps, cfgs), strict=True))
    for rate in rates:
        pairs = [
            (reports[PsConfig(False, rate, s)], reports[PsConfig(True, rate, s)])
            for s in range(1, 6)
        ]
        ok &= all(c.stable and d.stable for c, d in pairs)
        cfg = PsConfig(False, rate, 1)
        gaps = floor_exp_mean(cfg.output_mean) + 1.0  # E[o - 1] for o = floor(exp) + 2
        load = ps_decode_load(rate, gaps, cfg.tok, pd_batching.ENGINES * cfg.share)
        want = ps_num(1.0, load)
        colo = replications([c.decoding_per_station for c, _ in pairs])
        split = replications([d.decoding_per_station for _, d in pairs])
        time_ratio = replications([c.decode_time / d.decode_time for c, d in pairs])
        tpot_ratio = replications([c.tpot_token / d.tpot_token for c, d in pairs])
        n = float(pd_batching.ENGINES)
        ok &= colo.agrees_with(want, 0.05) and split.agrees_with(want, 0.05)
        ok &= time_ratio.agrees_with(n, 0.05) and tpot_ratio.agrees_with(n, 0.05)
        obs.append(
            f"λ={disp(rate)} (ρ={fixed(load, 2)}): decoding {colo} colocated, {split} split vs {fixed(want, 3)}; "
            f"decode time ratio {time_ratio}, TPOT ratio {tpot_ratio}"
        )
    return Check(
        "pd_ps_scaling_identity", "issue #28 (DecodeScaling)",
        ["psMeanNumber_scale", "dedicated_mean_number_eq", "dedicated_sojourn", "tpot_token_weighted_scale"],
        Kind.InModel,
        "a PS decode station with arrivals and capacity scaled by N keeps its occupancy law and divides the sojourn by N",
        "number decoding per station within 5 % of ρ/(1-ρ) in both modes; decode-time and token-weighted TPOT ratios within 5 % of N = 4 (5 seeds, 300 s)",
        "; ".join(obs), ok,
    )  # fmt: skip


def _step_pairs(
    rates, **kw
) -> dict[float, list[tuple[pd_batching.StepReport, pd_batching.StepReport]]]:
    """Colocated and split reports of the fixed-prompt baseline, with `kw`
    on top, for every rate and seed, run concurrently."""
    kw = {"prompt_len": PD_FIXED_PROMPT, **kw}
    cfgs = [
        StepConfig(split, rate, s, **kw)
        for rate in rates
        for s in PD_SEEDS
        for split in (False, True)
    ]
    reports = dict(
        zip([c.key() for c in cfgs], serq.parallel(pd_batching.simulate_step, cfgs), strict=True)
    )
    return {
        rate: [
            (
                reports[StepConfig(False, rate, s, **kw).key()],
                reports[StepConfig(True, rate, s, **kw).key()],
            )
            for s in PD_SEEDS
        ]
        for rate in rates
    }


def pd_step_split_tpot_at_equal_throughput() -> Check:
    """Beyond the PS model: `pd_batching.sq`'s step engines, 4 colocated vs
    3 prefill + 1 decode, the baseline of serQ #208 on its `fixed` prompt
    case (2000-token prompts; exclusive prefill steps, a 0.2 ms decode
    step, memory that never binds, a free transfer). The same requests, so
    the same output throughput; the split's token-weighted TPOT is below
    the colocated one at every load and the gap grows with load, and the
    split's TTFT is above (three prefill engines carry what four did)."""
    ok, obs, ratios = True, [], []
    for rate, pairs in _step_pairs((20.0, 40.0, 60.0, 70.0)).items():
        ok &= all(c.stable and d.stable for c, d in pairs)
        thr = replications([c.output_tokens_per_s / d.output_tokens_per_s for c, d in pairs])
        c_tpot = replications([c.tpot_token for c, _ in pairs])
        d_tpot = replications([d.tpot_token for _, d in pairs])
        c_ttft = replications([c.ttft for c, _ in pairs])
        d_ttft = replications([d.ttft for _, d in pairs])
        ok &= thr.agrees_with(1.0, 0.01)
        ok &= d_tpot.hi() < c_tpot.lo() and c_ttft.hi() < d_ttft.lo()
        ratios.append(c_tpot.mean / d_tpot.mean)
        c, d = pairs[0]
        obs.append(
            f"λ={disp(rate)}: {fixed(c.requests_per_s, 1)} req/s, out tok/s ratio {thr}; "
            f"TPOT {_ms(c_tpot)} colocated vs {_ms(d_tpot)} split (×{fixed(ratios[-1], 2)}); "
            f"TTFT {_ms(c_ttft)} vs {_ms(d_ttft)}; "
            f"decodes per engine {fixed(c.decoding, 2)} vs {fixed(d.decoding, 2)}, per step {fixed(c.batch, 2)} vs {fixed(d.batch, 2)}, "
            f"decode step {fixed(c.decode_step * PD_MS, 3)} vs {fixed(d.decode_step * PD_MS, 3)} ms; "
            f"colocated shares prefill {fixed(c.prefill_share, 2)}, decode {fixed(c.decode_share, 2)}, idle {fixed(c.idle_share, 2)}; "
            f"prefill capacity busy {fixed(c.prefill_busy, 2)} vs {fixed(d.prefill_busy, 2)} (seed 1)"
        )
    ok &= all(a < b for a, b in zip(ratios, ratios[1:], strict=False))
    return Check(
        "pd_step_split_tpot_at_equal_throughput", "issue #28 (serQ #208 baseline, `fixed` prompts)",
        ["dedicated_sojourn", "decode_share_loss"], Kind.BeyondModel,
        "at equal output throughput the split shortens the time per output token and lengthens the TTFT; the decode share of a colocated engine is not the constant the PS identity assumes",
        "runs stable (kept up, prefill capacity below 99 % busy); output tok/s ratio within 1 % of 1; split TPOT below colocated and colocated TTFT below split (95 % intervals disjoint) at λ ∈ {20, 40, 60, 70}; TPOT ratio increasing in λ (3 seeds, 300 s)",
        "; ".join(obs), ok,
    )  # fmt: skip


def pd_step_long_step_matches_ps_share() -> Check:
    """With a 10 ms decode step (`omega = 0.01`) a colocated engine's decodes
    no longer drain between prefills: it is never idle, its decode share is
    `1 - p` for a prefill share `p`, and the TPOT ratio is the PS identity's
    `1 / (1 - p)` (`dedicated_sojourn` with `f = 1 - p`)."""
    ok, obs = True, []
    for rate, pairs in _step_pairs((40.0, 60.0, 70.0), sets={"omega": 0.01}).items():
        ok &= all(c.stable and d.stable for c, d in pairs)
        ratio = replications([c.tpot_token / d.tpot_token for c, d in pairs])
        want = replications([1.0 / (1.0 - c.prefill_share) for c, _ in pairs])
        idles = [c.idle_share for c, _ in pairs]
        d_ttft = replications([d.ttft for _, d in pairs])
        c_ttft = replications([c.ttft for c, _ in pairs])
        ok &= _finite_below(idles, 0.01) and ratio.relative_error(want.mean) < 0.05
        ok &= c_ttft.hi() < d_ttft.lo()
        obs.append(
            f"λ={disp(rate)}: TPOT ratio {ratio} vs 1/(1-p) {want}; colocated idle {fixed(fold_max(idles), 3)}; "
            f"TTFT {_ms(c_ttft)} colocated vs {_ms(d_ttft)} split"
        )
    return Check(
        "pd_step_long_step_matches_ps_share", "issue #28 (serQ #208, `omega = 0.01`)",
        ["dedicated_sojourn", "psMeanNumber_anti_share"], Kind.BeyondModel,
        "when the decodes never drain, the step engines' TPOT ratio is the PS identity's 1/(1-p) at the measured prefill share",
        "colocated idle measured and < 1 %; TPOT ratio within 5 % of 1/(1-p) at λ ∈ {40, 60, 70}; split TTFT above colocated (3 seeds, 300 s)",
        "; ".join(obs), ok,
    )  # fmt: skip


def pd_step_interruption_pattern() -> Check:
    """The mean prefill share alone does not set the colocated TPOT. At
    λ = 60 with exclusive steps, mixed batches and 512-token chunks the
    engines spend the same share of their time on prefills. At a 0.2 ms
    decode step the pattern changes little (a decode gains a token per
    prefill step) and every pattern is far above the split; at a 10 ms step
    the TPOT falls from exclusive, where it is the PS identity's 1/(1-p), to
    mixed to chunked, where it is below 0.6 of that."""
    ok, obs = True, []
    patterns = (("exclusive", {}), ("mixed", {"exclusive": False}),
                ("chunk 512", {"exclusive": False, "sets": {"chunk_cap": 512.0}}))  # fmt: skip
    for omega in (2e-4, 0.01):
        cfgs = [
            StepConfig(False, 60.0, s, prompt_len=PD_FIXED_PROMPT,
                       sets={"omega": omega, **kw.get("sets", {})},
                       **{k: v for k, v in kw.items() if k != "sets"})
            for _, kw in patterns for s in PD_SEEDS
        ] + [StepConfig(True, 60.0, s, prompt_len=PD_FIXED_PROMPT, sets={"omega": omega}) for s in PD_SEEDS]  # fmt: skip
        reports = serq.parallel(pd_batching.simulate_step, cfgs)
        ok &= all(r.stable for r in reports)
        rows = []
        for i, (name, _) in enumerate(patterns):
            rs = reports[i * len(PD_SEEDS) : (i + 1) * len(PD_SEEDS)]
            rows.append((name, replications([r.tpot_token for r in rs]),
                         replications([r.prefill_share + r.mixed_share for r in rs]),
                         fold_max(r.itl_p99 for r in rs)))  # fmt: skip
        d_tpot = replications([r.tpot_token for r in reports[-len(PD_SEEDS) :]])
        shares = [p.mean for _, _, p, _ in rows]
        ok &= max(shares) - min(shares) < 0.05
        tpots = [t.mean for _, t, _, _ in rows]
        ps_ratio = 1.0 / (
            1.0 - rows[0][2].mean
        )  # the identity at the exclusive run's prefill share
        if omega == 0.01:
            ok &= rows[1][1].hi() < rows[0][1].lo() and rows[2][1].hi() < rows[1][1].lo()
            ok &= abs(tpots[0] / d_tpot.mean - ps_ratio) / ps_ratio < 0.05
            ok &= tpots[2] / d_tpot.mean < 0.6 * ps_ratio
        else:
            ok &= max(tpots) / min(tpots) < 1.15 and min(tpots) > 2.0 * d_tpot.mean
        cells = [
            f"{name} TPOT {_ms(t)} (×{fixed(t.mean / d_tpot.mean, 2)}), prefill share {fixed(p.mean, 3)}, ITL p99 {fixed(itl * PD_MS, 1)} ms"
            for name, t, p, itl in rows
        ]
        obs.append(
            f"step {disp(omega * PD_MS)} ms: split TPOT {_ms(d_tpot)}, 1/(1-p) {fixed(ps_ratio, 2)}; "
            + ", ".join(cells)
        )
    return Check(
        "pd_step_interruption_pattern", "issue #28 (serQ #208 variations)", [], Kind.BeyondModel,
        "engines with the same mean prefill share but different interruption patterns have different TPOTs, so the mean share is not enough to predict the split's gain",
        "prefill shares within 0.05 of each other; at the 0.2 ms step the three TPOTs within 15 % of each other (chunking gains 9 %) and above 2× the split's; at the 10 ms step exclusive > mixed > chunked with disjoint intervals, exclusive within 5 % of 1/(1-p) times the split's and chunked below 0.6 of it (λ = 60, 3 seeds, 300 s)",
        "; ".join(obs), ok,
    )  # fmt: skip


@cache
def pd_win_condition_decisions() -> Check:
    """Prop. pd (iii) as a decision: does the simulated winner (best integer
    split vs aggregation) match the analytic win condition? Cells within 3 %
    of the boundary are skipped."""
    n = 16
    agree = total = skipped = 0
    disagreements = []
    for i in (0.0, 0.25, 0.5, 1.0):
        for gp in (1.0, 1.5, 2.0):
            for bnet in (5.0, 8.0, 1000.0):
                agg_a = agg_capacity_i(float(n), 1.0, 1.0, i)
                pd_a = pd_full_capacity(float(n), 1.0, 1.0, gp, 1.0, bnet, 1.0, math.inf, math.inf)
                if rel(pd_a, agg_a) < 0.03:
                    skipped += 1
                    continue
                # The Lean capacity uses a real-valued split; compare against
                # the best integer one (the last of equal maxima, as Rust's max_by).
                best_np, best_c = None, None
                for np_ in range(1, n):
                    c = split_capacity(n, np_, 1.0, 1.0, gp, 1.0, bnet, 1.0)
                    if best_c is None or c >= best_c:
                        best_np, best_c = np_, c
                agg_s = pd.simulate(
                    pd_cfg(n, Aggregated(), 1.0, 1.0, i, (gp, 1.0), bnet)
                ).throughput
                pd_s = pd.simulate(
                    pd_cfg(n, Disaggregated(best_np), 1.0, 1.0, i, (gp, 1.0), bnet)
                ).throughput
                total += 1
                if (agg_a < pd_a) == (agg_s < pd_s):
                    agree += 1
                else:
                    disagreements.append(
                        f"I={disp(i)} g_P={disp(gp)} B/K={disp(bnet)}: sim agg {fixed(agg_s, 2)} pd {fixed(pd_s, 2)}"
                    )
    tail = f"; disagree: {'; '.join(disagreements)}" if disagreements else ""
    return Check(
        "pd_win_condition_decisions", "prop:pd (iii)", ["pd_beats_agg_iff"], Kind.BeyondModel,
        "PD beats aggregation iff each PD bottleneck exceeds N/(s_P+s_D+I)",
        "simulated winner (best integer split) matches the condition in every decisive cell",
        f"{agree}/{total} agree, {skipped} cells within 3% skipped{tail}", agree == total,
    )  # fmt: skip


# ---------------------------------------------------------------- §3.3 --


def affinity_breaks_at_high_load() -> Check:
    """Prop. routing (ii): strict affinity is not optimal at high load."""
    rates = [0.6, 1.2, 1.6, 1.8]
    aff = [
        routing.simulate(RoutingConfig.example(r, RoutePolicy.Affinity)).response.mean
        for r in rates
    ]
    look = routing.simulate(RoutingConfig.example(1.8, RoutePolicy.Lookahead))
    ok = _decreasing([-a for a in aff]) and aff[3] > 10.0 * look.response.mean
    pairs = ", ".join(f"{disp(r)}/s→{fixed(a, 3)}s" for r, a in zip(rates, aff, strict=True))
    return Check(
        "affinity_breaks_at_high_load", "prop:routing (ii)",
        ["affinity_not_always_optimal", "mm1Wait_unbounded"], Kind.BeyondModel,
        "for any finite migration cost, some stable load makes affinity worse than moving",
        "affinity response increasing in load; at the highest load > 10× lookahead",
        f"affinity R: {pairs}; lookahead at 1.8: {fixed(look.response.mean, 3)}s ({look.migrations} migrations)",
        ok,
    )  # fmt: skip


def lookahead_not_worse_than_affinity() -> Check:
    """Prop. routing (i): the lookahead rule, which contains "stay" as an
    option, is not worse than affinity at any load."""
    ok, obs = True, []
    for r in (0.3, 0.9, 1.4):
        a = routing.simulate(RoutingConfig.example(r, RoutePolicy.Affinity)).response
        l = routing.simulate(RoutingConfig.example(r, RoutePolicy.Lookahead)).response
        ok &= l.mean <= a.hi()
        obs.append(f"{disp(r)}/s: affinity {fixed(a.mean, 3)} lookahead {fixed(l.mean, 3)}")
    return Check(
        "lookahead_not_worse_than_affinity", "prop:routing (i)", ["lookahead_prefers_iff"],
        Kind.BeyondModel, "the lookahead rule prefers staying iff (W1+S1)-(W2+S2) < M2 + (F2-F1)",
        "lookahead mean response ≤ affinity upper CI at every load", "; ".join(obs), ok,
    )  # fmt: skip


# ------------------------------------------------ §4.1 trace replay ----


def trace_replay_variance_sources() -> Check:
    """§2.3 on a real workload, the replay of §4.2 on the vLLM-rule replica:
    with no eviction the prefill-work variance of follow-up turns comes from
    the appends alone (mixture share 0); with a finite pool and a tight cap
    the hit/miss mixture supplies a share; and PK from the measured moments
    is an upper bound on the observed prefill wait in every cell."""
    corpus = weka()
    rate = TRACE_RATES[-1]
    rows: list[TraceRow] = [
        replay_vllm.trace_row(rate, kv, trace_cap(corpus, kv, TRACE_CAP_FACTORS[0]))
        for kv in TRACE_POOLS
    ]
    open_has_no_mixture = rows[0].mixture_share.mean < 1e-9 and rows[0].hit_rate.mean > 0.999
    finite_has_mixture = all(r.mixture_share.mean > 0.0 for r in rows[1:])
    pk_upper = all(r.pk_wait.mean >= r.wait.mean for r in rows)

    def cell(r):
        pool = sci_fixed(r.kv, 1) if math.isfinite(r.kv) else "∞"
        return (
            f"pool {pool} cap {r.cap}: hit {fixed(r.hit_rate.mean, 3)} ρ {fixed(r.rho.mean, 2)} "
            f"CV² {fixed(r.cv2.mean, 1)} mix {fixed(r.mixture_share.mean, 2)} Wq {fixed(r.wait.mean, 1)}s "
            f"PK {fixed(r.pk_wait.mean, 1)}s TTFT {fixed(r.ttft.mean, 1)}s"
        )

    return Check(
        "trace_replay_variance_sources", "sec:congestion, sec:exp-variance, sec:limits",
        ["pkWait_mixture_antitone", "mixtureCV2_agentic_example"], Kind.BeyondModel,
        "on replayed production sessions (vLLM engine rules), prefill-work variance has two sources: the appends (all of it with no eviction) and the hit/miss mixture (a share once the pool is finite, small under block eviction); PK from measured moments is an upper bound on the prefill wait of a finite live population",
        "mixture share 0 with an infinite pool and > 0 for every finite pool at the tight cap; PK ≥ observed wait in every cell",
        "; ".join(cell(r) for r in rows), open_has_no_mixture and finite_has_mixture and pk_upper,
    )  # fmt: skip


# ------------------------------------------- §3.2 inversion load ----

INVERSION_BANDWIDTHS = (2.0e7, 2.0e6, 5.0e5, 1.25e5)  # tokens/s
INVERSION_RATES = tuple(round(0.2 + 0.1 * k, 1) for k in range(19))  # 0.2 .. 2.0


@dataclass(frozen=True)
class InversionRow:
    bandwidth: float
    move_over_service: float  # M̄/E[S]
    rho_star: float  # x/(1+x)
    inversion_rate: float | None
    hot_utilization: float | None
    link_utilization: float | None
    affinity_response: float | None
    move_response: float | None
    lookahead_response: float | None


@cache
def inversion_scenario() -> tuple[InversionRow, ...]:
    """For each bandwidth, sweep the rate and find the inversion of affinity
    against always-move; the move cost is measured on the affinity run."""
    aff = [
        routing.simulate(RoutingConfig.example(r, RoutePolicy.Affinity)) for r in INVERSION_RATES
    ]
    cost = RoutingConfig.example(1.0, RoutePolicy.Affinity).cost
    rows = []
    for bw in INVERSION_BANDWIDTHS:
        found = None
        for i, r in enumerate(INVERSION_RATES):
            cfg = RoutingConfig.example(r, RoutePolicy.LeastLoadedFetch)
            cfg.migrate_bandwidth = bw
            mv = routing.simulate(cfg)
            a = aff[i]
            if mv.response.mean + mv.response.half_width < a.response.mean - a.response.half_width:
                lcfg = RoutingConfig.example(r, RoutePolicy.Lookahead)
                lcfg.migrate_bandwidth = bw
                found = (i, mv, routing.simulate(lcfg))
                break
        i = found[0] if found else len(INVERSION_RATES) - 1
        a = aff[i]
        c = a.mean_context
        m = fmin(c / bw, cost.miss_penalty(c))
        x = m / a.service.mean()
        rows.append(
            InversionRow(
                bw, x, x / (1.0 + x),
                INVERSION_RATES[i] if found else None,
                a.utilization[0] if found else None,
                found[1].link_utilization if found else None,
                a.response.mean if found else None,
                found[1].response.mean if found else None,
                found[2].response.mean if found else None,
            )
        )  # fmt: skip
    return tuple(rows)


def inversion_load_rises_with_move_cost() -> Check:
    """Prop. routing (ii) beyond its model (4 replicas, skewed placement, a
    shared link): the inversion load exists for every finite move cost and
    never falls as the link slows."""
    rows = inversion_scenario()
    all_found = all(r.inversion_rate is not None for r in rows)
    inf = math.inf
    monotone = all(
        (a.inversion_rate if a.inversion_rate is not None else inf)
        <= (b.inversion_rate if b.inversion_rate is not None else inf)
        for a, b in zip(rows, rows[1:], strict=False)
    )

    def cell(r):
        inv = "none" if r.inversion_rate is None else f"{fixed(r.inversion_rate, 1)}/s"
        hot = "-" if r.hot_utilization is None else fixed(r.hot_utilization, 2)
        return (
            f"B={sci_fixed(r.bandwidth, 2)}: M̄/E[S] {fixed(r.move_over_service, 2)} ρ* {fixed(r.rho_star, 2)} "
            f"inversion at {inv} (hot util {hot})"
        )

    return Check(
        "inversion_load_rises_with_move_cost", "prop:routing (ii)",
        ["inversionLoad_mono", "affinity_loses_iff"], Kind.BeyondModel,
        "a cheaper move lowers the load at which always moving beats strict affinity; every finite move cost has such a load",
        "an inversion rate for every bandwidth, nondecreasing as the link slows; hot-replica utilisation at the inversion near ρ*",
        "; ".join(cell(r) for r in rows), all_found and monotone,
    )  # fmt: skip


def inversion_load_closed_form() -> Check:
    """Prop. routing (i) in its model: an M/M/1 affinity node with `μ = 10`
    against an idle node plus a move cost `M + F = x/μ`."""
    mu = 10.0
    obs, ok = [], True
    for i, x in enumerate([0.25, 1.0, 4.0]):
        rho_star = x / (1.0 + x)
        threshold = (1.0 + x) / mu
        side = []
        for k, d in enumerate([-0.05, 0.05]):
            lam = (rho_star + d) * mu
            r = mg1(lam, exp(1.0 / mu), 2_000_000, 40 + 2 * i + k)
            ok &= r.sojourn.hi() < threshold if d < 0.0 else r.sojourn.lo() > threshold
            side.append(
                f"ρ={fixed(rho_star + d, 2)}: W {r.sojourn} {'<' if d < 0.0 else '>'} {fixed(threshold, 3)}"
            )
        obs.append(f"x={disp(x)} (ρ*={fixed(rho_star, 2)}): {', '.join(side)}")
    return Check(
        "inversion_load_closed_form", "prop:routing (i)",
        ["affinity_loses_iff", "inversionLoad_utilization", "inversionLoad_stable"], Kind.InModel,
        "affinity's M/M/1 response exceeds the cost of moving to an idle node iff ρ > ρ* = μ(M+F)/(1+μ(M+F))",
        "W below (1+x)/μ at ρ*−0.05 and above it at ρ*+0.05 for x = M+F over service ∈ {0.25, 1, 4}",
        "; ".join(obs), ok,
    )  # fmt: skip


# --------------------------------------------- finite-source prefill queue ----

FINITE_SOURCE_NS = (2, 4, 8, 16, 64)
FINITE_SOURCE_RHO = 0.6


@dataclass(frozen=True)
class FiniteSourceRow:
    n: int
    think: float
    rho: float
    wait_exact: float  # exact M/M/1//N mean wait in queue
    wait_sim: Estimate  # simulated mean response (wait + service)
    wait_open: float  # open M/M/1 wait at the same throughput


@cache
def finite_source_scenario() -> tuple[FiniteSourceRow, ...]:
    mu = 1.0
    rows = []
    for n in FINITE_SOURCE_NS:
        nu = finite_source_nu_for_utilization(n, mu, FINITE_SOURCE_RHO)
        _, x, wq = finite_source_mm1(n, nu, mu)
        cfg = BatchConfig.poisson_turns(1.0, exp(1.0 / mu), Fifo(), 400_000.0, 300 + n)
        cfg.population = agentic.Closed(n)
        cfg.classes[0].resume_prob = 1.0
        cfg.classes[0].tool_time = exp(1.0 / nu)
        r = batch.simulate(cfg)
        rho = x / mu
        rows.append(
            FiniteSourceRow(
                n, 1.0 / nu, rho, wq, batch_means([t - 0.0 for _, t in r.responses], 20),
                rho / (mu * (1.0 - rho)),
            )
        )  # fmt: skip
    return tuple(rows)


def finite_source_wait_below_open() -> Check:
    """With N live sessions the prefill queue is a finite-source system; the
    open M/M/1 wait at the same utilisation is above the exact one for every
    N, with the gap closing as N grows."""
    ok, obs, prev = True, [], math.inf
    for r in finite_source_scenario():
        resp_exact = r.wait_exact + 1.0
        ok &= r.wait_sim.agrees_with(resp_exact, 0.02)
        ratio = r.wait_open / r.wait_exact
        ok &= ratio >= 1.0 and ratio <= prev + 1e-9
        prev = ratio
        obs.append(
            f"N={r.n}: Z={fixed(r.think, 1)}s ρ={fixed(r.rho, 2)} R sim {r.wait_sim} exact {fixed(resp_exact, 3)}; "
            f"W_q exact {fixed(r.wait_exact, 3)} open {fixed(r.wait_open, 3)} (×{fixed(ratio, 2)})"
        )
    return Check(
        "finite_source_wait_below_open", "sec:batch, prop:price, sec:limits", ["missPrice_upper"],
        Kind.InModel,
        "with N live sessions the prefill queue is a finite-source system; the open M/G/1 wait at the same utilisation is an upper bound that tightens as N grows",
        f"simulated response within CI (+2%) of the exact M/M/1//N value; open/exact wait ratio ≥ 1 and nonincreasing in N at ρ = {disp(FINITE_SOURCE_RHO)}",
        "; ".join(obs), ok,
    )  # fmt: skip


# ---------------------------------------------------------- observations -


@dataclass
class Observation:
    id: str
    paper: str
    question: str
    result: str


def mixed_workload(n: int, seed: int, ev: EvictionPolicy) -> AgenticConfig:
    """Two-class mix: agents (p=0.95, short context) and one-shot long
    documents (p=0.2, long context), on a 400k-token pool."""
    cfg = AgenticConfig.example(n, 4.0e5)
    cfg.classes = [
        ProgramClass(1.0, 0.95, Uniform(4_000.0, 8_000.0), exp(800.0), exp(300.0), exp(3.0)),
        ProgramClass(1.0, 0.2, Uniform(30_000.0, 60_000.0), exp(500.0), exp(300.0), exp(3.0)),
    ]
    cfg.eviction = ev
    cfg.seed = seed
    return cfg


def pd_step_limits() -> Observation:
    """What the split pays for beyond the baseline (serQ #208 variations):
    a transfer in the TTFT, a decode engine short of KV, colocated engines
    short of KV, and prompts of squared coefficient of variation 9."""
    lines = []
    bw = serq.parallel(
        lambda s: pd_batching.simulate_step(
            StepConfig(True, 60.0, s, prompt_len=PD_FIXED_PROMPT, sets={"Bw": 2e5, "x0": 0.002})
        ),
        PD_SEEDS,
    )
    lines.append(
        f"NICs of 2e5 tokens/s after 2 ms, λ=60 split: read {_ms(replications([r.transfer for r in bw]))} "
        f"inside TTFT {_ms(replications([r.ttft for r in bw]))}, TPOT {_ms(replications([r.tpot_token for r in bw]))}"
    )
    kvd = serq.parallel(
        lambda s: pd_batching.simulate_step(
            StepConfig(True, 40.0, s, prompt_len=PD_FIXED_PROMPT, sets={"blocksD": 512.0})
        ),
        PD_SEEDS,
    )
    lines.append(
        f"decode engine of 8192 KV tokens, λ=40 split: admission wait {_ms(replications([r.admit_wait for r in kvd]))}, "
        f"{replications([r.preemptions_per_s for r in kvd])} preemptions/s, "
        f"{fixed(replications([r.prefill_kv_used for r in kvd]).mean, 0)} KV tokens held on the prefill engines (running prefills and leases awaiting the read), "
        f"TTFT {_ms(replications([r.ttft for r in kvd]))}"
    )
    kve = serq.parallel(
        lambda s: pd_batching.simulate_step(
            StepConfig(False, 60.0, s, prompt_len=PD_FIXED_PROMPT, sets={"blocksE": 512.0})
        ),
        PD_SEEDS,
    )
    lines.append(
        f"colocated engines of 8192 KV tokens each, λ=60: {replications([r.preemptions_per_s for r in kve])} preemptions/s, "
        f"TTFT {_ms(replications([r.ttft for r in kve]))}"
    )
    for rate in (40.0, 60.0):
        pairs = serq.parallel(
            lambda s, rate=rate: (
                pd_batching.simulate_step(StepConfig(False, rate, s, prompt_len=H2_PROMPT)),
                pd_batching.simulate_step(StepConfig(True, rate, s, prompt_len=H2_PROMPT)),
            ),
            PD_SEEDS,
        )
        lines.append(
            f"prompts of CV² 9, λ={disp(rate)}: TTFT {_ms(replications([c.ttft for c, _ in pairs]))} colocated vs "
            f"{_ms(replications([d.ttft for _, d in pairs]))} split, response "
            f"{_ms(replications([c.response for c, _ in pairs]))} vs {_ms(replications([d.response for _, d in pairs]))} "
            f"(300 s runs; the split's prefill engines are near saturation at λ=60, so these are not steady-state means)"
        )
    return Observation(
        "pd_step_limits", "issue #28 (serQ #208 variations)",
        "what the split pays for beyond the baseline: the transfer, a bounded KV, prompt variance",
        "; ".join(lines),
    )  # fmt: skip


def observations() -> list[Observation]:
    """Results that bear on the paper's open questions (§7) but test no
    proposition."""
    E = EvictionPolicy
    out = []
    lines = []
    for n in (16, 24, 32):
        cells = []
        for ev in (E.ShortestFirst, E.Density, E.Priced, E.Lru):
            xs = [agentic.simulate(mixed_workload(n, s, ev)).throughput for s in range(1, 6)]
            cells.append(f"{ev.value} {replications(xs)}")
        lines.append(f"N={n}: {', '.join(cells)}")
    out.append(
        Observation(
            "dynamic_eviction", "prop:blind, sec:exp-evict",
            "Offline, the density rule beats SF by a wide margin when p_i vary. Does that, or the congestion-priced order q_i Φ_i / c_i, carry over to a closed system where evictions repeat and freed memory is reused? (Two classes: agent p=0.95 short context; one-shot p=0.2 long context. Throughput turns/s, 5 seeds.)",
            "; ".join(lines),
        )
    )  # fmt: skip
    lines = []
    for rate in (0.05, 0.08):
        for ev in (E.ShortestFirst, E.Density):
            cfg = mixed_workload(0, 1, ev)
            cfg.population = Open(rate)
            cfg.kv_capacity = 2.5e5
            cfg.max_context = 1.25e5
            cfg.horizon = 40_500.0
            r = agentic.simulate(cfg)
            lines.append(
                f"{disp(rate)}/s {ev.value}: hit {fixed(r.hit_rate, 3)} ρ {fixed(r.utilization, 2)} "
                f"CV² {fixed(r.service.cv2(), 1)} Wq {r.wait} PK {fixed(r.pk_wait_prediction(), 3)}"
            )
    out.append(
        Observation(
            "pk_on_agentic_turns", "sec:congestion, sec:limits",
            "Turn arrivals of agent programs are not Poisson and hits are correlated with memory state. How far is PK (fed the measured λ and service moments) from the simulated wait?",
            "; ".join(lines),
        )
    )  # fmt: skip
    lines = []
    for rate in (1.0, 1.6, 1.9):
        ra, rd = pd_latency_pair(rate)
        lines.append(f"λ={disp(rate)}: agg {ra.latency} vs PD {rd.latency}")
    out.append(
        Observation(
            "pd_latency_at_equal_capacity", "prop:pd (ii)",
            "At the rate-matched split PD and aggregation have equal capacity (N=8, s_P=1, s_D=3, capacity 2/s). Do they have equal latency?",
            "; ".join(lines),
        )
    )  # fmt: skip
    out.append(pd_step_limits())
    return out


@cache
def pd_latency_pair(rate: float) -> tuple[pd.PdReport, pd.PdReport]:
    """Aggregated vs the rate-matched split at equal capacity (N=8)."""
    a = PdConfig.from_means(
        8, Aggregated(), Poisson(rate), 1.0, 3.0, 0.0, (1.0, 1.0), math.inf, 1.0
    )
    a.requests = 100_000
    a.warmup = 10_000
    d = a.copy(mode=Disaggregated(2))
    return pd.simulate(a), pd.simulate(d)


ALL = (
    mm1_response_time,
    mm1_blowup,
    pk_formula,
    variance_orders_delay,
    cache_reuse_lowers_delay,
    cv2_ratio,
    miss_price_bracket,
    prefill_pays_the_miss,
    ps_insensitivity,
    bcmp_feedback,
    ps_price_bracket,
    footprint_batch_size,
    lps_vs_saturating_phi,
    kingman_bursty_arrivals,
    little_law,
    closed_throughput_falls_with_concurrency,
    closed_throughput_nondecreasing_fixed_demand,
    interactive_response_time_law,
    always_offload_can_be_worse,
    selective_offload_never_worse,
    shortest_first_counterexample,
    shortest_first_two_approx,
    shortest_first_tightness,
    shortest_first_unbounded_with_resume_prob,
    guarded_density_two_approx,
    memory_threshold_rule,
    pd_capacity_matches,
    pd_no_gain,
    pd_win_condition_decisions,
    pd_ps_scaling_identity,
    pd_step_split_tpot_at_equal_throughput,
    pd_step_long_step_matches_ps_share,
    pd_step_interruption_pattern,
    affinity_breaks_at_high_load,
    lookahead_not_worse_than_affinity,
    trace_replay_variance_sources,
    inversion_load_closed_form,
    inversion_load_rises_with_move_cost,
    finite_source_wait_below_open,
)


def all_checks() -> list[Check]:
    """Every check, in paper order."""
    return [f() for f in ALL]

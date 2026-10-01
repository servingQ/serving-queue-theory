"""serQ programs against the closed forms the paper proves, and the model
adapters against alternate serQ scenarios."""

import pytest

from sim import agentic, batch, pd, pd_batching, queue, routing, serq
from sim.agentic import AgenticConfig, Closed
from sim.batch import BatchConfig, Fifo, Ps
from sim.pd import Aggregated, Disaggregated, PdConfig, Poisson, Saturated
from sim.pd_batching import PsConfig, StepConfig
from sim.queue import QueueConfig
from sim.routing import RoutePolicy, RoutingConfig
from sim.stats import Estimate
from theory.analytic import finite_source_mm1, mm1_wait, pk_wait
from theory.batch import Saturating
from theory.dist import (
    Bernoulli,
    Deterministic,
    HitMiss,
    HyperExp,
    discrete,
    exp,
    hyperexp_balanced,
)
from theory.pd import split_capacity
from theory.queue import lindley_waits

EXAMPLES_PRESENT = serq.EXAMPLES.exists()
pytestmark = pytest.mark.skipif(
    not EXAMPLES_PRESENT, reason="serQ checkout missing: run `make serq`"
)


def ci(o: serq.Observe) -> Estimate:
    return Estimate(o.mean, o.ci)


def program(name, sets, seed, horizon=None):
    return serq.run(serq.program_path(name), sets=sets, seed=seed, horizon=horizon)


# --------------------------------------------------------- closed forms --


def test_mm1_sojourn_is_one_over_mu_minus_lambda():
    for i, lam in enumerate([0.5, 0.8, 0.9]):
        r = program("mg1", {"lam": lam, "law": 1}, 10 + i)
        o = r.observe("sojourn")
        assert ci(o).agrees_with(mm1_wait(1.0, lam), 0.02)
        l = r.stage("svc").mean_number
        assert abs(l - lam * o.mean) / l < 0.03


def test_pk_wait_for_four_service_laws():
    lam = 0.8
    for law, m2 in [(0, 1.0), (1, 2.0), (2, 1.25), (3, 5.0)]:
        r = program("mg1", {"law": law, "cv2": 4}, 3)
        assert ci(r.observe("wait")).agrees_with(pk_wait(lam, m2, lam), 0.03), law


def test_ps_mean_number_is_insensitive():
    lam = 0.7
    want = lam / (1.0 - lam)
    for law in [0, 1, 3]:
        r = program("ps", {"law": law}, 5)
        assert abs(r.stage("svc").mean_number - want) / want < 0.03
        assert ci(r.observe("sojourn")).agrees_with(want / lam, 0.03)


def test_finite_source_wait_matches_mva():
    for n in [2, 8, 32]:
        r = program("closed", {"N": n}, 7)
        l, x, wq = finite_source_mm1(n, 1.0 / 4.0, 1.0)
        assert ci(r.observe("wait")).agrees_with(wq, 0.05)
        svc = r.stage("svc")
        assert abs(svc.throughput - x) / x < 0.03
        assert abs(svc.mean_number - l) / l < 0.05


# ------------------------------------------------------ replica and PD --

STEP = """
let a = 2e-5; let omega = 2e-4;
stage engine : step {{ budget max(decoders, omega / a); cost max(omega, tokens * a); }}
workload {{ arrive poisson({lam}); init {{ set t0 = now; }} }}
session {{ run engine {work}; observe {obs} = now - t0; end; }}
run {{ horizon {h}; warmup {w}; seed {seed}; }}
"""


def test_step_prefill_alone_is_md1():
    lam = 0.7
    r = serq.run(
        source=STEP.format(lam=lam, work="prefill (1 / a)", obs="sojourn", h=3000, w=300, seed=8)
    )
    assert ci(r.observe("sojourn")).agrees_with(1.0 + lam / (2.0 * (1.0 - lam)), 0.03)


def test_step_decode_is_infinite_server_at_zero_context():
    r = serq.run(
        source=STEP.format(lam=3.0, work="decode (500)", obs="response", h=2000, w=200, seed=9)
    )
    assert abs(r.observe("response").mean - 0.1) < 1e-3
    assert abs(r.stage("engine").mean_number - 0.3) < 0.02


def test_pd_tandem_capacity():
    agg = program("pd_tandem", {"mode": 0}, 2)
    want = 32.0 / (1.0 + 1.0 + 0.5)
    assert abs(agg.stage("agg").throughput - want) / want < 0.02
    for np_, bnet in [(10, 1000.0), (11, 1000.0), (12, 1000.0), (11, 10.0)]:
        want = split_capacity(32, np_, 1.0, 1.0, 2.0, 1.0, bnet, 1.0)
        r = program("pd_tandem", {"mode": 1, "NP": np_, "bnet": bnet}, 3)
        assert abs(r.stage("decode").throughput - want) / want < 0.02


def test_lecture_pd_program_runs():
    # the lecture's figure, kept here since serQ took it out of its examples
    # (vrvrv/serQ#121): a KV transfer as a store-and-forward link
    r = serq.run(serq.PROGRAMS / "lecture_pd.sq", sets={}, seed=1)
    assert r.turns > 500
    p = r.stage("prefill")
    assert p.utilization < 0.95
    assert r.observe("ttft").mean >= p.mean_wait + p.mean_service + r.pool("memP").mean_wait - 1e-6
    assert r.observe("miss").mean < 0.5


def test_ps_capacity_matches_batch_ps_server():
    lam = 2.0
    cfg = BatchConfig.poisson_turns(lam, exp(1.0), Ps(Saturating(0.0, 8)), 20000.0, 4)
    b = batch.simulate(cfg)
    src = f"""
        stage svc : ps(min(present, 8));
        workload {{ arrive poisson({lam}); init {{ set t0 = now; }} }}
        session {{ run svc (~exp(1)); observe response = now - t0; end; }}
        run {{ horizon 20000; warmup 1000; seed 4; }}
    """
    a = serq.run(source=src).observe("response").mean
    assert abs(a - b.response.mean()) / b.response.mean() < 0.05


def test_pd_single_device_aggregated_capacity():
    cfg = PdConfig.from_means(
        1, Aggregated(), Saturated(4), 0.3, 0.7, 0.0, (1.0, 1.0), float("inf"), 1.0
    )
    cfg.requests, cfg.warmup = 50_000, 1_000
    r = pd.simulate(cfg)
    assert abs(r.throughput - 1.0) < 0.02 and r.station_utilization[0] > 0.99


def test_pd_open_poisson_load_uses_the_serq_program():
    cfg = PdConfig.from_means(
        8, Disaggregated(2), Poisson(1.5), 1.0, 3.0, 0.0, (1.0, 1.0), float("inf"), 1.0
    )
    cfg.requests, cfg.warmup = 5_000, 500
    r = pd.simulate(cfg)
    assert len(r.latencies) == cfg.requests
    assert 1.2 < r.throughput < 1.8
    assert all(0.0 <= u <= 1.0 for u in r.station_utilization)


# ---------------------------------------------------------------- queue --


def test_engine_agrees_with_lindley():
    cfg = QueueConfig.mg1(0.8, hyperexp_balanced(1.0, 5.0), 50_000, 3)
    des = queue.simulate(cfg)
    lin = lindley_waits(cfg.interarrival, cfg.service, cfg.customers, cfg.warmup, cfg.seed)
    assert len(des.waits) == len(lin)
    assert max(abs(a - b) for a, b in zip(des.waits.tolist(), lin, strict=True)) < 1e-8


def test_deterministic_underload_never_waits():
    cfg = QueueConfig(Deterministic(1.0), Deterministic(0.5), 1, 1000, 10, 0)
    r = queue.simulate(cfg)
    assert (r.waits == 0.0).all()
    assert abs(r.utilization - 0.5) < 1e-3


def test_ttft_stops_after_prefill():
    cfg = BatchConfig.poisson_turns(0.1, Deterministic(2.0), Fifo(), 100.0, 1)
    cfg.population = Closed(1)
    cfg.classes[0].resume_prob = 1.0
    cfg.classes[0].tool_time = Deterministic(10.0)
    cfg.prefill, cfg.decode = Deterministic(2.0), Deterministic(3.0)
    r = batch.simulate(cfg)
    assert abs(r.ttft.mean() - 2.0) < 1e-9
    assert abs(r.response.mean() - 5.0) < 1e-9


# -------------------------------------------------------------- routing --


def test_affinity_and_myopic_match_the_serq_example():
    for code, pol in [
        (0, RoutePolicy.Affinity),
        (3, RoutePolicy.Myopic),
        (4, RoutePolicy.Lookahead),
    ]:
        for rate in [0.6, 1.2]:
            theirs = routing.simulate(RoutingConfig.example(rate, pol))
            ours = program("routing", {"policy": code, "rate": rate}, 1)
            a, b = ours.observe("response").mean, theirs.response.mean
            assert abs(a - b) / b < 0.12
            assert abs(ours.observe("hitrate").mean - theirs.hit_rate) < 0.05


def test_routing_adapter_renders_distribution_samples_in_serq():
    cfg = RoutingConfig.example(0.6, RoutePolicy.Lookahead)
    cfg.cls.initial_tokens = discrete([5_000.0, 15_000.0], [0.25, 0.75])
    cfg.cls.new_tokens = HitMiss(0.8, 100.0, 1_000.0)
    cfg.cls.output_tokens = Bernoulli(0.5)
    cfg.cls.tool_time = HyperExp(0.25, 0.5, 4.5)
    r = routing.simulate(cfg)
    assert len(r.utilization) == cfg.replicas and r.turns > 0
    assert r.response.mean == r.response.mean and r.mean_context > 0.0


# -------------------------------------------------------------- agentic --


def test_agentic_programs_agree_statistically():
    for programs, kv in [(16, 1.0e9), (32, 3.0e5), (48, 3.0e5)]:
        ours, theirs = [], []
        for s in range(1, 5):
            cfg = AgenticConfig.example(programs, kv)
            cfg.seed = s
            if kv > 1e8:
                cfg.max_context = 2.0e5
            r = agentic.simulate(cfg)
            theirs.append((r.throughput, r.hit_rate, r.response.mean()))
            o = serq.run(
                serq.PROGRAMS / "agentic.sq",
                sets={"N": programs, "C": kv, "maxctx": cfg.max_context},
                seed=s,
            )
            ours.append(
                (o.stage("svc").throughput, o.observe("hit").mean, o.observe("response").mean)
            )

        def mean(xs, k):
            return sum(x[k] for x in xs) / len(xs)

        assert abs(mean(ours, 0) - mean(theirs, 0)) / mean(theirs, 0) < 0.05
        assert abs(mean(ours, 1) - mean(theirs, 1)) < 0.05
        assert abs(mean(ours, 2) - mean(theirs, 2)) / mean(theirs, 2) < 0.10


def test_pd_batching_modes_draw_the_same_requests():
    # the two modes of pd_batching.sq share the request stream of a seed:
    # the output tokens of the requests both ended agree, so the output
    # throughputs do within the requests in flight at the end
    c = pd_batching.simulate_step(StepConfig(False, 40.0, 7, horizon=60.0, warmup=6.0))
    d = pd_batching.simulate_step(StepConfig(True, 40.0, 7, horizon=60.0, warmup=6.0))
    assert c.stable and d.stable
    assert abs(c.output_tokens_per_s - d.output_tokens_per_s) / c.output_tokens_per_s < 0.02
    assert d.tpot_token < c.tpot_token and c.ttft < d.ttft
    assert 0.0 < c.prefill_share < 1.0 and c.idle_share > 0.0
    assert d.transfer < 1e-6 and d.admit_wait >= 0.0  # a hand-over over NICs of 1e15 tokens/s
    assert 0.0 < c.prefill_busy < 1.0 and 0.0 < d.prefill_busy < 1.0


def test_pd_batching_edits_the_program_lines_it_cannot_set():
    text = pd_batching._program_text(StepConfig(False, 40.0, 1, exclusive=False, prefill_engines=2))
    assert pd_batching.EXCLUSIVE_LINE not in text and "let NP = 2;" in text
    assert (
        pd_batching._program_text(StepConfig(False, 40.0, 1))
        == serq.program_path("pd_batching").read_text()
    )


def test_pd_ps_is_little_consistent():
    r = pd_batching.simulate_ps(PsConfig(True, 10.0, 3, horizon=120.0, warmup=12.0))
    # L = λ W at the pooled station, with the time in the station the decode time
    assert abs(r.decoding_per_station - 10.0 * r.decode_time) / r.decoding_per_station < 0.05
    assert r.tpot_token <= r.tpot_request * 1.05  # a short answer's TPOT weighs more per request

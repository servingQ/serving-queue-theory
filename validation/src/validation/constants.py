"""Constants shared by the scenarios and the table generator.

The cost model of the replay scenarios is calibrated on the NPU testbed
(paper §4.3): the prefill terms are the cost-fit experiment's least-squares
fit (`data/exp/e1/fit.json`, `scripts/exp/fit_e1.py`; `scripts/check_sim.sh`
checks these constants against that file) and the decode iteration time is
the mean inter-token latency of the lightest long-context replay (cap 8),
which did not vary with the context over 30k–90k tokens, so `β = 0`.
"""

CAL_PREFILL_LINEAR = 1.94e-4  # a, s per new token
CAL_PREFILL_QUADRATIC = 6.51e-9  # b, s per token², K_c = a/b ≈ 30k
CAL_PREFILL_OVERHEAD = 0.044  # c0, s per request
CAL_DECODE_STEP = 0.057  # ω, s per decode iteration

# Open-session eviction and admission experiment.
OPEN_SEEDS = 20
OPEN_CAP = 24  # default cap on live sessions
OPEN_CAPS = (16, 24, 32)  # admission caps of the sweep

# Trace replay (§4.2).
TRACE_RATES = (0.0005, 0.001)  # session arrival rates (per s)
# KV pools (tokens); inf = no eviction. They hold about ten, five and two or
# three finished sessions of the corpus (mean final context 3.9·10^5).
TRACE_POOLS = (float("inf"), 4.0e6, 2.0e6, 1.0e6)
TRACE_SEEDS = 5
TRACE_WARMUP = 6_000.0
TRACE_HORIZON = 66_000.0
# Admission caps as multiples of `pool / mean final context`: tight, loose.
TRACE_CAP_FACTORS = (0.8, 1.6)
TRACE_CAP_OPEN = 24
TRACE_PRICE_DELTAS = (0.01, 0.03, 0.1)  # forced-miss shares

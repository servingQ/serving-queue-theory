//! §4.2's trace replay (paper `sec:sim`) on a replica with the vLLM v1
//! engine's rules: the seQ program `programs/replay_vllm.seq`, run
//! in-process by the `seq` crate, on the production sessions of
//! [`crate::workload::TraceCorpus::weka`].
//!
//! The program is the replica of `validation::trace_replay_cfg` (same
//! corpus, Poisson session arrivals, live-session cap, batch cap 8, RBLN
//! cost fit, eviction by price per byte-second) with the engine rules that
//! the request-for-request comparison of seQ against the real vLLM
//! scheduler established: admission by the engine at iteration start with
//! the budget left, a whole-prompt admission gate with chunk-wise KV growth
//! and LIFO preemption, 16-token blocks evicted from an entry's tail, reuse
//! bounded by the previous turn's computed full blocks, and a finished
//! session's blocks kept (`docs/seq-replay42.md`). The rows are the ones of
//! `validation::trace_row` and `validation::trace_price_row`, computed with
//! the same definitions from the program's per-turn observations: a turn
//! hits iff it reuses its whole reusable prefix (else it is a miss, often a
//! partial one); prefill service in stage time is `work / availability`,
//! the availability being the share of the iteration budget the decoding
//! turns leave (as in `models::batch`); the prefill wait is the time to
//! first token less that service (one FIFO server); the mean number in the
//! prefill stage `L_P` is the TTFT rate (Little's law). Simulator output on a replayed workload, not a
//! measurement.

use std::collections::BTreeMap;
use std::path::Path;

use seq::{Overrides, Report, parser};

use crate::analytic::{finite_source_price, miss_price};
use crate::models::agentic::EvictionPolicy;
use crate::stats::replications;
use crate::validation::{
    CAL_DECODE_STEP, CAL_PREFILL_LINEAR, TRACE_CAP_FACTORS, TRACE_CAP_OPEN, TRACE_HORIZON,
    TRACE_POOLS, TRACE_RATES, TRACE_WARMUP, TracePriceRow, TraceRow, trace_cap,
};
use crate::workload::TraceCorpus;

/// The program, relative to this crate.
pub const PROGRAM: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../programs/replay_vllm.seq");
/// Seeds per replay cell and per forced-miss cell.
pub const SEEDS: u64 = 20;
pub const PRICE_SEEDS: u64 = 20;
/// KV block size of the program (tokens).
pub const BLOCK_TOKENS: f64 = 16.0;

/// One run's inputs.
#[derive(Clone, Debug)]
struct Cell {
    rate: f64,
    kv: f64,
    cap: usize,
    delta: f64,
    /// Corpus file and its scheduler estimates `p`, `τ` (the price key).
    trace: Option<String>,
    p: f64,
    tau: f64,
}

fn run(c: &Cell, seed: u64) -> Report {
    let e = |v: f64| parser::parse_expr(&format!("{v:e}")).expect("number");
    let lets = vec![
        ("Lambda".to_string(), e(c.rate)),
        ("cap".to_string(), e(c.cap as f64)),
        (
            "C".to_string(),
            e(if c.kv.is_finite() { c.kv } else { 1e15 }),
        ),
        ("delta".to_string(), e(c.delta)),
        ("p".to_string(), e(c.p)),
        ("tau".to_string(), e(c.tau)),
    ];
    let ov = Overrides {
        lets,
        seed: Some(seed),
        horizon: Some(TRACE_HORIZON),
        warmup: Some(TRACE_WARMUP),
        trace: c.trace.clone(),
    };
    let path = Path::new(PROGRAM);
    let prog = seq::load(path, &ov).unwrap_or_else(|e| panic!("{PROGRAM}: {e}"));
    let base = if ov.trace.is_some() {
        None
    } else {
        path.parent()
    };
    seq::run_ir(&prog, base).unwrap_or_else(|e| panic!("{PROGRAM}: {e}"))
}

/// Run every seed of a cell, in parallel (each run is independent and
/// deterministic, so the results do not depend on the thread count).
fn runs(c: &Cell, seeds: u64) -> Vec<Report> {
    std::thread::scope(|s| {
        let hs: Vec<_> = (1..=seeds)
            .map(|seed| s.spawn(move || run(c, seed)))
            .collect();
        hs.into_iter().map(|h| h.join().expect("run")).collect()
    })
}

/// Per-turn observations of a run, by (session, turn).
fn by_turn(r: &Report, name: &str) -> BTreeMap<(u64, u32), f64> {
    let o = r
        .observe(name)
        .unwrap_or_else(|| panic!("no observation `{name}`"));
    o.records
        .iter()
        .zip(&o.samples)
        .map(|(&(_, s, k), &v)| ((s, k), v))
        .collect()
}

fn mean_obs(r: &Report, name: &str) -> f64 {
    let o = r.observe(name).unwrap();
    if o.count == 0 { 0.0 } else { o.mean }
}

/// The prefill queue of one run, in stage time.
struct Queue {
    n: usize,
    lam: f64,
    es: f64,
    es2: f64,
    rho: f64,
    avail: f64,
    wait: f64,
    l_p: f64,
}

fn queue(r: &Report) -> Queue {
    let window = TRACE_HORIZON - TRACE_WARMUP;
    let (kind, work, ttft, done) = (
        by_turn(r, "kind"),
        by_turn(r, "work"),
        by_turn(r, "ttft"),
        by_turn(r, "done"),
    );
    // turns with every observation after the warm-up (a turn that straddles
    // it has only some)
    let keys: Vec<_> = kind
        .keys()
        .filter(|k| ttft.contains_key(k) && work.contains_key(k) && done.contains_key(k))
        .copied()
        .collect();
    // Availability for prefill as in `models::batch`: the share of an
    // iteration's token budget the decoding turns leave, `1 - L_D/B` with
    // `L_D` the time-average number decoding (Little: decode time per
    // second) and `B = floor(ω/a)` the budget in tokens.
    let budget = (CAL_DECODE_STEP / CAL_PREFILL_LINEAR).floor();
    let l_d = keys.iter().map(|k| done[k] - ttft[k]).sum::<f64>() / window;
    let avail = (1.0 - l_d / budget).clamp(0.05, 1.0);
    let n = keys.len();
    let (mut s1, mut s2, mut t) = (0.0, 0.0, 0.0);
    for k in &keys {
        let st = work[k] / avail;
        s1 += st;
        s2 += st * st;
        t += ttft[k];
    }
    let lam = n as f64 / window;
    let nn = n.max(1) as f64;
    let (es, es2) = (s1 / nn, s2 / nn);
    Queue {
        n,
        lam,
        es,
        es2,
        rho: lam * es,
        avail,
        // one FIFO server: the time to first token less the turn's own service
        wait: (t - s1) / nn,
        l_p: t / window,
    }
}

fn trace_row_of(c: &Cell) -> TraceRow {
    struct One {
        hit: f64,
        reused: f64,
        live: f64,
        entry: f64,
        rho: f64,
        cv2: f64,
        share: f64,
        wait: f64,
        pk: f64,
        ttft: f64,
        p99: f64,
        lp: f64,
        avail: f64,
        trunc: f64,
        x: f64,
    }
    let window = TRACE_HORIZON - TRACE_WARMUP;
    let ones: Vec<One> = runs(c, SEEDS)
        .iter()
        .map(|r| {
            let q = queue(r);
            let (kind, work) = (by_turn(r, "kind"), by_turn(r, "work"));
            let (mut h, mut m) = (vec![], vec![]);
            for (k, &v) in kind.iter().filter(|(k, _)| work.contains_key(k)) {
                match v as i64 {
                    1 => h.push(work[k]),
                    2 => m.push(work[k]),
                    _ => {}
                }
            }
            let mv = |xs: &[f64]| -> (f64, f64) {
                if xs.is_empty() {
                    return (0.0, 0.0);
                }
                let mu = xs.iter().sum::<f64>() / xs.len() as f64;
                let var = if xs.len() > 1 {
                    xs.iter().map(|x| (x - mu).powi(2)).sum::<f64>() / (xs.len() - 1) as f64
                } else {
                    0.0
                };
                (mu, var)
            };
            let p = h.len() as f64 / (h.len() + m.len()).max(1) as f64;
            let ((mh, vh), (mm, vm)) = (mv(&h), mv(&m));
            let between = p * (1.0 - p) * (mm - mh).powi(2);
            let var = between + p * vh + (1.0 - p) * vm;
            let mean = p * mh + (1.0 - p) * mm;
            let ttft = r.observe("ttft").unwrap();
            One {
                hit: mean_obs(r, "hit"),
                reused: mean_obs(r, "reused"),
                live: r.pool("live").unwrap().mean_holders,
                entry: mean_obs(r, "entry_wait"),
                rho: q.rho,
                cv2: if mean > 0.0 { var / (mean * mean) } else { 0.0 },
                share: if var > 0.0 { between / var } else { 0.0 },
                wait: q.wait,
                pk: if q.rho < 1.0 {
                    q.lam * q.es2 / (2.0 * (1.0 - q.rho))
                } else {
                    f64::INFINITY
                },
                ttft: ttft.mean,
                p99: ttft.p99,
                lp: q.l_p,
                avail: q.avail,
                trunc: r.observe("trunc").unwrap().count as f64,
                x: r.turns as f64 / window,
            }
        })
        .collect();
    let est = |f: fn(&One) -> f64| replications(&ones.iter().map(f).collect::<Vec<_>>());
    TraceRow {
        rate: c.rate,
        kv: c.kv,
        cap: c.cap,
        policy: EvictionPolicy::PricedMemoryBlocks,
        hit_rate: est(|o| o.hit),
        reused: est(|o| o.reused),
        sessions: est(|o| o.live),
        entry_wait: est(|o| o.entry),
        rho: est(|o| o.rho),
        cv2: est(|o| o.cv2),
        mixture_share: est(|o| o.share),
        wait: est(|o| o.wait),
        pk_wait: est(|o| o.pk),
        ttft: est(|o| o.ttft),
        ttft_p99: est(|o| o.p99),
        prefill_number: est(|o| o.lp),
        availability: est(|o| o.avail),
        truncated: est(|o| o.trunc),
        throughput: est(|o| o.x),
    }
}

fn weka_cell(rate: f64, kv: f64, cap: usize, delta: f64, corpus: &TraceCorpus) -> Cell {
    Cell {
        rate,
        kv,
        cap,
        delta,
        trace: None,
        p: corpus.resume_fraction(),
        tau: corpus.mean_think(),
    }
}

/// One cell of §4.2's replay table on the WEKA corpus.
pub fn trace_row(rate: f64, kv: f64, cap: usize) -> TraceRow {
    trace_row_of(&weka_cell(rate, kv, cap, 0.0, &TraceCorpus::weka()))
}

/// Every cell of §4.2's replay table.
pub fn trace_replay_scenario() -> Vec<TraceRow> {
    let corpus = TraceCorpus::weka();
    let mut rows = vec![];
    for rate in TRACE_RATES {
        rows.push(trace_row_of(&weka_cell(
            rate,
            f64::INFINITY,
            TRACE_CAP_OPEN,
            0.0,
            &corpus,
        )));
    }
    let rate = TRACE_RATES[TRACE_RATES.len() - 1];
    for kv in TRACE_POOLS.iter().copied().filter(|k| k.is_finite()) {
        for f in TRACE_CAP_FACTORS {
            let cap = trace_cap(&corpus, kv, f);
            rows.push(trace_row_of(&weka_cell(rate, kv, cap, 0.0, &corpus)));
        }
    }
    rows
}

/// §4.2's forced-miss table, as `validation::trace_price_row`: with no pool
/// limit, a share `delta` of follow-up turns reuses nothing (a nonce at the
/// head of the prompt; the old blocks stay). The bracket of Prop. price is
/// computed from the baseline's measured `λ`, `E[S²]`, `ρ` in stage time
/// and each forced turn's own `S^miss` (its work) and `S^hit` (the work had
/// it reused its reusable prefix).
pub fn trace_price_row(rate: f64, delta: f64) -> TracePriceRow {
    let corpus = TraceCorpus::weka();
    let window = TRACE_HORIZON - TRACE_WARMUP;
    let base = runs(
        &weka_cell(rate, f64::INFINITY, TRACE_CAP_OPEN, 0.0, &corpus),
        PRICE_SEEDS,
    );
    let forced = runs(
        &weka_cell(rate, f64::INFINITY, TRACE_CAP_OPEN, delta, &corpus),
        PRICE_SEEDS,
    );
    let mut dl = vec![];
    let (mut lo_sum, mut rho_sum, mut live_sum, mut hit_sum) = (0.0, 0.0, 0.0, 0.0);
    let (mut rho1_sum, mut live1_sum, mut lp_sum, mut fin_sum) = (0.0, 0.0, 0.0, 0.0);
    for (r0, r1) in base.iter().zip(&forced) {
        let q0 = queue(r0);
        let q1 = queue(r1);
        let (f, work, whit) = (
            by_turn(r1, "forced"),
            by_turn(r1, "work"),
            by_turn(r1, "whit"),
        );
        let (mut phi_sum, mut ds_sum) = (0.0, 0.0);
        for (k, &fm) in &f {
            if fm < 1.0 || !work.contains_key(k) || !whit.contains_key(k) {
                continue;
            }
            let s_miss = work[k] / q0.avail;
            let s_hit = whit[k] / q0.avail;
            phi_sum += miss_price(q0.lam, q0.es2, q0.rho, s_hit, s_miss);
            ds_sum += s_miss - s_hit;
        }
        let live0 = r0.pool("live").unwrap().mean_holders;
        let n_live = live0.round().max(1.0) as usize;
        let es1 = q0.es + ds_sum / q0.n.max(1) as f64;
        fin_sum += finite_source_price(n_live, corpus.mean_think(), q0.es, es1);
        dl.push(q1.l_p - q0.l_p);
        lo_sum += phi_sum / window;
        rho_sum += q0.rho;
        rho1_sum += q0.rho + ds_sum / window;
        live_sum += live0;
        live1_sum += r1.pool("live").unwrap().mean_holders;
        lp_sum += q0.l_p;
        hit_sum += mean_obs(r1, "hit");
    }
    let k = PRICE_SEEDS as f64;
    let (rho_m, rho1_m) = (rho_sum / k, rho1_sum / k);
    let hi = if rho1_m < 1.0 {
        (1.0 - rho_m) / (1.0 - rho1_m) * lo_sum / k
    } else {
        f64::INFINITY
    };
    TracePriceRow {
        rate,
        delta,
        rho: rho_m,
        live: live_sum / k,
        rho1: rho1_m,
        live1: live1_sum / k,
        l_p: lp_sum / k,
        dl_p: replications(&dl),
        lo: lo_sum / k,
        hi,
        finite: fin_sum / k,
        hit_rate: hit_sum / k,
    }
}

/// §4.2's split-rule sensitivity, as `validation::trace_split_scenario`.
pub fn trace_split_scenario() -> Vec<(String, TraceRow, f64, f64)> {
    let data = concat!(env!("CARGO_MANIFEST_DIR"), "/data");
    let mut out = vec![];
    for (name, corpus, file) in [
        ("10 min", TraceCorpus::weka(), "weka-sessions.csv"),
        (
            "30 min",
            TraceCorpus::weka_split_30min(),
            "weka-sessions-1800.csv",
        ),
    ] {
        let mut c = weka_cell(TRACE_RATES[0], f64::INFINITY, TRACE_CAP_OPEN, 0.0, &corpus);
        c.trace = Some(format!("{data}/{file}"));
        out.push((
            name.to_string(),
            trace_row_of(&c),
            corpus.mean_turns(),
            corpus.mean_think(),
        ));
    }
    out
}

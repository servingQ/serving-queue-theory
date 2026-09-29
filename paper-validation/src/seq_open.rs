//! The synthetic eviction and admission experiment of the paper (App. B,
//! `tab:sim-evict-dyn`, `tab:sim-admission`, `fig:sim-admission`) on a
//! replica with the vLLM v1 engine's rules: the seQ program
//! `programs/open_vllm.seq`, run in-process by the `seq` crate.
//!
//! The workload is the two-class one of `validation::open_session_cfg`;
//! the engine rules are those of `programs/replay_vllm.seq` (admission by
//! the engine with the budget left, whole-prompt gate, chunk-wise KV growth
//! with LIFO preemption, 16-token blocks evicted from an entry's tail); the
//! time model is the testbed's cost fit, whose decode iteration of
//! `CAL_DECODE_STEP` seconds makes the arrival rates two orders of
//! magnitude lower than in the uncalibrated paper-validation scenario. Every
//! policy is run with the end of a session known (its blocks dropped), so
//! that the eviction order is the only difference; LRU (vLLM's order) and
//! the byte-second price are also run with the end unknown, as vLLM's
//! engine is (a finished session's blocks stay and look like a session in
//! a tool call). Simulator output on a synthetic workload, not a
//! measurement.

use std::path::Path;

use seq::{Overrides, Report, frontend::parser};

use crate::models::agentic::EvictionPolicy;
use crate::stats::replications;
use crate::validation::{
    CAL_DECODE_STEP, CAL_PREFILL_LINEAR, OPEN_CAP, OPEN_CAPS, OPEN_SEEDS, OpenEvictRow,
};

/// The program, relative to this crate.
pub const PROGRAM: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../programs/open_vllm.seq");
/// Session arrival rates (per s): at the default cap and with the priced
/// order, the first is at the edge of the eviction window (hit rate about
/// 0.95, some seeds degrade) and the second deep inside it (about 0.75).
pub const RATES: [f64; 2] = [0.03, 0.05];
pub const HORIZON: f64 = 21_000.0;
pub const WARMUP: f64 = 1_000.0;
/// All policies, run at the default cap with the end known.
pub const POLICIES: [EvictionPolicy; 6] = [
    EvictionPolicy::ShortestFirst,
    EvictionPolicy::Density,
    EvictionPolicy::Priced,
    EvictionPolicy::PricedMemory,
    EvictionPolicy::PricedMemoryBlocks,
    EvictionPolicy::Lru,
];
/// Also run at the default cap with the end unknown (vLLM's engine).
pub const END_UNKNOWN: [EvictionPolicy; 2] = [EvictionPolicy::Lru, EvictionPolicy::PricedMemory];
/// Run at the other caps of the sweep.
pub const SWEEP: [EvictionPolicy; 3] = [
    EvictionPolicy::ShortestFirst,
    EvictionPolicy::Density,
    EvictionPolicy::PricedMemory,
];

fn policy_code(p: EvictionPolicy) -> f64 {
    match p {
        EvictionPolicy::ShortestFirst => 0.0,
        EvictionPolicy::Density => 1.0,
        EvictionPolicy::Priced => 2.0,
        EvictionPolicy::PricedMemory => 3.0,
        EvictionPolicy::PricedMemoryBlocks => 4.0,
        EvictionPolicy::Lru => 5.0,
        other => panic!("{other:?} is not in open_vllm.seq"),
    }
}

fn run(cap: usize, rate: f64, policy: EvictionPolicy, end_known: bool, seed: u64) -> Report {
    let e = |v: f64| parser::parse_expr(&format!("{v:e}")).expect("number");
    let ov = Overrides {
        lets: vec![
            ("Lambda".to_string(), e(rate)),
            ("cap".to_string(), e(cap as f64)),
            ("policy".to_string(), e(policy_code(policy))),
            ("keep".to_string(), e(if end_known { 0.0 } else { 1.0 })),
        ],
        seed: Some(seed),
        horizon: Some(HORIZON),
        warmup: Some(WARMUP),
        arrivals: None,
        trace: None,
    };
    let path = Path::new(PROGRAM);
    let prog = seq::load(path, &ov).unwrap_or_else(|e| panic!("{PROGRAM}: {e}"));
    seq::run_ir(&prog, path.parent()).unwrap_or_else(|e| panic!("{PROGRAM}: {e}"))
}

/// One (cap, load, policy, end rule) cell over [`OPEN_SEEDS`] seeds.
pub fn open_row(cap: usize, rate: f64, policy: EvictionPolicy, end_known: bool) -> OpenEvictRow {
    let window = HORIZON - WARMUP;
    let budget = (CAL_DECODE_STEP / CAL_PREFILL_LINEAR).floor();
    let rs: Vec<Report> = std::thread::scope(|s| {
        let hs: Vec<_> = (1..=OPEN_SEEDS)
            .map(|seed| s.spawn(move || run(cap, rate, policy, end_known, seed)))
            .collect();
        hs.into_iter().map(|h| h.join().expect("run")).collect()
    });
    struct One {
        x: f64,
        hit: f64,
        ttft: f64,
        ttft_p99: f64,
        response: f64,
        p99: f64,
        avail: f64,
        entry: f64,
        reused: f64,
    }
    let ones: Vec<One> = rs
        .iter()
        .map(|r| {
            let ttft = r.observe("ttft").unwrap();
            let resp = r.observe("response").unwrap();
            let entry = r.observe("entry_wait").unwrap();
            let hit = r.observe("hit").unwrap();
            let reused = r.observe("reused").unwrap();
            // decode time per second (Little: the mean number decoding)
            let l_d =
                (resp.samples.iter().sum::<f64>() - ttft.samples.iter().sum::<f64>()) / window;
            One {
                x: resp.count as f64 / window,
                hit: if hit.count > 0 { hit.mean } else { 1.0 },
                ttft: ttft.mean,
                ttft_p99: ttft.p99,
                response: resp.mean,
                p99: resp.p99,
                avail: (1.0 - l_d / budget).clamp(0.05, 1.0),
                entry: if entry.count > 0 { entry.mean } else { 0.0 },
                reused: if reused.count > 0 { reused.mean } else { 1.0 },
            }
        })
        .collect();
    let est = |f: fn(&One) -> f64| replications(&ones.iter().map(f).collect::<Vec<_>>());
    OpenEvictRow {
        cap,
        rate,
        policy,
        end_known,
        throughput: est(|o| o.x),
        hit_rate: est(|o| o.hit),
        ttft: est(|o| o.ttft),
        ttft_p99: est(|o| o.ttft_p99),
        response: est(|o| o.response),
        p99: est(|o| o.p99),
        availability: est(|o| o.avail),
        entry_wait: est(|o| o.entry),
        // under block eviction a miss is often partial: a seed thrashes when
        // follow-up turns reuse less than half of their reusable prefix
        collapsed: ones.iter().filter(|o| o.reused < 0.5).count(),
    }
}

/// Every cell: all policies at the default cap with the end known, LRU and
/// the byte-second price there with the end unknown, [`SWEEP`] at the other
/// caps with the end known; both loads.
pub fn eviction_open_scenario() -> Vec<OpenEvictRow> {
    let mut cells = vec![];
    for cap in OPEN_CAPS {
        for rate in RATES {
            if cap == OPEN_CAP {
                cells.extend(POLICIES.iter().map(|&p| (cap, rate, p, true)));
                cells.extend(END_UNKNOWN.iter().map(|&p| (cap, rate, p, false)));
            } else {
                cells.extend(SWEEP.iter().map(|&p| (cap, rate, p, true)));
            }
        }
    }
    cells
        .into_iter()
        .map(|(cap, rate, p, end)| open_row(cap, rate, p, end))
        .collect()
}

//! Where the price of a miss is paid, on a replica with the vLLM v1
//! engine's rules: the seQ program `programs/price_vllm.seq`, run
//! in-process by the `seq` crate (Props. price and decode; the check
//! `validation::prefill_pays_the_miss`, `tab:sim-ps` rows 8-9).
//!
//! Poisson turns with no memory limit and the testbed's cost model. A turn
//! prefills [`HIT_TOKENS`] (a hit) or [`MISS_TOKENS`] (a miss), decided by
//! one uniform draw at arrival, so that the run with a share `δ` of forced
//! misses sees the same arrivals and draws (common random numbers; the
//! differences are paired by turn). The prefill stage is the engine's
//! prefill in the budget the decoding turns leave: its mean availability
//! `r̄ = 1 - L_D/B` (`L_D` the time-average number decoding, `B` the
//! iteration budget in tokens) turns work into stage time, as in the
//! paper's §2.2. Simulator output, not a measurement.

use std::path::Path;

use seq::{Overrides, Report, parser};

use crate::analytic::{miss_price, num_in_system};
use crate::models::batch::paired_differences;
use crate::stats::{Estimate, batch_means};
use crate::validation::{CAL_DECODE_STEP, CAL_PREFILL_LINEAR, CAL_PREFILL_QUADRATIC};

/// The program, relative to this crate.
pub const PROGRAM: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../programs/price_vllm.seq");
/// Tokens prefilled by a hit and by a miss, and the baseline miss share.
pub const HIT_TOKENS: f64 = 512.0;
pub const MISS_TOKENS: f64 = 5120.0;
pub const MISS_SHARE: f64 = 0.2;
/// Prefill load of the baseline, `λ E[P]`.
pub const LOAD: f64 = 0.6;
pub const HORIZON: f64 = 500_000.0;
pub const WARMUP: f64 = 2_000.0;

/// Prefill work (s) of `n` tokens on an empty context.
fn work(n: f64) -> f64 {
    CAL_PREFILL_LINEAR * n + CAL_PREFILL_QUADRATIC * n * n / 2.0
}

/// Turn arrival rate of the scenario.
pub fn rate() -> f64 {
    LOAD / ((1.0 - MISS_SHARE) * work(HIT_TOKENS) + MISS_SHARE * work(MISS_TOKENS))
}

fn run(delta: f64) -> Report {
    let e = |v: f64| parser::parse_expr(&format!("{v:e}")).expect("number");
    let ov = Overrides {
        lets: vec![
            ("Lambda".to_string(), e(rate())),
            ("pmiss".to_string(), e(MISS_SHARE)),
            ("delta".to_string(), e(delta)),
            ("hitn".to_string(), e(HIT_TOKENS)),
            ("missn".to_string(), e(MISS_TOKENS)),
        ],
        seed: Some(1),
        horizon: Some(HORIZON),
        warmup: Some(WARMUP),
        trace: None,
    };
    let path = Path::new(PROGRAM);
    let prog = seq::load(path, &ov).unwrap_or_else(|e| panic!("{PROGRAM}: {e}"));
    seq::run_ir(&prog, path.parent()).unwrap_or_else(|e| panic!("{PROGRAM}: {e}"))
}

/// An observation per turn, sorted by turn (session serial).
fn per_turn(r: &Report, name: &str) -> Vec<(u64, f64)> {
    let o = r
        .observe(name)
        .unwrap_or_else(|| panic!("no observation `{name}`"));
    let mut v: Vec<(u64, f64)> = o
        .records
        .iter()
        .zip(&o.samples)
        .map(|(&(_, s, _), &x)| (s, x))
        .collect();
    v.sort_by_key(|x| x.0);
    v
}

/// The turns with both observations, paired: (serial, a, b).
fn pair(a: &[(u64, f64)], b: &[(u64, f64)]) -> Vec<(u64, f64, f64)> {
    let (mut i, mut j, mut out) = (0, 0, vec![]);
    while i < a.len() && j < b.len() {
        match a[i].0.cmp(&b[j].0) {
            std::cmp::Ordering::Less => i += 1,
            std::cmp::Ordering::Greater => j += 1,
            std::cmp::Ordering::Equal => {
                out.push((a[i].0, a[i].1, b[j].1));
                i += 1;
                j += 1;
            }
        }
    }
    out
}

/// One `δ` of the scenario.
#[derive(Clone, Debug)]
pub struct PriceRun {
    /// Mean prefill availability of the baseline run, `r̄`.
    pub avail: f64,
    /// Effective prefill load `λE[P]/r̄` of the baseline.
    pub rho_p: f64,
    /// Baseline mean number in the prefill stage, `λ·TTFT`, and the M/G/1
    /// prediction at service `P/r̄`.
    pub l_p: Estimate,
    pub l_p_theory: f64,
    /// Rise of the prefill-stage number, `λ·ΔTTFT` (paired).
    pub dl_p: Estimate,
    /// Bracket `[λδΦ, (1-ρ)/(1-ρ')·λδΦ]` with `Φ = missPrice` at service
    /// `P/r̄`.
    pub lo: f64,
    pub hi: f64,
    /// Change of the decode-stage number, `λ·Δ(R - TTFT)` (paired), and its
    /// baseline level `λ·E[R - TTFT]`.
    pub dl_d: Estimate,
    pub l_d: Estimate,
}

pub fn price_scenario(delta: f64) -> PriceRun {
    let window = HORIZON - WARMUP;
    let budget = (CAL_DECODE_STEP / CAL_PREFILL_LINEAR).floor();
    let (r0, r1) = std::thread::scope(|s| {
        let a = s.spawn(|| run(0.0));
        let b = s.spawn(move || run(delta));
        (a.join().expect("run"), b.join().expect("run"))
    });
    let (t0, t1) = (per_turn(&r0, "ttft"), per_turn(&r1, "ttft"));
    let (w0, resp0, resp1) = (
        per_turn(&r0, "work"),
        per_turn(&r0, "response"),
        per_turn(&r1, "response"),
    );
    let lam = t0.len() as f64 / window;
    let scale = |xs: Vec<f64>| xs.into_iter().map(|x| lam * x).collect::<Vec<_>>();
    // decode time per turn, R - TTFT
    let dec = |t: &[(u64, f64)], r: &[(u64, f64)]| -> Vec<(u64, f64)> {
        pair(t, r).into_iter().map(|(s, t, r)| (s, r - t)).collect()
    };
    let (d0, d1) = (dec(&t0, &resp0), dec(&t1, &resp1));
    let l_d_mean = d0.iter().map(|x| x.1).sum::<f64>() / window;
    let avail = (1.0 - l_d_mean / budget).clamp(0.05, 1.0);
    let n = w0.len() as f64;
    let ep = w0.iter().map(|x| x.1).sum::<f64>() / n / avail;
    let m2 = w0.iter().map(|x| x.1 * x.1).sum::<f64>() / n / (avail * avail);
    let rho = lam * ep;
    let (s_h, s_m) = (work(HIT_TOKENS) / avail, work(MISS_TOKENS) / avail);
    let phi = miss_price(lam, m2, rho, s_h, s_m);
    let lo = lam * delta * phi;
    let rho1 = rho + lam * delta * (s_m - s_h);
    PriceRun {
        avail,
        rho_p: rho,
        l_p: batch_means(&scale(t0.iter().map(|x| x.1).collect()), 20),
        l_p_theory: num_in_system(lam, m2, rho),
        dl_p: batch_means(&scale(paired_differences(&t0, &t1)), 20),
        lo,
        hi: if rho1 < 1.0 {
            (1.0 - rho) / (1.0 - rho1) * lo
        } else {
            f64::INFINITY
        },
        dl_d: batch_means(&scale(paired_differences(&d0, &d1)), 20),
        l_d: batch_means(&scale(d0.iter().map(|x| x.1).collect()), 20),
    }
}

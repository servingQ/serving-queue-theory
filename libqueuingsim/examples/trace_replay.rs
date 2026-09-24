//! Explore the trace-replay scenario (paper §4.1): print one line per
//! (rate, pool) cell. `cargo run --release --example trace_replay [rate ...]`.

use libqueuingsim::models::agentic::EvictionPolicy;
use libqueuingsim::validation::{
    TRACE_CAP_FACTORS, TRACE_CAP_OPEN, TRACE_POOLS, TRACE_RATES, trace_cap, trace_row,
};
use libqueuingsim::workload::TraceCorpus;
use std::sync::Arc;

fn main() {
    let corpus = Arc::new(TraceCorpus::weka());
    eprintln!(
        "corpus: {} sessions, {} turns, mean turns {:.1}, resume {:.3}, mean think {:.1}s, mean final context {:.0}",
        corpus.sessions.len(),
        corpus.turns(),
        corpus.mean_turns(),
        corpus.resume_fraction(),
        corpus.mean_think(),
        corpus.mean_final_context()
    );
    let rates: Vec<f64> = std::env::args()
        .skip(1)
        .map(|a| a.parse().expect("rate"))
        .collect();
    let rates = if rates.is_empty() {
        TRACE_RATES.to_vec()
    } else {
        rates
    };
    let mut cells = vec![];
    for rate in rates {
        cells.push((
            rate,
            f64::INFINITY,
            TRACE_CAP_OPEN,
            EvictionPolicy::PricedMemory,
        ));
        for kv in TRACE_POOLS.iter().copied().filter(|k| k.is_finite()) {
            for f in TRACE_CAP_FACTORS {
                cells.push((
                    rate,
                    kv,
                    trace_cap(&corpus, kv, f),
                    EvictionPolicy::PricedMemory,
                ));
            }
            cells.push((
                rate,
                kv,
                trace_cap(&corpus, kv, TRACE_CAP_FACTORS[1]),
                EvictionPolicy::PricedMemoryBlocks,
            ));
        }
    }
    for (rate, kv, cap, ev) in cells {
        {
            let t = std::time::Instant::now();
            let r = trace_row(&corpus, rate, kv, cap, ev);
            println!(
                "Λ={rate} pool={:>8} cap={cap:>2} {ev:?}: hit {:.3}±{:.3} live {:.1} entry {:.0}s ρ {:.2} avail {:.2} CV² {:.1} mix {:.2}±{:.2} Wq {:.2} PK {:.2} TTFT {:.2} p99 {:.1} L_P {:.2} trunc {:.0} ({:.0}s)",
                if kv.is_finite() {
                    format!("{:.1e}", kv)
                } else {
                    "inf".into()
                },
                r.hit_rate.mean,
                r.hit_rate.half_width,
                r.sessions.mean,
                r.entry_wait.mean,
                r.rho.mean,
                r.availability.mean,
                r.cv2.mean,
                r.mixture_share.mean,
                r.mixture_share.half_width,
                r.wait.mean,
                r.pk_wait.mean,
                r.ttft.mean,
                r.ttft_p99.mean,
                r.prefill_number.mean,
                r.truncated.mean,
                t.elapsed().as_secs_f64()
            );
        }
    }
}

//! Prop. price on the replayed workload: forced misses vs the bracket.
//! `cargo run --release --example trace_price [rate ...]`
use libqueuingsim::validation::trace_price_row;
use libqueuingsim::workload::TraceCorpus;
use std::sync::Arc;

fn main() {
    let corpus = Arc::new(TraceCorpus::weka());
    let rates: Vec<f64> = std::env::args()
        .skip(1)
        .map(|a| a.parse().expect("rate"))
        .collect();
    let rates = if rates.is_empty() {
        vec![0.005, 0.01]
    } else {
        rates
    };
    for rate in rates {
        for delta in [0.01, 0.03, 0.1] {
            let r = trace_price_row(&corpus, rate, delta);
            println!(
                "Λ={rate} δ={delta}: ρ {:.2} live {:.1} hit {:.3} ΔL_P {} bracket [{:.3}, {:.3}] ratio ΔL_P/lo {:.2}",
                r.rho,
                r.live,
                r.hit_rate,
                r.dl_p,
                r.lo,
                r.hi,
                r.dl_p.mean / r.lo
            );
        }
    }
}

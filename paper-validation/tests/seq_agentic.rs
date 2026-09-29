//! Compare the paper-specific agentic seQ program with an alternate seQ
//! scenario over independent random streams.

use paper_validation::models::agentic::{self, AgenticConfig};
use seq::{Overrides, run_file};
use std::path::Path;

fn mean(xs: &[f64]) -> f64 {
    xs.iter().sum::<f64>() / xs.len() as f64
}

#[test]
fn agentic_programs_agree_statistically() {
    for (programs, kv) in [(16usize, 1.0e9), (32, 3.0e5), (48, 3.0e5)] {
        let mut ours = (vec![], vec![], vec![]);
        let mut theirs = (vec![], vec![], vec![]);
        for seed in 1..=4u64 {
            let mut cfg = AgenticConfig::example(programs, kv);
            cfg.seed = seed;
            if kv > 1e8 {
                cfg.max_context = 2.0e5;
            }
            let r = agentic::simulate(&cfg);
            theirs.0.push(r.throughput);
            theirs.1.push(r.hit_rate);
            theirs.2.push(r.response.mean());
            let sets = [
                format!("N={programs}"),
                format!("C={kv}"),
                format!("maxctx={}", cfg.max_context),
            ];
            // The reference scenario belongs to this paper; seQ removed it
            // from its general example set when examples were reorganized.
            let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("../programs/agentic.seq");
            let o = run_file(
                &path,
                &Overrides {
                    lets: sets
                        .iter()
                        .map(|set| {
                            let (name, value) = set.split_once('=').expect("name=expr");
                            (
                                name.to_string(),
                                seq::frontend::parser::parse_expr(value)
                                    .expect("override expression"),
                            )
                        })
                        .collect(),
                    seed: Some(seed),
                    ..Default::default()
                },
            )
            .expect("paper agentic program");
            ours.0.push(o.stage("svc").unwrap().throughput);
            ours.1.push(o.observe("hit").unwrap().mean);
            ours.2.push(o.observe("response").unwrap().mean);
        }
        let (x0, x1) = (mean(&ours.0), mean(&theirs.0));
        let (h0, h1) = (mean(&ours.1), mean(&theirs.1));
        let (r0, r1) = (mean(&ours.2), mean(&theirs.2));
        eprintln!(
            "N={programs} C={kv}: throughput {x0:.4} vs {x1:.4}, hit {h0:.3} vs {h1:.3}, response {r0:.3} vs {r1:.3}"
        );
        assert!((x0 - x1).abs() / x1 < 0.05, "throughput {x0} vs {x1}");
        assert!((h0 - h1).abs() < 0.05, "hit rate {h0} vs {h1}");
        assert!((r0 - r1).abs() / r1 < 0.10, "response {r0} vs {r1}");
    }
}

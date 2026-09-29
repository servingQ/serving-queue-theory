//! Small conversions shared by Rust configuration adapters and seQ programs.

use crate::Dist;

pub(crate) fn number(x: f64) -> String {
    format!("{x:.17e}")
}

/// Render every shared distribution as an expression in seQ's sampler.
pub(crate) fn sample_expr(dist: &Dist) -> String {
    match dist {
        Dist::Deterministic(x) => format!("~det({})", number(*x)),
        Dist::Exponential { mean } => format!("~exp({})", number(*mean)),
        Dist::Erlang { k, mean } => format!("~erlang({k}, {})", number(*mean)),
        Dist::HyperExp { p, mean1, mean2 } => format!(
            "(~bernoulli({}) ? ~exp({}) : ~exp({}))",
            number(*p),
            number(*mean1),
            number(*mean2)
        ),
        Dist::Uniform { lo, hi } => {
            format!("~uniform({}, {})", number(*lo), number(*hi))
        }
        Dist::Discrete { values, probs } => {
            assert!(!values.is_empty() && values.len() == probs.len());
            let mut tail = number(*values.last().expect("nonempty"));
            let mut suffix_probability = *probs.last().expect("nonempty");
            for (&value, &prob) in values.iter().zip(probs).rev().skip(1) {
                suffix_probability += prob;
                if prob > 0.0 {
                    let conditional = prob / suffix_probability;
                    tail = format!(
                        "(~bernoulli({}) ? {} : {})",
                        number(conditional),
                        number(value),
                        tail
                    );
                }
            }
            tail
        }
        Dist::HitMiss { p_hit, hit, miss } => format!(
            "(~bernoulli({}) ? {} : {})",
            number(*p_hit),
            number(*hit),
            number(*miss)
        ),
        Dist::Bernoulli { p } => format!("~bernoulli({})", number(*p)),
    }
}

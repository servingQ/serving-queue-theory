//! Service-time and interarrival distributions with exact moments.
//!
//! Every variant reports `mean` and `second_moment` in closed form so a
//! simulation can be compared with the PK and Kingman formulas that consume
//! them.

use rand::Rng;

#[derive(Clone, Debug, PartialEq)]
pub enum Dist {
    /// Always `x`.
    Deterministic(f64),
    /// Exponential with the given mean.
    Exponential { mean: f64 },
    /// Sum of `k` i.i.d. exponentials, total mean `mean` (CV² = 1/k).
    Erlang { k: u32, mean: f64 },
    /// With probability `p` Exp(`mean1`), otherwise Exp(`mean2`) (CV² ≥ 1).
    HyperExp { p: f64, mean1: f64, mean2: f64 },
    /// Uniform on `[lo, hi]`.
    Uniform { lo: f64, hi: f64 },
    /// Finite discrete distribution, the `DiscreteService` of the Lean code.
    Discrete { values: Vec<f64>, probs: Vec<f64> },
    /// The hit/miss mixture of §2.2: `hit` w.p. `p_hit`, else `miss`.
    HitMiss { p_hit: f64, hit: f64, miss: f64 },
}

impl Dist {
    pub fn exp(mean: f64) -> Self {
        Dist::Exponential { mean }
    }

    /// Two-phase hyperexponential with balanced means and the requested
    /// mean and CV² (≥ 1). Used for bursty arrivals.
    pub fn hyperexp_balanced(mean: f64, cv2: f64) -> Self {
        assert!(cv2 >= 1.0, "hyperexponential needs CV² ≥ 1, got {cv2}");
        let p = 0.5 * (1.0 + ((cv2 - 1.0) / (cv2 + 1.0)).sqrt());
        Dist::HyperExp {
            p,
            mean1: mean / (2.0 * p),
            mean2: mean / (2.0 * (1.0 - p)),
        }
    }

    pub fn discrete(values: Vec<f64>, probs: Vec<f64>) -> Self {
        assert_eq!(values.len(), probs.len());
        let total: f64 = probs.iter().sum();
        assert!((total - 1.0).abs() < 1e-9, "probabilities sum to {total}");
        assert!(probs.iter().all(|&p| p >= 0.0));
        Dist::Discrete { values, probs }
    }

    pub fn sample<R: Rng + ?Sized>(&self, rng: &mut R) -> f64 {
        match self {
            Dist::Deterministic(x) => *x,
            Dist::Exponential { mean } => sample_exp(rng, *mean),
            Dist::Erlang { k, mean } => {
                let m = mean / *k as f64;
                (0..*k).map(|_| sample_exp(rng, m)).sum()
            }
            Dist::HyperExp { p, mean1, mean2 } => {
                let m = if rng.random::<f64>() < *p {
                    *mean1
                } else {
                    *mean2
                };
                sample_exp(rng, m)
            }
            Dist::Uniform { lo, hi } => lo + (hi - lo) * rng.random::<f64>(),
            Dist::Discrete { values, probs } => {
                let u: f64 = rng.random();
                let mut acc = 0.0;
                for (v, p) in values.iter().zip(probs) {
                    acc += p;
                    if u < acc {
                        return *v;
                    }
                }
                *values.last().expect("non-empty")
            }
            Dist::HitMiss { p_hit, hit, miss } => {
                if rng.random::<f64>() < *p_hit {
                    *hit
                } else {
                    *miss
                }
            }
        }
    }

    pub fn mean(&self) -> f64 {
        match self {
            Dist::Deterministic(x) => *x,
            Dist::Exponential { mean } | Dist::Erlang { mean, .. } => *mean,
            Dist::HyperExp { p, mean1, mean2 } => p * mean1 + (1.0 - p) * mean2,
            Dist::Uniform { lo, hi } => 0.5 * (lo + hi),
            Dist::Discrete { values, probs } => values.iter().zip(probs).map(|(v, p)| p * v).sum(),
            Dist::HitMiss { p_hit, hit, miss } => p_hit * hit + (1.0 - p_hit) * miss,
        }
    }

    /// `E[X^2]`.
    pub fn second_moment(&self) -> f64 {
        match self {
            Dist::Deterministic(x) => x * x,
            Dist::Exponential { mean } => 2.0 * mean * mean,
            Dist::Erlang { k, mean } => mean * mean * (1.0 + 1.0 / *k as f64),
            Dist::HyperExp { p, mean1, mean2 } => {
                2.0 * (p * mean1 * mean1 + (1.0 - p) * mean2 * mean2)
            }
            Dist::Uniform { lo, hi } => (lo * lo + lo * hi + hi * hi) / 3.0,
            Dist::Discrete { values, probs } => {
                values.iter().zip(probs).map(|(v, p)| p * v * v).sum()
            }
            Dist::HitMiss { p_hit, hit, miss } => p_hit * hit * hit + (1.0 - p_hit) * miss * miss,
        }
    }

    pub fn variance(&self) -> f64 {
        self.second_moment() - self.mean().powi(2)
    }

    pub fn cv2(&self) -> f64 {
        self.variance() / self.mean().powi(2)
    }
}

fn sample_exp<R: Rng + ?Sized>(rng: &mut R, mean: f64) -> f64 {
    // 1 - U lies in (0, 1], so the log is finite.
    -mean * (1.0 - rng.random::<f64>()).ln()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::stats::Welford;
    use rand::SeedableRng;
    use rand::rngs::StdRng;

    fn check(d: &Dist, n: usize, tol: f64) {
        let mut rng = StdRng::seed_from_u64(7);
        let mut w = Welford::new();
        (0..n).for_each(|_| w.push(d.sample(&mut rng)));
        let rel = |a: f64, b: f64| (a - b).abs() / b.abs().max(1e-12);
        assert!(rel(w.mean(), d.mean()) < tol, "{d:?}: mean {}", w.mean());
        assert!(
            rel(w.second_moment(), d.second_moment()) < 3.0 * tol,
            "{d:?}: m2 {} vs {}",
            w.second_moment(),
            d.second_moment()
        );
    }

    #[test]
    fn sample_moments_match_closed_forms() {
        let n = 400_000;
        check(&Dist::Deterministic(3.0), 10, 1e-12);
        check(&Dist::exp(2.0), n, 0.01);
        check(&Dist::Erlang { k: 4, mean: 1.0 }, n, 0.01);
        check(&Dist::hyperexp_balanced(1.0, 4.0), n, 0.02);
        check(&Dist::Uniform { lo: 1.0, hi: 3.0 }, n, 0.01);
        check(
            &Dist::discrete(vec![100.0, 3700.0], vec![0.75, 0.25]),
            n,
            0.02,
        );
        check(
            &Dist::HitMiss {
                p_hit: 0.8,
                hit: 0.05,
                miss: 0.5,
            },
            n,
            0.01,
        );
    }

    #[test]
    fn balanced_hyperexp_hits_target_cv2() {
        for c in [1.0, 2.0, 10.0, 50.0] {
            let d = Dist::hyperexp_balanced(3.0, c);
            assert!((d.mean() - 3.0).abs() < 1e-12);
            assert!((d.cv2() - c).abs() < 1e-9, "cv2 {} vs {c}", d.cv2());
        }
    }

    #[test]
    fn erlang_and_exponential_cv2() {
        assert!((Dist::exp(5.0).cv2() - 1.0).abs() < 1e-12);
        assert!((Dist::Erlang { k: 4, mean: 2.0 }.cv2() - 0.25).abs() < 1e-12);
        assert_eq!(Dist::Deterministic(1.0).cv2(), 0.0);
    }
}

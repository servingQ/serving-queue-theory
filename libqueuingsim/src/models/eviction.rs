//! Offline eviction instances (paper §3.1, Props. evict and guarded;
//! experiment E4 "O").
//!
//! Problem (evict): choose a subset of suspended programs with context
//! lengths `c_i` freeing at least `ΔC`, minimising `Σ w_i`. With
//! [`Item`], `w_i = p_i c_i²` (`p_i = 1` recovers ThunderAgent Def. 4.1);
//! with [`Weighted`], `w_i ≥ 0` is arbitrary (e.g. the congestion price
//! `p_i Φ_i` of paper Props. price and memory). [`optimal_weighted`] solves it exactly
//! by dynamic programming over freed tokens, so heuristics can be scored as
//! cost/OPT on many random instances.
//!
//! [`guarded_density`] is the guarded density greedy of paper
//! Prop. guarded (`guardedGreedy_two_approx` in DensityGreedy.lean): a
//! 2-approximation for arbitrary nonnegative weights, where plain
//! [`density_weighted`] has no constant ratio.

use rand::rngs::StdRng;
use rand::{Rng, SeedableRng};

/// A suspended program: context length and resume probability.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Item {
    pub c: u64,
    pub p: f64,
}

impl Item {
    pub fn uniform(c: u64) -> Self {
        Self { c, p: 1.0 }
    }

    /// Expected recompute cost `p c²` (`expectedEvictCost` in Eviction.lean).
    pub fn cost(&self) -> f64 {
        self.p * (self.c as f64).powi(2)
    }

    /// Cost per token freed, `p c` (`evictDensity` in Eviction.lean).
    pub fn density(&self) -> f64 {
        self.p * self.c as f64
    }
}

impl From<Item> for Weighted {
    fn from(it: Item) -> Self {
        Weighted {
            c: it.c,
            w: it.cost(),
        }
    }
}

/// A suspended program with an arbitrary nonnegative eviction weight.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Weighted {
    pub c: u64,
    pub w: f64,
}

impl Weighted {
    /// Weight per token freed, `w / c`.
    pub fn density(&self) -> f64 {
        self.w / self.c as f64
    }
}

/// `evictCost`: `Σ c²` (Eviction.lean).
pub fn evict_cost(s: &[u64]) -> u64 {
    s.iter().map(|c| c * c).sum()
}

/// `shortestFirst` exactly as defined in Eviction.lean: scan the list in
/// the given order, taking items until `ΔC` is covered.
pub fn shortest_first_lean(ctx: &[u64], delta: u64) -> Vec<u64> {
    match (ctx, delta) {
        (_, 0) | ([], _) => vec![],
        ([c, rest @ ..], d) => {
            if d <= *c {
                vec![*c]
            } else {
                let mut v = vec![*c];
                v.extend(shortest_first_lean(rest, d - c));
                v
            }
        }
    }
}

/// Take `order` until `delta` is freed. Returns indices into `items`.
fn take_until(items: &[Weighted], order: &[usize], delta: u64) -> Vec<usize> {
    let mut freed = 0;
    let mut out = vec![];
    for &i in order {
        if freed >= delta {
            break;
        }
        freed += items[i].c;
        out.push(i);
    }
    out
}

/// Indices sorted by increasing `key`, ties by index.
fn sorted_by_key(items: &[Weighted], key: impl Fn(&Weighted) -> f64) -> Vec<usize> {
    let mut order: Vec<usize> = (0..items.len()).collect();
    order.sort_by(|&a, &b| key(&items[a]).total_cmp(&key(&items[b])).then(a.cmp(&b)));
    order
}

fn weighted(items: &[Item]) -> Vec<Weighted> {
    items.iter().map(|&it| it.into()).collect()
}

/// Shortest-context-first (SF).
pub fn shortest_first(items: &[Item], delta: u64) -> Vec<usize> {
    shortest_first_weighted(&weighted(items), delta)
}

/// Increasing cost per token freed, `p_i c_i` (the relaxation's greedy).
pub fn density_first(items: &[Item], delta: u64) -> Vec<usize> {
    density_weighted(&weighted(items), delta)
}

/// SF on general weights (the order ignores the weights).
pub fn shortest_first_weighted(items: &[Weighted], delta: u64) -> Vec<usize> {
    take_until(items, &sorted_by_key(items, |it| it.c as f64), delta)
}

/// Plain density greedy: increasing `w_i / c_i` until `delta` is freed.
/// No constant ratio for general weights (see the tests).
pub fn density_weighted(items: &[Weighted], delta: u64) -> Vec<usize> {
    take_until(items, &sorted_by_key(items, Weighted::density), delta)
}

/// Guarded density greedy (paper Prop. guarded). For each candidate `e`,
/// the guess for the heaviest item of an optimum: if `c_e ≥ ΔC` the
/// candidate is `{e}`; otherwise restrict to items `j ≠ e` with
/// `w_j ≤ w_e` and take them in increasing `w_j / c_j` until
/// `c_e + freed ≥ ΔC` (skip `e` if that never happens). Return the cheapest
/// candidate. `None` iff evicting everything does not free `delta`.
/// `O(n² log n)`.
pub fn guarded_density(items: &[Weighted], delta: u64) -> Option<Vec<usize>> {
    if delta == 0 {
        return Some(vec![]);
    }
    let order = sorted_by_key(items, Weighted::density);
    let mut best: Option<(f64, Vec<usize>)> = None;
    for (e, it) in items.iter().enumerate() {
        let mut s = vec![e];
        let mut freed = it.c;
        for &j in &order {
            if freed >= delta {
                break;
            }
            if j != e && items[j].w <= it.w {
                freed += items[j].c;
                s.push(j);
            }
        }
        if freed < delta {
            continue;
        }
        let cost = weighted_cost(items, &s);
        if best.as_ref().is_none_or(|(b, _)| cost < *b) {
            best = Some((cost, s));
        }
    }
    best.map(|(_, s)| s)
}

/// [`guarded_density`] on `p_i c_i²` costs.
pub fn guarded_density_items(items: &[Item], delta: u64) -> Option<Vec<usize>> {
    guarded_density(&weighted(items), delta)
}

pub fn subset_cost(items: &[Item], s: &[usize]) -> f64 {
    s.iter().map(|&i| items[i].cost()).sum()
}

pub fn subset_freed(items: &[Item], s: &[usize]) -> u64 {
    s.iter().map(|&i| items[i].c).sum()
}

pub fn weighted_cost(items: &[Weighted], s: &[usize]) -> f64 {
    s.iter().map(|&i| items[i].w).sum()
}

pub fn weighted_freed(items: &[Weighted], s: &[usize]) -> u64 {
    s.iter().map(|&i| items[i].c).sum()
}

/// Exact optimum of (evict) by 0/1 covering-knapsack DP, `O(n·ΔC)` time
/// and space. Returns `None` if evicting everything does not free `delta`.
pub fn optimal(items: &[Item], delta: u64) -> Option<(f64, Vec<usize>)> {
    optimal_weighted(&weighted(items), delta)
}

/// [`optimal`] for arbitrary nonnegative weights.
pub fn optimal_weighted(items: &[Weighted], delta: u64) -> Option<(f64, Vec<usize>)> {
    let d = delta as usize;
    let n = items.len();
    // table[k][j]: min cost using items[..k] to free at least j tokens.
    let mut table = vec![vec![f64::INFINITY; d + 1]; n + 1];
    table[0][0] = 0.0;
    for (k, it) in items.iter().enumerate() {
        let c = it.c as usize;
        let w = it.w;
        for j in 0..=d {
            let skip = table[k][j];
            let with = table[k][j.saturating_sub(c)] + w;
            table[k + 1][j] = skip.min(with);
        }
    }
    let opt = table[n][d];
    if !opt.is_finite() {
        return None;
    }
    let mut s = vec![];
    let mut j = d;
    for k in (0..n).rev() {
        if table[k + 1][j] != table[k][j] {
            s.push(k);
            j = j.saturating_sub(items[k].c as usize);
        }
    }
    s.reverse();
    Some((opt, s))
}

/// How resume probabilities are drawn for random instances.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum ResumeModel {
    /// All `p_i = 1`: Def. 4.1 as posed; Prop. evict (ii) bounds SF by 2.
    Uniform,
    /// `p_i` i.i.d. uniform on `[lo, 1]`: Prop. evict (iii) regime.
    Varied { lo: f64 },
    /// Shorter programs are likelier to resume (`p_i` falls with `c_i`),
    /// the adversarial direction for SF. (When `p_i` rises with `c_i` the SF
    /// and density orders coincide.)
    ShorterResumes,
}

#[derive(Clone, Debug)]
pub struct Instance {
    pub items: Vec<Item>,
    pub delta: u64,
}

/// Random instance: `n` programs with `c_i` uniform on `1..=max_c`, and
/// `ΔC` a uniform fraction in `[0.1, 0.6]` of the total.
pub fn random_instance(rng: &mut StdRng, n: usize, max_c: u64, resume: ResumeModel) -> Instance {
    let items: Vec<Item> = (0..n)
        .map(|_| {
            let c = rng.random_range(1..=max_c);
            let p = match resume {
                ResumeModel::Uniform => 1.0,
                ResumeModel::Varied { lo } => rng.random_range(lo..=1.0),
                ResumeModel::ShorterResumes => {
                    let x = c as f64 / max_c as f64;
                    (1.0 - 0.95 * x * x).max(0.05)
                }
            };
            Item { c, p }
        })
        .collect();
    let total: u64 = items.iter().map(|i| i.c).sum();
    let frac = rng.random_range(0.1..=0.6);
    let delta = ((total as f64 * frac).round() as u64).max(1);
    Instance { items, delta }
}

/// A random instance with arbitrary weights, for Prop. guarded.
#[derive(Clone, Debug)]
pub struct WeightedInstance {
    pub items: Vec<Weighted>,
    pub delta: u64,
}

/// Random instance with weights independent of sizes: `c_i` uniform on
/// `1..=max_c`, `w_i` log-uniform on `[1e-4, 1e5]` (so near-free and very
/// heavy programs both occur), and `ΔC` a uniform fraction in `[0.1, 0.6]`
/// of the total.
pub fn random_weighted_instance(rng: &mut StdRng, n: usize, max_c: u64) -> WeightedInstance {
    let items: Vec<Weighted> = (0..n)
        .map(|_| Weighted {
            c: rng.random_range(1..=max_c),
            w: 10f64.powf(rng.random_range(-4.0..=5.0)),
        })
        .collect();
    let total: u64 = items.iter().map(|i| i.c).sum();
    let frac = rng.random_range(0.1..=0.6);
    let delta = ((total as f64 * frac).round() as u64).max(1);
    WeightedInstance { items, delta }
}

/// Cost/OPT of SF, of the density rule and of the guarded density greedy
/// on one instance.
#[derive(Clone, Copy, Debug)]
pub struct Ratios {
    pub shortest_first: f64,
    pub density_first: f64,
    pub guarded_density: f64,
}

pub fn ratios_weighted(items: &[Weighted], delta: u64) -> Ratios {
    let (opt, _) = optimal_weighted(items, delta).expect("feasible");
    let r = |s: Vec<usize>| {
        let c = weighted_cost(items, &s);
        if opt == 0.0 {
            if c == 0.0 { 1.0 } else { f64::INFINITY }
        } else {
            c / opt
        }
    };
    Ratios {
        shortest_first: r(shortest_first_weighted(items, delta)),
        density_first: r(density_weighted(items, delta)),
        guarded_density: r(guarded_density(items, delta).expect("feasible")),
    }
}

pub fn ratios(inst: &Instance) -> Ratios {
    ratios_weighted(&weighted(&inst.items), inst.delta)
}

/// Score the heuristics on `count` random instances.
pub fn sweep(count: usize, n: usize, max_c: u64, resume: ResumeModel, seed: u64) -> Vec<Ratios> {
    let mut rng = StdRng::seed_from_u64(seed);
    (0..count)
        .map(|_| ratios(&random_instance(&mut rng, n, max_c, resume)))
        .collect()
}

/// Score the heuristics on `count` random general-weight instances.
pub fn sweep_weighted(count: usize, n: usize, max_c: u64, seed: u64) -> Vec<Ratios> {
    let mut rng = StdRng::seed_from_u64(seed);
    (0..count)
        .map(|_| {
            let inst = random_weighted_instance(&mut rng, n, max_c);
            ratios_weighted(&inst.items, inst.delta)
        })
        .collect()
}

/// The family of `densityFirst_unbounded` (DensityGreedy.lean) on which
/// plain density greedy pays `K` against an optimum of 2:
/// `(c=1, w=0)`, `(c=K, w=K)`, `(c=1, w=2)` with `ΔC = 2` and `K ≥ 2`.
pub fn density_counterexample(k: u64) -> (Vec<Weighted>, u64) {
    assert!(k >= 2);
    (
        vec![
            Weighted { c: 1, w: 0.0 },
            Weighted { c: k, w: k as f64 },
            Weighted { c: 1, w: 2.0 },
        ],
        2,
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn items(cs: &[u64]) -> Vec<Item> {
        cs.iter().map(|&c| Item::uniform(c)).collect()
    }

    #[test]
    fn lean_definition_matches_greedy() {
        assert_eq!(shortest_first_lean(&[4, 5, 6], 6), vec![4, 5]);
        let mut rng = StdRng::seed_from_u64(0);
        for _ in 0..2000 {
            let inst = random_instance(&mut rng, 8, 30, ResumeModel::Uniform);
            let mut cs: Vec<u64> = inst.items.iter().map(|i| i.c).collect();
            cs.sort();
            let lean = shortest_first_lean(&cs, inst.delta);
            let mut ours: Vec<u64> = shortest_first(&inst.items, inst.delta)
                .into_iter()
                .map(|i| inst.items[i].c)
                .collect();
            ours.sort();
            assert_eq!(lean, ours);
        }
    }

    #[test]
    fn dp_matches_brute_force() {
        let mut rng = StdRng::seed_from_u64(1);
        for resume in [ResumeModel::Uniform, ResumeModel::Varied { lo: 0.05 }] {
            for _ in 0..500 {
                let inst = random_instance(&mut rng, 10, 25, resume);
                let n = inst.items.len();
                let brute = (0u32..1 << n)
                    .filter_map(|mask| {
                        let s: Vec<usize> = (0..n).filter(|i| mask >> i & 1 == 1).collect();
                        (subset_freed(&inst.items, &s) >= inst.delta)
                            .then(|| subset_cost(&inst.items, &s))
                    })
                    .fold(f64::INFINITY, f64::min);
                let (opt, s) = optimal(&inst.items, inst.delta).unwrap();
                assert!((opt - brute).abs() < 1e-9 * brute.max(1.0));
                assert!(subset_freed(&inst.items, &s) >= inst.delta);
                assert!((subset_cost(&inst.items, &s) - opt).abs() < 1e-9 * opt.max(1.0));
            }
        }
    }

    #[test]
    fn counterexample_of_prop_evict_i() {
        let it = items(&[4, 5, 6]);
        let sf = shortest_first(&it, 6);
        assert_eq!(subset_cost(&it, &sf), 41.0);
        let (opt, s) = optimal(&it, 6).unwrap();
        assert_eq!(opt, 36.0);
        assert_eq!(s, vec![2]);
    }

    fn brute_force(items: &[Weighted], delta: u64) -> f64 {
        let n = items.len();
        (0u32..1 << n)
            .filter_map(|mask| {
                let s: Vec<usize> = (0..n).filter(|i| mask >> i & 1 == 1).collect();
                (weighted_freed(items, &s) >= delta).then(|| weighted_cost(items, &s))
            })
            .fold(f64::INFINITY, f64::min)
    }

    #[test]
    fn guarded_is_two_approx_against_brute_force() {
        let mut rng = StdRng::seed_from_u64(11);
        let mut worst_plain: f64 = 0.0;
        for _ in 0..5000 {
            let n = rng.random_range(1..=10);
            let inst = random_weighted_instance(&mut rng, n, 25);
            let opt = brute_force(&inst.items, inst.delta);
            let (dp, _) = optimal_weighted(&inst.items, inst.delta).unwrap();
            assert!((dp - opt).abs() <= 1e-9 * opt.max(1.0));
            let g = guarded_density(&inst.items, inst.delta).unwrap();
            assert!(weighted_freed(&inst.items, &g) >= inst.delta);
            let cost = weighted_cost(&inst.items, &g);
            assert!(
                cost <= 2.0 * opt * (1.0 + 1e-12),
                "{inst:?}: {cost} vs {opt}"
            );
            let d = density_weighted(&inst.items, inst.delta);
            worst_plain = worst_plain.max(weighted_cost(&inst.items, &d) / opt);
        }
        assert!(worst_plain > 2.0, "plain density worst {worst_plain}");
    }

    #[test]
    fn guarded_is_two_approx_on_quadratic_costs() {
        let mut rng = StdRng::seed_from_u64(12);
        for resume in [ResumeModel::Uniform, ResumeModel::Varied { lo: 0.05 }] {
            for _ in 0..1000 {
                let inst = random_instance(&mut rng, 10, 25, resume);
                let r = ratios(&inst);
                assert!(r.guarded_density <= 2.0 + 1e-12);
            }
        }
    }

    #[test]
    fn plain_density_has_no_constant_ratio() {
        for k in [10u64, 100, 1000, 100_000] {
            let (it, delta) = density_counterexample(k);
            let d = density_weighted(&it, delta);
            assert_eq!(weighted_cost(&it, &d), k as f64);
            let (opt, _) = optimal_weighted(&it, delta).unwrap();
            assert_eq!(opt, 2.0);
            let g = guarded_density(&it, delta).unwrap();
            assert_eq!(weighted_cost(&it, &g), 2.0);
        }
    }

    #[test]
    fn guarded_infeasible_is_none() {
        let it = [Weighted { c: 1, w: 1.0 }, Weighted { c: 2, w: 1.0 }];
        assert!(guarded_density(&it, 4).is_none());
        assert_eq!(guarded_density(&it, 0), Some(vec![]));
    }

    #[test]
    fn infeasible_is_none() {
        assert!(optimal(&items(&[1, 2]), 4).is_none());
    }
}

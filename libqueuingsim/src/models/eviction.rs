//! Offline eviction instances (paper §3.2, Prop. evict; experiment E4 "O").
//!
//! Problem (evict): choose a subset of suspended programs with context
//! lengths `c_i` freeing at least `ΔC`, minimising `Σ w_i` where
//! `w_i = p_i c_i²` (`p_i = 1` recovers ThunderAgent Def. 4.1).
//! [`optimal`] solves it exactly by dynamic programming over freed tokens,
//! so heuristics can be scored as cost/OPT on many random instances.

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

/// Greedy eviction in increasing `key` order until `delta` is freed.
/// Returns indices into `items`.
fn greedy(items: &[Item], delta: u64, key: impl Fn(&Item) -> f64) -> Vec<usize> {
    let mut order: Vec<usize> = (0..items.len()).collect();
    order.sort_by(|&a, &b| key(&items[a]).total_cmp(&key(&items[b])).then(a.cmp(&b)));
    let mut freed = 0;
    let mut out = vec![];
    for i in order {
        if freed >= delta {
            break;
        }
        freed += items[i].c;
        out.push(i);
    }
    out
}

/// Shortest-context-first (SF).
pub fn shortest_first(items: &[Item], delta: u64) -> Vec<usize> {
    greedy(items, delta, |it| it.c as f64)
}

/// Increasing cost per token freed, `p_i c_i` (the relaxation's greedy).
pub fn density_first(items: &[Item], delta: u64) -> Vec<usize> {
    greedy(items, delta, Item::density)
}

pub fn subset_cost(items: &[Item], s: &[usize]) -> f64 {
    s.iter().map(|&i| items[i].cost()).sum()
}

pub fn subset_freed(items: &[Item], s: &[usize]) -> u64 {
    s.iter().map(|&i| items[i].c).sum()
}

/// Exact optimum of (evict) by 0/1 covering-knapsack DP, `O(n·ΔC)` time
/// and space. Returns `None` if evicting everything does not free `delta`.
pub fn optimal(items: &[Item], delta: u64) -> Option<(f64, Vec<usize>)> {
    let d = delta as usize;
    let n = items.len();
    // table[k][j]: min cost using items[..k] to free at least j tokens.
    let mut table = vec![vec![f64::INFINITY; d + 1]; n + 1];
    table[0][0] = 0.0;
    for (k, it) in items.iter().enumerate() {
        let c = it.c as usize;
        let w = it.cost();
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

/// Cost/OPT of SF and of the density rule on one instance.
#[derive(Clone, Copy, Debug)]
pub struct Ratios {
    pub shortest_first: f64,
    pub density_first: f64,
}

pub fn ratios(inst: &Instance) -> Ratios {
    let (opt, _) = optimal(&inst.items, inst.delta).expect("feasible");
    let r = |s: Vec<usize>| {
        let c = subset_cost(&inst.items, &s);
        if opt == 0.0 { 1.0 } else { c / opt }
    };
    Ratios {
        shortest_first: r(shortest_first(&inst.items, inst.delta)),
        density_first: r(density_first(&inst.items, inst.delta)),
    }
}

/// Score both heuristics on `count` random instances.
pub fn sweep(count: usize, n: usize, max_c: u64, resume: ResumeModel, seed: u64) -> Vec<Ratios> {
    let mut rng = StdRng::seed_from_u64(seed);
    (0..count)
        .map(|_| ratios(&random_instance(&mut rng, n, max_c, resume)))
        .collect()
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

    #[test]
    fn infeasible_is_none() {
        assert!(optimal(&items(&[1, 2]), 4).is_none());
    }
}

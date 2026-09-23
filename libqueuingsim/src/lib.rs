//! # libqueuingsim
//!
//! A discrete-event simulator for the models in `paper/main.tex`. The Lean
//! proofs in `lean/` establish the propositions *inside* their model; this
//! crate asks whether the decisions they imply survive once the model's
//! simplifications are dropped (non-Poisson arrivals, closed programs with
//! tool time, finite KV memory, tandem PD pools, load-dependent routing).
//!
//! | Module | Paper result it exercises |
//! |--------|---------------------------|
//! | [`models::queue`]    | Props. mm1, pk, cache; Ex. cv2; Kingman; Little |
//! | [`models::agentic`]  | §2 chain (eviction → p → E\[S\] → ρ), IRTL, Prop. option |
//! | [`models::eviction`] | Prop. evict (offline, exact optimum) |
//! | [`models::pd`]       | Prop. pd |
//! | [`models::routing`]  | Prop. routing |
//!
//! [`validation`] turns each proposition into a named, seeded check.
//! [`analytic`] mirrors the Lean definitions one-to-one so that simulated
//! quantities can be compared with the closed forms the paper proves things
//! about.
//!
//! Everything is seeded: the same `seed` gives bit-identical results, which
//! is what lets the statistical tests in `tests/` run in CI without flaking.
//! Simulated numbers are results *under the stated synthetic workload*; they
//! are not measurements of a real serving system.

pub mod analytic;
pub mod dist;
pub mod engine;
pub mod models;
pub mod stats;
pub mod validation;

pub use dist::Dist;
pub use engine::{Model, Scheduler, run};
pub use stats::{Estimate, TimeAverage, Welford};

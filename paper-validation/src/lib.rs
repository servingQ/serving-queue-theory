//! # paper-validation
//!
//! Validation and report generation for the models in `paper/main.tex`. The
//! Lean proofs in `lean/` establish the propositions *inside* their model;
//! this crate checks whether the decisions they imply survive once the
//! model's simplifications are dropped (non-Poisson arrivals, closed programs
//! with tool time, finite KV memory, tandem PD pools, load-dependent routing).
//!
//! | Module | Paper result it exercises |
//! |--------|---------------------------|
//! | [`models::queue`]    | Props. mm1, pk, cache; Ex. cv2; Kingman; Little |
//! | [`models::batch`]    | batching and two-resource replica: PS insensitivity, BCMP sessions, Props. price, decode, memory, footprint |
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
//!
//! Serving deployments and their workloads are specified in seQ programs.
//! Queue, PD, routing, agentic and batch checks run those programs.
//! Distribution sampling and moments come from seQ's `Dist` API.

pub mod analytic;
pub mod models;
mod seq_adapter;
pub mod seq_open;
pub mod seq_price;
pub mod seq_replay;
pub mod stats;
pub mod validation;
pub mod workload;

pub use seq::Dist;
pub use stats::{Estimate, TimeAverage, Welford};

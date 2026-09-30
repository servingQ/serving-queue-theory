"""Validation and report generation for the models in `paper/main.tex`.

The Lean proofs in `lean/` establish the propositions *inside* their model;
this package checks whether the decisions they imply survive once the
model's simplifications are dropped. Every simulated system is a seQ program
run by the pinned seQ CLI (`validation.seq`); `validation.checks` turns each
proposition into a named, seeded check, and `validation.analytic` mirrors
the Lean definitions one to one. Everything is seeded: the same seed gives
bit-identical results. Simulated numbers are results under the stated
synthetic workload, not measurements of a real serving system.
"""

# Serving Queue Theory

Decision-faithful queueing models for agentic LLM serving. The paper's
analytical propositions are machine-checked in Lean 4 with Mathlib, the
paper-to-proof correspondence is enforced by CI, and the serving deployments
the paper reasons about are written as programs in
[serQ](https://servingq.github.io/serQ/), where the same program is simulated and
checked against the real system.

The PDFs below are built from the sources at every change to `main`
(no PDF is kept in the repository).

## Paper

**[The Price of a Miss: Congestion-Priced KV Scheduling for Agentic LLM Serving](pdf/paper.pdf)**
(PDF, ICML 2026 format, draft)

An agentic LLM server keeps a program's KV cache across tool calls, and every
KV decision asks what one miss costs. For replicas with a prefill queue, a
decode batch and one memory pool the paper derives the *price of a miss*, the
time to first token it adds summed over all turns. Beyond its recompute, a
miss delays every prefill queued behind it, a quadratic term that chunked
prefill does not remove; one shadow price of memory decides eviction,
offloading, placement and admission.

## Lecture notes

| Notes | About |
|---|---|
| **[Queueing Theory for LLM Serving](pdf/queueing-serving.pdf)** (PDF) | Unified lecture notes: arrivals, PASTA, renewal rewards, Little’s law, Markovian queues, memory slots, processor sharing, the price of a miss, closed systems, eviction, a colocated scheduler, and prefill–decode disaggregation with transfer prices and feedback. Executable examples use serQ v0.1.1. |

## Sources

- [servingQ/serving-queue-theory](https://github.com/servingQ/serving-queue-theory):
  the paper (`paper/`), the lecture notes (`lectures/`), the Lean development
  (`lean/`) and the validation reports (`validation/`), executed with serQ.
  The repository is private;
  the page and the PDFs are public.
- [serQ](https://github.com/servingQ/serQ), the serving-deployment language, with
  its [tutorial site](https://servingq.github.io/serQ/).

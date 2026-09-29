# Serving Queue Theory

Decision-faithful queueing models for agentic LLM serving. The paper's
analytical propositions are machine-checked in Lean 4 with Mathlib, the
paper-to-proof correspondence is enforced by CI, and the serving deployments
the paper reasons about are written as programs in
[seQ](https://vrvrv.github.io/seQ/), where the same program is simulated and
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
| **[Queueing Theory for Agentic LLM Serving](pdf/queueing-primer.pdf)** (PDF) | Lecture notes for a four-hour course, the queueing primer behind the paper: probabilistic foundations (Poisson arrivals, PASTA, Little's law), Markovian queues (M/M/1, processor sharing, insensitivity), the M/G/1 queue and Pollaczek–Khinchine as the price of a miss, closed systems and memory (mean value analysis, Campbell's theorem, eviction as a covering knapsack), and the theory of the paper step by step. |
| **[Queueing Theory for Disaggregated LLM Serving](pdf/queueing-pd.pdf)** (PDF) | Lecture notes for a five-lecture course on prefill instances, decode instances and the KV cache between them: the same foundations, the prefill instance as an M/G/1 queue, memory slots and processor sharing at the decode instance, closed systems and eviction, and a queueing model of disaggregated serving with three prices and two pools (how long to keep, how many sessions to admit, misses that feed themselves). |

## Sources

- [vrvrv/serving-queue-theory](https://github.com/vrvrv/serving-queue-theory):
  the paper (`paper/`), the lecture notes (`lectures/`), the Lean development
  (`lean/`) and the validation reports (`validation/`), executed with seQ.
  The repository is private;
  the page and the PDFs are public.
- [seQ](https://github.com/vrvrv/seQ), the serving-deployment language, with
  its [tutorial site](https://vrvrv.github.io/seQ/).

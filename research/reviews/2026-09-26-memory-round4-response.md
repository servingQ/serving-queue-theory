# Response to the memory-model review, round 4 (2026-09-26)

All findings are accepted. What was done is in research/memory-model.md,
"Deviations and corrections (review round 4)".

| Item | Done |
|------|------|
| Registration record | disclosed: not committed; the three section times corrected to the output file times (22:36, 22:51, 22:55); the post-registration change to memory_model.py and its unregistered decode filter disclosed; the filter is off by default (`--min-decode 0`) |
| v1 deviated from the registered max rule | disclosed; the registered rule fitted on probes A+B (`analyze_decode.py --form max`, `fit_max_c0.json`) is reported, labelled post hoc |
| v2 summary | the overstated paragraph is marked superseded; failures stated (miss counts, metric 1 in the short-context arms) |
| c0 charged as engine time | fixed: c0 is client/frontend latency on the first-token and completion times; the model and fits frozen before the post hoc runs (hashes in data/exp/lockstep/freeze_c0.txt) |
| Probe G | in the doc; the stretch table is now computed net of c0 |
| Prefix-cache contamination, rep drift, inline CV searches | disclosed |
| New probes, engine step log, fresh saturated held-out replay with ensemble thresholds | planned in research/research-plan.md §0; not run (need a committed registration first) |
| Probe measurements into §4.3 / App. D via make exp | not yet |
| Table 1 "budget the decode batch leaves" | left: Table 1 states the model, and §6 already says that on this stack the roles are reversed |

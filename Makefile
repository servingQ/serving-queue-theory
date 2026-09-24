# Shared entry points for humans and coding agents (Claude Code, Codex).
SHELL := /bin/bash
export PATH := $(HOME)/.elan/bin:$(HOME)/.cargo/bin:$(HOME)/.local/bin:$(PATH)

.PHONY: setup lean refs paper sim figs report check preview clean

setup:            ## install elan, rustup, tectonic, uv (user-local) and fetch Mathlib cache
	scripts/setup.sh

lean:             ## lake build + sorry check + axiom audit
	scripts/check_lean.sh

refs:             ## every \leanref{} in the paper exists and is audited
	scripts/check_lean_refs.sh

paper:            ## compile paper/main.pdf
	cd paper && tectonic -X compile main.tex

sim:              ## libqueuingsim: Lean-name check, fmt, clippy, tests, report, tables/data staleness, figures
	scripts/check_sim.sh

figs:             ## redraw paper/sim/fig-*.pdf from paper/sim/data/*.csv (written by paper_tables)
	uv run --quiet --with matplotlib python scripts/plot_sim.py

WEKA ?= data/cc-traces-weka/traces.jsonl
HARBOR ?= /mnt/shared_data/groups/fsw_serv/harbor-trajectory/swebenchpro__claude-code
traces:           ## regenerate paper/traces/ from the trace corpora (WEKA=..., HARBOR=...)
	python3 scripts/trace_stats_weka.py $(WEKA) --tex paper/traces --label weka
	python3 scripts/trace_stats_harbor.py $(HARBOR) --tex paper/traces --label harbor

report:           ## print the simulator validation report
	cd libqueuingsim && cargo run --release --quiet --example validate

check: lean refs paper sim   ## everything CI runs

preview: paper    ## render PDF pages to PNG for visual inspection
	cd paper && uv run --quiet --with pymupdf python -c "import pymupdf,os; d=pymupdf.open('main.pdf'); out=os.environ.get('OUT','/tmp/sqt-preview'); os.makedirs(out,exist_ok=True); [p.get_pixmap(dpi=75).save(f'{out}/page{i+1}.png') for i,p in enumerate(d)]; print(len(d),'pages ->',out)"

clean:
	rm -f paper/main.pdf lean/build.log lean/axioms.log libqueuingsim/validation-report.md

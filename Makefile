# Shared entry points for humans and coding agents (Claude Code, Codex).
SHELL := /bin/bash
export PATH := $(HOME)/.elan/bin:$(HOME)/.cargo/bin:$(HOME)/.local/bin:$(PATH)

.PHONY: setup serq lean refs paper lectures lecture-results site sim tables figs report check preview clean

setup:            ## install elan, rustup, tectonic, uv (user-local) and fetch Mathlib cache
	scripts/setup.sh

lean:             ## lake build + sorry check + axiom audit
	scripts/check_lean.sh

refs:             ## every \leanref{} in the paper exists and is audited
	scripts/check_lean_refs.sh

paper:            ## compile paper/main.pdf
	cd paper && tectonic -X compile main.tex

lectures:         ## compile lectures/*/notes.pdf
	for d in lectures/*/; do (cd $$d && tectonic -X compile notes.tex) || exit 1; done

lecture-results: serq  ## lecture formulas and executable resource lifetimes
	python3 scripts/check_lecture_results.py --serq .serq/bin/serq --out /tmp/sqt-lecture-check.json

site: paper lectures   ## the public page (docs/, mkdocs.yml) with the PDFs, into site/
	mkdir -p docs/pdf && cp paper/main.pdf docs/pdf/paper.pdf
	for d in lectures/*/; do cp $$d/notes.pdf docs/pdf/$$(basename $$d).pdf; done
	uv run --quiet --with mkdocs-material==9.7.7 mkdocs build --strict

sim:              ## validation: Lean-name check, ruff, pytest and validation report
	scripts/check_sim.sh

serq:              ## the serQ release pinned in validation/pyproject.toml: .serq/src (programs, oracle vectors) and the CLI .serq/bin/serq
	scripts/fetch_serq.sh

tables:           ## regenerate paper/sim/*.tex and paper/sim/data/*.csv (report.paper_tables)
	cd validation && uv run --locked --quiet python -m report.paper_tables

figs:             ## redraw paper/sim/fig-*.pdf from paper/sim/data/*.csv (written by `make tables`)
	uv run --quiet --with matplotlib python scripts/plot_sim.py

WEKA ?= data/cc-traces-weka/traces.jsonl
HARBOR ?= /mnt/shared_data/groups/fsw_serv/harbor-trajectory/swebenchpro__claude-code
traces:           ## regenerate paper/traces/ from the trace corpora (WEKA=..., HARBOR=...)
	python3 scripts/trace_stats_weka.py $(WEKA) --tex paper/traces --label weka
	python3 scripts/trace_stats_harbor.py $(HARBOR) --tex paper/traces --label harbor

exp:              ## regenerate paper/exp/ from the testbed measurements (data/exp/e1, data/exp/e2)
	python3 scripts/exp/fit_e1.py data/exp/e1/probes.jsonl
	python3 scripts/exp/analyze_e2.py --fit data/exp/e1/fit.json --out data/exp/e2/summary.json data/exp/e2/*/rounds.jsonl
	python3 scripts/exp/paper_e2_tables.py data/exp/e2/summary.json
	python3 scripts/exp/analyze_e2.py --fit data/exp/e1/fit.json --warmup 90 --out data/exp/e2b/summary.json data/exp/e2b/s*_base*/rounds.jsonl data/exp/e2b/s*_m10*/rounds.jsonl
	for b in data/exp/e2b/s*_base data/exp/e2b/s*_base_s1; do f=$${b/_base/_m10}; t=data/exp/traces/short_m10$${b##*_base}.jsonl; [ -f $$f/rounds.jsonl ] && python3 scripts/exp/analyze_price.py --fit data/exp/e1/fit.json --base $$b/rounds.jsonl --forced $$f/rounds.jsonl --trace $$t --out data/exp/e2b/price_$$(basename $$f | sed 's/_m10//').json; done; true
	python3 scripts/exp/paper_e2b_tables.py data/exp/e2b/summary.json data/exp/e2b/price_*.json
	uv run --quiet --with matplotlib python scripts/exp/plot_exp.py --prices data/exp/e2b/price_*.json

report:           ## print the simulator validation report
	cd validation && uv run --locked --quiet python -m report.validation

check: serq lean refs paper lectures sim lecture-results   ## everything CI runs

preview: paper    ## render PDF pages to PNG for visual inspection
	cd paper && uv run --quiet --with pymupdf python -c "import pymupdf,os; d=pymupdf.open('main.pdf'); out=os.environ.get('OUT','/tmp/sqt-preview'); os.makedirs(out,exist_ok=True); [p.get_pixmap(dpi=75).save(f'{out}/page{i+1}.png') for i,p in enumerate(d)]; print(len(d),'pages ->',out)"

clean:
	rm -f paper/main.pdf lectures/*/notes.pdf lean/build.log lean/axioms.log validation/validation-report.md
	rm -rf docs/pdf site

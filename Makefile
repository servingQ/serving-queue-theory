# Shared entry points for humans and coding agents (Claude Code, Codex).
SHELL := /bin/bash
export PATH := $(HOME)/.elan/bin:$(HOME)/.local/bin:$(PATH)

.PHONY: setup lean refs paper check preview clean

setup:            ## install elan, tectonic, uv (user-local) and fetch Mathlib cache
	scripts/setup.sh

lean:             ## lake build + sorry check + axiom audit
	scripts/check_lean.sh

refs:             ## every \leanref{} in the paper exists and is audited
	scripts/check_lean_refs.sh

paper:            ## compile paper/main.pdf
	cd paper && tectonic -X compile main.tex

check: lean refs paper   ## everything CI runs

preview: paper    ## render PDF pages to PNG for visual inspection
	cd paper && uv run --quiet --with pymupdf python -c "import pymupdf,os; d=pymupdf.open('main.pdf'); out=os.environ.get('OUT','/tmp/sqt-preview'); os.makedirs(out,exist_ok=True); [p.get_pixmap(dpi=75).save(f'{out}/page{i+1}.png') for i,p in enumerate(d)]; print(len(d),'pages ->',out)"

clean:
	rm -f paper/main.pdf lean/build.log lean/axioms.log

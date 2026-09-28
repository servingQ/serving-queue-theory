# Publishing this page

`www/` is the source of <https://vrvrv.github.io/serving-queue-theory/>: the
paper and the two lecture notes as PDFs, and one page that links them. It is
built by `mkdocs` (`mkdocs.yml` at the root, `docs_dir: www`) and deployed by
`.github/workflows/publish.yml`. `docs/` is the internal working notes and is
not part of the site.

**Public.** Anyone can read the page and download the PDFs, and search
engines index them, although the repository is private. The paper is a
draft with unpublished measurements; treat everything reachable from the
page as published.

## How it works

Every push to `main` that touches `paper/`, `lectures/`, `www/` or
`mkdocs.yml` (and `workflow_dispatch`) runs `publish.yml`:

1. **pdfs**: tectonic compiles `paper/main.tex` and every
   `lectures/*/notes.tex`. The PDFs are uploaded as the workflow artifacts
   `paper-pdf` and `lecture-notes` (kept 90 days) and handed to the next job.
2. **site**: the PDFs land in `www/pdf/` (gitignored), `mkdocs build --strict`
   builds the page, which links them relatively (`pdf/paper.pdf`,
   `pdf/queueing-primer.pdf`, `pdf/queueing-pd.pdf`), so a missing PDF fails
   the build. The site is uploaded as the artifact `site`.
3. **deploy**: on `main` only, `actions/deploy-pages` publishes the site.

A pull request touching the same paths runs steps 1 and 2 and stops, so a
reviewer downloads the artifacts from the run.

No PDF is committed: `paper/main.pdf`, `lectures/*/notes.pdf` and `www/pdf/`
are gitignored. The figures under `paper/sim/` and `paper/exp/` are
generated data that the paper `\input`s, and stay tracked.

## Locally

```bash
make lectures                      # lectures/*/notes.pdf (tectonic)
make paper                         # paper/main.pdf
make site                          # copies the PDFs into www/pdf/ and builds site/
uv run --with mkdocs-material==9.7.7 mkdocs serve   # http://127.0.0.1:8000
```

## Unpublishing

```bash
gh api -X DELETE repos/vrvrv/serving-queue-theory/pages
```

The page stops being served; caches and search results keep what they
already have for a while.

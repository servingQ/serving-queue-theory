"""Print every validation check as a Markdown report.

    uv run python -m report            # report to stdout
    uv run python -m report out.md     # also write a file

Exits non-zero if any check fails.
"""

from __future__ import annotations

import sys
import time

import checks


def main(argv: list[str]) -> int:
    t0 = time.monotonic()
    cs = checks.all_checks()
    obs = checks.observations()
    failed = sum(1 for c in cs if not c.passed)
    md = ["# Validation report\n"]
    md.append(
        "Synthetic workloads, fixed seeds. These are properties of the simulated model, "
        "not measurements of a serving system.\n"
    )
    md.append("| | Check | Paper | Kind |")
    md.append("|-|-------|-------|------|")
    for c in cs:
        md.append(f"| {'PASS' if c.passed else 'FAIL'} | `{c.id}` | {c.paper} | {c.kind.value} |")
    md.append("\n## Details\n")
    for c in cs:
        md.append(f"### `{c.id}` ({'PASS' if c.passed else 'FAIL'})\n")
        md.append(f"- **Claim:** {c.claim}")
        if c.lean:
            md.append(f"- **Lean:** `{'`, `'.join(c.lean)}`")
        md.append(f"- **Expected:** {c.expected}")
        md.append(f"- **Observed:** {c.observed}\n")
    md.append("## Observations (not asserted)\n")
    for o in obs:
        md.append(f"### `{o.id}` ({o.paper})\n")
        md.append(f"- **Question:** {o.question}")
        md.append(f"- **Result:** {o.result}\n")
    md.append(f"{len(cs)} checks, {failed} failed; {time.monotonic() - t0:.1f}s")
    text = "\n".join(md) + "\n"
    sys.stdout.write(text)
    if argv:
        with open(argv[0], "w") as f:
            f.write(text)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

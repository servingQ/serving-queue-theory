//! Print every validation check as a Markdown report.
//!
//! ```text
//! cargo run --release --example validate            # report to stdout
//! cargo run --release --example validate -- out.md  # also write a file
//! ```
//!
//! Exits non-zero if any check fails.

use std::fmt::Write as _;
use std::time::Instant;

use libqueuingsim::validation::{self, Kind};

fn main() {
    let t0 = Instant::now();
    let checks = validation::all();
    let obs = validation::observations();

    let mut md = String::new();
    let failed = checks.iter().filter(|c| !c.pass).count();
    writeln!(md, "# libqueuingsim validation report\n").unwrap();
    writeln!(
        md,
        "Synthetic workloads, fixed seeds. These are properties of the \
         simulated model, not measurements of a serving system.\n"
    )
    .unwrap();
    writeln!(md, "| | Check | Paper | Kind |").unwrap();
    writeln!(md, "|-|-------|-------|------|").unwrap();
    for c in &checks {
        let kind = match c.kind {
            Kind::InModel => "in-model",
            Kind::BeyondModel => "beyond-model",
        };
        let mark = if c.pass { "PASS" } else { "FAIL" };
        writeln!(md, "| {mark} | `{}` | {} | {kind} |", c.id, c.paper).unwrap();
    }
    writeln!(md, "\n## Details\n").unwrap();
    for c in &checks {
        writeln!(
            md,
            "### `{}` ({})\n",
            c.id,
            if c.pass { "PASS" } else { "FAIL" }
        )
        .unwrap();
        writeln!(md, "- **Claim:** {}", c.claim).unwrap();
        if !c.lean.is_empty() {
            writeln!(md, "- **Lean:** `{}`", c.lean.join("`, `")).unwrap();
        }
        writeln!(md, "- **Expected:** {}", c.expected).unwrap();
        writeln!(md, "- **Observed:** {}\n", c.observed).unwrap();
    }
    writeln!(md, "## Observations (not asserted)\n").unwrap();
    for o in &obs {
        writeln!(md, "### `{}` ({})\n", o.id, o.paper).unwrap();
        writeln!(md, "- **Question:** {}", o.question).unwrap();
        writeln!(md, "- **Result:** {}\n", o.result).unwrap();
    }
    writeln!(
        md,
        "{} checks, {} failed; {:.1}s",
        checks.len(),
        failed,
        t0.elapsed().as_secs_f64()
    )
    .unwrap();

    print!("{md}");
    if let Some(path) = std::env::args().nth(1) {
        std::fs::write(&path, &md).expect("write report");
    }
    if failed > 0 {
        std::process::exit(1);
    }
}

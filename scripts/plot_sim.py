#!/usr/bin/env python3
"""Figures of the paper's simulation section, drawn from paper/sim/data/*.csv.

    uv run --quiet --with matplotlib python scripts/plot_sim.py [--data DIR] [--out DIR]

The CSV files are written by `cargo run --release --example paper_tables`
(validation/), the same run that writes the tables, so every figure
shows exactly the numbers of the table it accompanies. `make figs`
regenerates the PDFs; `scripts/check_sim.sh` checks the data files are
current and re-runs this script. Numbers are from synthetic workloads
(uncalibrated), never measurements.

Style follows the dataviz method: three categorical slots in fixed order
(blue, orange, aqua; validated for CVD separation), marker shapes as the
secondary channel, hairline solid grid, one axis per panel, a legend for
every multi-series panel, text in ink tokens rather than series colours.
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import matplotlib

matplotlib.use("pdf")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

# Categorical slots (fixed order, never cycled) and their marker shapes.
SLOTS = ["#2a78d6", "#eb6834", "#1baf7a"]
MARKERS = ["o", "s", "^"]
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SURFACE = "#ffffff"
COL_W = 3.25  # ICML single-column width in inches

# Deterministic PDF bytes: no timestamps or tool versions in the file.
META = {"CreationDate": None, "ModDate": None, "Producer": None, "Creator": None}

POLICY_LABEL = {
    "SF": "Shortest-first",
    "Density": "Density",
    "PricedTau": r"Priced/$\tau$",
    "Guarded": "Guarded density",
}
REGIME_LABEL = {
    "equal_p": r"equal $p_i$",
    "varied_p": r"$p_i \sim U[0.05,1]$",
    "p_falls_with_c": r"$p_i$ falls with $c_i$",
    "arbitrary_w": r"arbitrary $w_i$",
}
WORK_LABEL = {"D": "D", "Exp": "Exp", "H2": "H2"}


def style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 8,
            "axes.titlesize": 8,
            "axes.labelsize": 8,
            "xtick.labelsize": 7,
            "ytick.labelsize": 7,
            "legend.fontsize": 7,
            "legend.frameon": False,
            "legend.handlelength": 1.6,
            "legend.borderaxespad": 0.2,
            "axes.edgecolor": AXIS,
            "axes.linewidth": 0.5,
            "axes.labelcolor": INK2,
            "axes.titlecolor": INK,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "axes.grid.axis": "y",
            "grid.color": GRID,
            "grid.linewidth": 0.5,
            "grid.linestyle": "-",
            "axes.axisbelow": True,
            "xtick.color": MUTED,
            "ytick.color": MUTED,
            "xtick.labelcolor": INK2,
            "ytick.labelcolor": INK2,
            "xtick.major.width": 0.5,
            "ytick.major.width": 0.5,
            "xtick.major.size": 2.5,
            "ytick.major.size": 2.5,
            "lines.linewidth": 1.2,
            "lines.markersize": 4,
            "lines.markeredgewidth": 0.8,
            "text.color": INK,
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "pdf.fonttype": 42,
            "mathtext.fontset": "dejavusans",
        }
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open() as f:
        lines = [ln for ln in f if not ln.startswith("#")]
    return list(csv.DictReader(lines))


def fnum(row: dict[str, str], key: str) -> float:
    return float(row[key])


def legend_handles(labels: list[str], n: int | None = None) -> list[Line2D]:
    n = len(labels) if n is None else n
    return [
        Line2D(
            [],
            [],
            color=SLOTS[i],
            marker=MARKERS[i],
            markerfacecolor=SLOTS[i],
            markeredgecolor=SURFACE,
            label=labels[i],
        )
        for i in range(n)
    ]


# --------------------------------------------------------------------------
# fig-admission: TTFT, p99 and hit rate against the admission cap
# --------------------------------------------------------------------------
def fig_admission(data: Path, out: Path) -> None:
    rows = read_csv(data / "admission.csv")
    rates = sorted({row["rate"] for row in rows}, key=float)
    caps = sorted({int(row["cap"]) for row in rows})
    policies = ["SF", "Density", "PricedTau"]
    seeds = int(rows[0]["seeds"])
    dodge = 0.9  # x offset between policies so whiskers do not overlap

    fig, axes = plt.subplots(
        3,
        len(rates),
        figsize=(COL_W, 3.9),
        sharex=True,
        sharey="row",
        gridspec_kw={"hspace": 0.18, "wspace": 0.12},
    )
    panels = [
        ("ttft", "Mean TTFT (s)", True),
        ("ttft_p99", "p99 TTFT (s)", True),
        ("hit", "Follow-up hit rate", False),
    ]
    for j, rate in enumerate(rates):
        for i, (key, ylabel, logy) in enumerate(panels):
            ax = axes[i, j]
            for k, pol in enumerate(policies):
                cells = {
                    int(r["cap"]): r for r in rows if r["rate"] == rate and r["policy"] == pol
                }
                xs = [c + (k - 1) * dodge for c in caps]
                ys = [fnum(cells[c], key) for c in caps]
                hw = [fnum(cells[c], key + "_hw") for c in caps]
                if logy:
                    # A whisker cannot cross zero on a log axis; clip it at
                    # a tenth of the mean and let the table state the value.
                    lo = [min(h, 0.9 * y) for y, h in zip(ys, hw)]
                else:
                    lo = hw
                ax.errorbar(
                    xs,
                    ys,
                    yerr=[lo, hw],
                    color=SLOTS[k],
                    marker=MARKERS[k],
                    markerfacecolor=SLOTS[k],
                    markeredgecolor=SURFACE,
                    ecolor=SLOTS[k],
                    elinewidth=0.6,
                    capsize=1.2,
                    capthick=0.6,
                    zorder=3 + k,
                )
            if key == "hit":
                # Thrashed-seed counts: one stacked column per cap (one row
                # per policy, in legend order, in the policy's colour), below
                # the lowest point of that cap, so the three counts never
                # overlap and nothing is clipped at the right edge.
                for c in caps:
                    counts = [int({int(r["cap"]): r for r in rows if r["rate"] == rate and r["policy"] == p}[c]["thrashed"]) for p in policies]
                    if not any(counts):
                        continue
                    ylow = min(fnum({int(r["cap"]): r for r in rows if r["rate"] == rate and r["policy"] == p}[c], key) for p in policies)
                    for k, t in enumerate(counts):
                        ax.annotate(
                            f"{t}/{seeds}",
                            (c, ylow),
                            xytext=(0, -9 - 6.5 * k),
                            textcoords="offset points",
                            ha="center",
                            va="top",
                            fontsize=5.5,
                            color=SLOTS[k],
                        )
            if logy:
                ax.set_yscale("log")
            ax.set_xticks(caps)
            ax.set_xlim(caps[0] - 3.5, caps[-1] + 5.5)
            if j == 0:
                ax.set_ylabel(ylabel)
            else:
                ax.tick_params(axis="y", length=0)
            if i == 0:
                ax.set_title(rf"$\Lambda = {float(rate):.2f}$ /s", pad=3)
            if i == 2:
                ax.set_ylim(0.22, 1.03)
                ax.set_yticks([0.4, 0.6, 0.8, 1.0])
    for ax in axes[0]:
        ax.set_yticks([0.3, 1, 3, 10])
        ax.set_yticklabels(["0.3", "1", "3", "10"])
    for ax in axes[1]:
        ax.set_yticks([3, 10, 30, 100])
        ax.set_yticklabels(["3", "10", "30", "100"])
    fig.legend(
        handles=legend_handles([POLICY_LABEL[p] for p in policies]),
        loc="upper center",
        ncol=3,
        bbox_to_anchor=(0.5, 1.0),
        columnspacing=1.0,
        handletextpad=0.4,
    )
    fig.supxlabel("Admission cap (live sessions)", fontsize=8, color=INK2, y=0.015)
    fig.subplots_adjust(left=0.15, right=0.99, top=0.88, bottom=0.11)
    fig.savefig(out / "fig-admission.pdf", metadata=META)
    plt.close(fig)


# --------------------------------------------------------------------------
# fig-lps: relative error of the saturating-phi formula vs exact limited PS
# --------------------------------------------------------------------------
def fig_lps(data: Path, out: Path) -> None:
    rows = read_csv(data / "lps.csv")
    works = []
    for r in rows:
        if r["work"] not in works:
            works.append(r["work"])
    fig, ax = plt.subplots(figsize=(COL_W, 2.0))
    ax.axhline(0, color=AXIS, linewidth=0.6, zorder=1)
    for k, w in enumerate(works):
        sub = [r for r in rows if r["work"] == w]
        xs = [fnum(r, "u") for r in sub]
        ys = [fnum(r, "err_pct") for r in sub]
        hw = [fnum(r, "err_pct_hw") for r in sub]
        ax.errorbar(
            xs,
            ys,
            yerr=hw,
            color=SLOTS[k],
            marker=MARKERS[k],
            markerfacecolor=SLOTS[k],
            markeredgecolor=SURFACE,
            ecolor=SLOTS[k],
            elinewidth=0.6,
            capsize=1.2,
            capthick=0.6,
            label=rf"{WORK_LABEL[w]} ($\mathrm{{CV}}^2 = {float(sub[0]['cv2']):g}$)",
            zorder=3 + k,
        )
    us = sorted({fnum(r, "u") for r in rows})
    ax.set_xticks(us)
    ax.set_xlim(us[0] - 0.04, us[-1] + 0.04)
    ax.set_xlabel(r"Load $u = \rho/\phi(B)$")
    ax.set_ylabel("LPS relative to formula (%)")
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:+.0f}"))
    ax.legend(loc="upper left", handletextpad=0.4)
    fig.subplots_adjust(left=0.16, right=0.98, top=0.96, bottom=0.2)
    fig.savefig(out / "fig-lps.pdf", metadata=META)
    plt.close(fig)


# --------------------------------------------------------------------------
# fig-evict-offline: cost/OPT by regime and policy, range and mean
# --------------------------------------------------------------------------
def quantile(sorted_xs: list[float], q: float) -> float:
    if not sorted_xs:
        return math.nan
    pos = q * (len(sorted_xs) - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, len(sorted_xs) - 1)
    return sorted_xs[lo] + (sorted_xs[hi] - sorted_xs[lo]) * (pos - lo)


def sci(x: float) -> str:
    k = math.floor(math.log10(x))
    return rf"${x / 10**k:.1f}{{\times}}10^{{{k}}}$"


def fig_evict_offline(data: Path, out: Path) -> None:
    summary = read_csv(data / "evict-offline.csv")
    samples = read_csv(data / "evict-offline-samples.csv")
    regimes = []
    for r in summary:
        if r["regime"] not in regimes:
            regimes.append(r["regime"])
    policies = [("SF", "sf"), ("Density", "density"), ("Guarded", "guarded")]
    xmax = 11.0  # the clip; SF on arbitrary weights lies far beyond it

    fig, ax = plt.subplots(figsize=(COL_W, 2.5))
    ax.grid(False)
    ax.grid(True, axis="x", color=GRID, linewidth=0.5)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    sub_h = 0.26  # spacing between policy sub-rows within a regime
    yticks, ylabels = [], []
    clipped = []
    for i, regime in enumerate(regimes):
        base = -i
        yticks.append(base)
        ylabels.append(REGIME_LABEL[regime])
        for k, (pol, col) in enumerate(policies):
            y = base + (1 - k) * sub_h
            xs = sorted(fnum(r, col) for r in samples if r["regime"] == regime)
            mean = sum(xs) / len(xs)
            lo, p90, hi = xs[0], quantile(xs, 0.9), xs[-1]
            if hi > xmax:
                clipped.append((pol, regime, mean, hi, y))
            ax.plot(
                [lo, min(hi, xmax)],
                [y, y],
                color=SLOTS[k],
                linewidth=0.6,
                solid_capstyle="butt",
                zorder=2,
            )
            ax.plot(
                [lo, min(p90, xmax)],
                [y, y],
                color=SLOTS[k],
                linewidth=2.0,
                solid_capstyle="butt",
                zorder=3,
            )
            if mean <= xmax:
                ax.plot(
                    [mean],
                    [y],
                    marker=MARKERS[k],
                    color=SLOTS[k],
                    markerfacecolor=SLOTS[k],
                    markeredgecolor=SURFACE,
                    linestyle="none",
                    zorder=4,
                )
            if hi > xmax:
                ax.annotate(
                    "",
                    xy=(xmax + 0.35, y),
                    xytext=(xmax - 0.4, y),
                    arrowprops={"arrowstyle": "-|>", "color": SLOTS[k], "lw": 0.6},
                    annotation_clip=False,
                )
    for pol, regime, mean, hi, y in clipped:
        ax.text(
            xmax - 0.15,
            y + 0.12,
            f"mean {sci(mean)}, max {sci(hi)}",
            ha="right",
            va="bottom",
            fontsize=5.5,
            color=INK2,
        )
    ax.set_yticks(yticks)
    ax.set_yticklabels(ylabels)
    ax.set_ylim(-len(regimes) + 1 - 0.55, 0.55)
    ax.set_xlim(0.85, xmax)
    ax.set_xticks([1, 2, 4, 6, 8, 10])
    ax.set_xlabel("Cost / OPT\n(line: min to max, thick to p90; marker: mean)", fontsize=7)
    ax.legend(
        handles=legend_handles([POLICY_LABEL[p] for p, _ in policies]),
        loc="upper right",
        handletextpad=0.4,
    )
    fig.subplots_adjust(left=0.27, right=0.98, top=0.97, bottom=0.22)
    fig.savefig(out / "fig-evict-offline.pdf", metadata=META)
    plt.close(fig)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data", type=Path, default=root / "paper" / "sim" / "data")
    ap.add_argument("--out", type=Path, default=root / "paper" / "sim")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    style()
    fig_admission(args.data, args.out)
    fig_lps(args.data, args.out)
    fig_evict_offline(args.data, args.out)
    print(f"wrote fig-admission.pdf fig-lps.pdf fig-evict-offline.pdf -> {args.out}")


if __name__ == "__main__":
    main()

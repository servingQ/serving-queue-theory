#!/usr/bin/env python3
"""Figures of the testbed section, drawn from the measurement files:

    uv run --quiet --with matplotlib python scripts/exp/plot_exp.py

  paper/exp/fig-e1.pdf   E1: measured TTFT of cold and append probes against
                         the fitted cost model P(n,K) (data/exp/e1/probes.jsonl,
                         data/exp/e1/fit.json).
  paper/exp/fig-e2.pdf   E2: per replay run, TTFT of follow-up hits and misses
                         with p99, the follow-up hit rate and KV occupancy, and
                         the server's queueing time against the open PK wait and
                         the finite-source wait (data/exp/e2/summary.json).

Style follows scripts/plot_sim.py (fixed categorical slots, marker shapes,
hairline grid). Every number comes from the same files as the tables.
"""
from __future__ import annotations

import argparse
import json
import statistics as st
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("pdf")
import matplotlib.pyplot as plt  # noqa: E402

SLOTS = ["#2a78d6", "#eb6834", "#1baf7a"]
MARKERS = ["o", "s", "^"]
INK = "#0b0b0b"
INK2 = "#52514e"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
META = {"Creator": "scripts/exp/plot_exp.py"}


def style() -> None:
    plt.rcParams.update(
        {
            "font.size": 8,
            "axes.titlesize": 8,
            "axes.labelsize": 8,
            "legend.fontsize": 7,
            "xtick.labelsize": 7,
            "ytick.labelsize": 7,
            "axes.edgecolor": AXIS,
            "axes.linewidth": 0.6,
            "axes.grid": True,
            "grid.color": GRID,
            "grid.linewidth": 0.5,
            "axes.axisbelow": True,
            "xtick.color": INK2,
            "ytick.color": INK2,
            "text.color": INK,
            "axes.labelcolor": INK,
            "legend.frameon": False,
            "figure.dpi": 150,
            "savefig.bbox": "tight",
            "savefig.pad_inches": 0.02,
            "pdf.fonttype": 42,
        }
    )


def fig_e1(e1: Path, out: Path) -> None:
    fit = json.load(open(e1 / "fit.json"))
    c0, a, b = fit["c0"], fit["a"], fit["b"]
    groups: dict[tuple[int, int], list[float]] = defaultdict(list)
    for line in open(e1 / "probes.jsonl"):
        if not line.strip():
            continue
        r = json.loads(line)
        if r["kind"] == "cold":
            groups[(0, r["n"])].append(r["ttft_s"])
        elif r["kind"] == "append" and (r.get("cached_tokens") or 0) >= 0.5 * r["K"]:
            groups[(r["K"], r["n"])].append(r["ttft_s"])
    ks = sorted({k for k, _ in groups})
    fig, ax = plt.subplots(figsize=(3.3, 2.3))
    xs = [2 ** (i / 2) for i in range(16, 34)]
    for i, k in enumerate(ks):
        col = SLOTS[i % 3] if k else INK
        mk = MARKERS[i % 3]
        pts = sorted((n, st.fmean(ts)) for (kk, n), ts in groups.items() if kk == k)
        ax.plot([n for n, _ in pts], [t for _, t in pts], linestyle="none", marker=mk, color=col, markersize=4, zorder=3)
        ax.plot(xs, [c0 + a * n + b * n * (k + n / 2) for n in xs], color=col, linewidth=0.9, zorder=2)
        label = "cold ($K=0$)" if k == 0 else f"append on $K={k // 1024}$k"
        ax.plot([], [], marker=mk, color=col, linewidth=0.9, markersize=4, label=label)
    ax.plot(xs, [c0 + a * n for n in xs], color=INK2, linestyle=":", linewidth=0.8, label="dense term only")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("new tokens $n$")
    ax.set_ylabel("TTFT (s)")
    ax.set_title(f"Cost fit: $P(n,K)$, $K_c=a/b\\approx${fit['kc'] / 1000:.0f}k tokens", loc="left", color=INK2)
    ax.legend(loc="upper left")
    fig.savefig(out / "fig-e1.pdf", metadata=META)
    plt.close(fig)


def fig_e2(summary: Path, out: Path, summary_e2b: Path | None = None, prices: list[Path] | None = None) -> None:
    runs = [r for r in json.load(open(summary)) if r]
    runs.sort(key=lambda r: (-float(r["params"].get("spacing_s", 0) or 0), -(int(r["params"].get("cap", 0) or 0) or 10**9)))
    labels = []
    for r in runs:
        cap = int(r["params"].get("cap", 0) or 0)
        # One line per run: the cap; a dagger marks the run with a session
        # every 10 s instead of 20 s (the caption says so).
        lab = "$\\infty$" if cap == 0 else str(cap)
        if float(r["params"].get("spacing_s", 0)) < 15:
            lab += "$^{\\dagger}$"
        labels.append(lab)
    x = list(range(len(runs)))
    e2b = summary_e2b is not None and summary_e2b.exists()
    if e2b:
        fig, axes_all = plt.subplots(1, 5, figsize=(6.8, 2.3), gridspec_kw={"width_ratios": [1, 1, 1, 1.05, 0.85]})
        axes = axes_all[:3]
    else:
        fig, axes = plt.subplots(1, 3, figsize=(6.8, 2.2))
    # (a) TTFT of hits, misses, p99
    ax = axes[0]
    ax.plot(x, [r["ttft_hit"] for r in runs], marker=MARKERS[0], color=SLOTS[0], label="follow-up hit (mean)")
    ax.plot(x, [r["ttft_miss"] for r in runs], marker=MARKERS[1], color=SLOTS[1], label="follow-up miss (mean)")
    ax.plot(x, [r["ttft_p99"] for r in runs], marker=MARKERS[2], color=SLOTS[2], label="all turns (p99)")
    ax.set_yscale("log")
    ax.set_ylabel("TTFT (s)")
    ax.set_title("(a) long: miss cost", loc="left", color=INK2, fontsize=7)
    # (b) hit rate and KV occupancy
    ax = axes[1]
    ax.plot(x, [100 * r["hit"] for r in runs], marker=MARKERS[0], color=SLOTS[0], label="follow-up hit rate")
    ax.plot(x, [100 * r["kv_usage"] for r in runs], marker=MARKERS[1], color=SLOTS[1], label="KV pool occupancy")
    ax.plot(x, [100 * r["rho_hi"] for r in runs], marker=MARKERS[2], color=SLOTS[2], label="prefill $\\rho$, busiest rank")
    ax.set_ylim(0, 105)
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.set_ylabel("%")
    ax.set_title("(b) long: cache, load", loc="left", color=INK2, fontsize=7)
    # (c) waits: observed vs PK vs finite-source
    ax = axes[2]
    ax.plot(x, [r["q_srv"] for r in runs], marker=MARKERS[0], color=SLOTS[0], label="server queueing time")
    ax.plot(x, [r["w_fin"] for r in runs], marker=MARKERS[1], color=SLOTS[1], label="finite-source M/M/1//N")
    ax.plot(x, [r["pk"] for r in runs], marker=MARKERS[2], color=SLOTS[2], label="open PK")
    ax.set_yscale("log")
    ax.set_ylabel("mean wait (s)")
    lo = min(min(r["pk"] for r in runs), min(r["w_fin"] for r in runs)) / 8
    ax.set_ylim(bottom=lo)
    ax.set_title("(c) long: waits", loc="left", color=INK2, fontsize=7)
    for ax in axes:
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.set_xlabel("cap $N_{\\max}$", fontsize=7, labelpad=1)
        # The legend sits below the axis label, outside the axes, so no
        # entry can cover a line (round-4 review).
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.3), ncol=1, fontsize=6, handlelength=1.4, borderaxespad=0.0)
    if e2b:
        e2b_panels(axes_all[3], axes_all[4], summary_e2b, prices or [])
    fig.tight_layout(w_pad=0.8)
    fig.savefig(out / "fig-e2.pdf", metadata=META)
    plt.close(fig)


def e2b_panels(ax_a, ax_b, summary: Path, prices: list[Path]) -> None:
    """(a) per rank and run: the server's queueing time, the open PK wait and
    the finite-source wait against the rank's prefill load; (b) per spacing:
    the observed rise of the prefill stage under forced misses against the
    bracket of Proposition price (bar from lo to hi) and the finite-source
    price."""
    runs = [r for r in json.load(open(summary)) if r]
    base = [r for r in runs if "m10" not in str(r["path"])]
    ax = ax_a
    for key, lab, k in (("queue_time_mean", "server queueing time", 0), ("w_fin", "finite-source M/M/1//N", 1), ("pk", "open PK", 2)):
        xs, ys = [], []
        for r in base:
            for pr in r["per_rank"]:
                v = pr.get(key)
                if v is not None and v == v and v != float("inf"):
                    xs.append(pr["rho"])
                    ys.append(v)
        ax.plot(xs, ys, linestyle="none", marker=MARKERS[k], color=SLOTS[k], markersize=3.5, label=lab, zorder=3 - k)
    ax.set_yscale("log")
    ax.set_xlabel("load $\\rho$ per rank", fontsize=7, labelpad=1)
    ax.set_ylabel("mean wait (s)")
    ax.set_title("(d) short: waits", loc="left", color=INK2, fontsize=7)
    ax.set_xticks([0.2, 0.4, 0.6])
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.3), ncol=1, fontsize=6, handlelength=1.4, borderaxespad=0.0)
    ax = ax_b
    ps = [json.load(open(p)) for p in prices]
    ps.sort(key=lambda p: -p["spacing_s"])
    x = list(range(len(ps)))
    for i, p in enumerate(ps):
        t = p["total"]
        hi = t["hi"] if t["hi"] != float("inf") else t["lo"] * 3
        ax.plot([i, i], [t["lo"], hi], color=SLOTS[2], linewidth=6, alpha=0.35, solid_capstyle="butt", zorder=1)
        if t["hi"] == float("inf"):
            ax.annotate("", xy=(i, hi * 1.15), xytext=(i, hi), arrowprops={"arrowstyle": "-|>", "color": SLOTS[2], "lw": 0.6})
    ax.plot(x, [p["total"]["dl_p"] for p in ps], linestyle="none", marker=MARKERS[0], color=SLOTS[0], markersize=4, label="observed $\\Delta L_P$", zorder=3)
    ax.plot(x, [p["total"]["fin"] for p in ps], linestyle="none", marker=MARKERS[1], color=SLOTS[1], markersize=4, label="finite-source price", zorder=3)
    ax.plot([], [], color=SLOTS[2], linewidth=6, alpha=0.35, label="bracket [lo, hi]")
    ax.set_xticks(x)
    # A second seed at the same spacing is marked with an asterisk (caption).
    ax.set_xticklabels([f"{p['spacing_s']:g}" + ("*" if p["forced"].endswith("_s1") else "") for p in ps])
    ax.set_xlim(-0.6, len(ps) - 0.4)
    ax.set_ylabel("rise of $L_P$")
    ax.set_title("(e) short: price", loc="left", color=INK2, fontsize=7)
    ax.set_xlabel("spacing $s$ (s)", fontsize=7, labelpad=1)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.3), ncol=1, fontsize=6, handlelength=1.4, borderaxespad=0.0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--e1", default="data/exp/e1")
    ap.add_argument("--summary", default="data/exp/e2/summary.json")
    ap.add_argument("--summary-e2b", default="data/exp/e2b/summary.json")
    ap.add_argument("--prices", nargs="*", default=[])
    ap.add_argument("--out", default="paper/exp")
    a = ap.parse_args()
    style()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    fig_e1(Path(a.e1), out)
    fig_e2(Path(a.summary), out, Path(a.summary_e2b), [Path(p) for p in a.prices])
    print("wrote", out / "fig-e1.pdf", out / "fig-e2.pdf")


if __name__ == "__main__":
    main()

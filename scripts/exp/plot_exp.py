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
    ax.set_title(f"E1: $P(n,K)$, $K_c=a/b\\approx${fit['kc'] / 1000:.0f}k tokens", loc="left", color=INK2)
    ax.legend(loc="upper left")
    fig.savefig(out / "fig-e1.pdf", metadata=META)
    plt.close(fig)


def fig_e2(summary: Path, out: Path) -> None:
    runs = [r for r in json.load(open(summary)) if r]
    runs.sort(key=lambda r: (-float(r["params"].get("spacing_s", 0) or 0), -(int(r["params"].get("cap", 0) or 0) or 10**9)))
    labels = []
    for r in runs:
        cap = int(r["params"].get("cap", 0) or 0)
        labels.append(f"$s$={float(r['params'].get('spacing_s', 0)):g} s\n$N_{{\\max}}$={'∞' if cap == 0 else cap}")
    x = list(range(len(runs)))
    fig, axes = plt.subplots(1, 3, figsize=(6.8, 1.7))
    # (a) TTFT of hits, misses, p99
    ax = axes[0]
    ax.plot(x, [r["ttft_hit"] for r in runs], marker=MARKERS[0], color=SLOTS[0], label="follow-up hit (mean)")
    ax.plot(x, [r["ttft_miss"] for r in runs], marker=MARKERS[1], color=SLOTS[1], label="follow-up miss (mean)")
    ax.plot(x, [r["ttft_p99"] for r in runs], marker=MARKERS[2], color=SLOTS[2], label="all turns (p99)")
    ax.set_yscale("log")
    ax.set_ylabel("TTFT (s)")
    ax.set_title("(a) the price of a miss", loc="left", color=INK2)
    ax.legend(loc="center left", fontsize=6)
    # (b) hit rate and KV occupancy
    ax = axes[1]
    ax.plot(x, [100 * r["hit"] for r in runs], marker=MARKERS[0], color=SLOTS[0], label="follow-up hit rate")
    ax.plot(x, [100 * r["kv_usage"] for r in runs], marker=MARKERS[1], color=SLOTS[1], label="KV pool occupancy")
    ax.plot(x, [100 * r["rho_hi"] for r in runs], marker=MARKERS[2], color=SLOTS[2], label="prefill $\\rho$, busiest rank")
    ax.set_ylim(0, 170)
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.set_ylabel("%")
    ax.set_title("(b) cache and load", loc="left", color=INK2)
    ax.legend(loc="upper left", fontsize=6)
    # (c) waits: observed vs PK vs finite-source
    ax = axes[2]
    ax.plot(x, [r["q_srv"] for r in runs], marker=MARKERS[0], color=SLOTS[0], label="server queueing time")
    ax.plot(x, [r["w_fin"] for r in runs], marker=MARKERS[1], color=SLOTS[1], label="finite-source M/M/1//N")
    ax.plot(x, [r["pk"] for r in runs], marker=MARKERS[2], color=SLOTS[2], label="open PK")
    ax.set_yscale("log")
    ax.set_ylabel("mean wait (s)")
    lo = min(min(r["pk"] for r in runs), min(r["w_fin"] for r in runs)) / 8
    ax.set_ylim(bottom=lo)
    ax.set_title("(c) the wait and two predictions", loc="left", color=INK2)
    ax.legend(loc="upper right", fontsize=6)
    for ax in axes:
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
    fig.tight_layout(w_pad=1.0)
    fig.savefig(out / "fig-e2.pdf", metadata=META)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--e1", default="data/exp/e1")
    ap.add_argument("--summary", default="data/exp/e2/summary.json")
    ap.add_argument("--out", default="paper/exp")
    a = ap.parse_args()
    style()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    fig_e1(Path(a.e1), out)
    fig_e2(Path(a.summary), out)
    print("wrote", out / "fig-e1.pdf", out / "fig-e2.pdf")


if __name__ == "__main__":
    main()

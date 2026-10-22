#!/usr/bin/env python3
"""Figures 3-9 of the paper (writes figures/out/*.pdf and .png).

Sans fonts, no top/right spines, frameless legends, a semantic blue/green/red/neutral palette, 300 dpi.
Figures are drawn at the text width (6.5 in), so the font sizes below are the printed sizes.

Usage: python paper_figures.py [name ...]   names: levels cost quote region coupling patch method
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import matplotlib as mpl
import matplotlib.font_manager  # noqa: F401  (addfont below)
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

import style  # data helpers only; its rcParams are replaced below
from style import DATA, MODEL_ORDER, calls, canitedit_arms, paired, runs, wilson

OUT = Path(__file__).resolve().parent / "out"
W = 6.5  # inches: the arXiv text width, so every figure prints at its nominal font size

mpl.rcdefaults()
for _f in Path("/usr/share/texmf/fonts/opentype/public/tex-gyre").glob("texgyreheros-*.otf"):
    mpl.font_manager.fontManager.addfont(str(_f))
mpl.rcParams.update({
    "font.family": "sans-serif", "font.sans-serif": ["TeX Gyre Heros", "Helvetica", "Arial", "DejaVu Sans"],
    "mathtext.fontset": "dejavusans",
    "font.size": 8.5, "axes.titlesize": 9, "axes.titleweight": "normal", "axes.titlelocation": "left", "axes.titlepad": 6,
    "axes.labelsize": 8.5, "xtick.labelsize": 8, "ytick.labelsize": 8, "legend.fontsize": 8, "legend.frameon": False,
    "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": 0.8, "axes.edgecolor": "#333333",
    "axes.labelcolor": "#222222", "xtick.color": "#333333", "ytick.color": "#333333",
    "axes.grid": True, "axes.grid.axis": "y", "grid.color": "#E8E8E8", "grid.linewidth": 0.6, "axes.axisbelow": True,
    "xtick.major.size": 3, "ytick.major.size": 3, "xtick.major.width": 0.8, "ytick.major.width": 0.8,
    "lines.linewidth": 1.5, "lines.markersize": 5, "patch.linewidth": 0, "legend.numpoints": 1,
    "savefig.dpi": 300, "savefig.bbox": "tight", "savefig.pad_inches": 0.03, "pdf.fonttype": 42, "ps.fonttype": 42,
})

# Skill palette (figures4papers PALETTE), used semantically: the reference interface is neutral,
# pointing is green, the other quoting format is red, and our method is blue, with the ablation
# chain as lighter blues of the same hue.
P = {"blue_main": "#0F4D92", "blue_secondary": "#3775BA", "blue_light": "#9DBBE0",
     "green": "#5AAE61", "green_light": "#AADCA9", "red_strong": "#B64342", "red_2": "#E9A6A1",
     "neutral": "#767676", "neutral_light": "#CFCECE", "ink": "#272727",
     "teal": "#42949E", "violet": "#9A4D8E", "gold": "#D9A93A"}
COL = {"text": P["neutral"], "patch": P["red_strong"], "lines": P["green"],
       "p1": P["blue_light"], "p12": P["blue_secondary"], "ours": P["blue_main"]}
LAB = {"text": "search/replace", "patch": "patch", "lines": "line-range", "p1": "boundary check (P1)",
       "p12": "+ alignment (P1+P2)", "ours": "verified selection"}
MRK = {"text": "o", "patch": "s", "lines": "^", "ours": "D"}
ARMS = ["text", "patch", "lines"]
# Model names exactly as in the text, with a two-line form for crowded axes.
NAME = {"GPT-5.6-luna": "GPT-5.6-luna", "GLM-5.3": "GLM-5.3", "DeepSeek-V4-Flash": "DeepSeek-V4-Flash",
        "MiMo-v2.5-Pro": "MiMo-v2.5-Pro", "Qwen3.8-Flash": "Qwen3.8-Flash", "Claude-Sonnet-5": "Claude Sonnet 5"}
NAME2 = {"GPT-5.6-luna": "GPT-5.6\nluna", "GLM-5.3": "GLM-5.3", "DeepSeek-V4-Flash": "DeepSeek\nV4-Flash",
         "MiMo-v2.5-Pro": "MiMo\nv2.5-Pro", "Qwen3.8-Flash": "Qwen3.8\nFlash", "Claude-Sonnet-5": "Claude\nSonnet 5"}
CIE = MODEL_ORDER + ["Claude-Sonnet-5"]  # Claude ran text and lines only (Anthropic rejects the patch schema)


def model_runs(bench, model):
    frame = runs(None)
    if model == "Claude-Sonnet-5":
        return frame[(frame.batch == "claude") & (frame.model == model) & (frame.benchmark == bench)]
    return canitedit_arms(model) if bench == "canitedit" else runs()[lambda f: (f.model == model) & (f.benchmark == bench)]


def arms_of(model):
    return ["text", "lines"] if model == "Claude-Sonnet-5" else ARMS


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}.pdf"); fig.savefig(OUT / f"{name}.png", dpi=300); plt.close(fig)
    print("wrote", f"figures/out/{name}.pdf")


def pct_axis(ax, ticks):
    ax.set_yticks(ticks); ax.set_yticklabels([f"{t:.0%}" for t in ticks])


def ratio_axis(ax, ticks, axis="x"):
    labels = [("%g" % t) + "×" for t in ticks]
    if axis == "x":
        ax.set_xscale("log"); ax.set_xticks(ticks); ax.set_xticklabels(labels)
    else:
        ax.set_yscale("log"); ax.set_yticks(ticks); ax.set_yticklabels(labels)
    ax.minorticks_off()


# ------------------------------------------------------------------------------------------------
def fig_levels():
    """Result 1: first-edit acceptance varies far more than task success. Panels stacked so that the
    same model sits at the same x in both, with full model names."""
    groups = [("canitedit", m) for m in CIE] + [("aider-refactor", "GPT-5.6-luna"), ("aider-refactor", "MiMo-v2.5-Pro")]
    fig, axes = plt.subplots(2, 1, figsize=(W, 2.55), sharex=True, gridspec_kw={"hspace": 0.42})
    for ax, (col, title) in zip(axes, (("first_targeted_ok", "(a) First targeted edit accepted"), ("passed", "(b) Task success"))):
        for g, (bench, model) in enumerate(groups):
            every = model_runs(bench, model); am = arms_of(model)
            sub = paired(every[every.arm.isin(am)], am)
            for a, arm in enumerate(ARMS):
                if arm not in am: continue
                v = sub[sub.arm == arm][col].dropna(); lo, hi = wilson(v.sum(), len(v)); x = g + (a - 1) * 0.2
                ax.plot([x, x], [lo, hi], color=COL[arm], lw=1.1, alpha=0.75, solid_capstyle="butt", zorder=2)
                ax.plot(x, v.mean(), MRK[arm], color=COL[arm], mec="white", mew=0.6, ms=5.2, zorder=3)
        ax.axvline(len(CIE) - 0.5, color="#999999", lw=0.7, ls=(0, (2, 2)))
        ax.set_xlim(-0.5, len(groups) - 0.5); ax.set_ylim(0, 1.05); pct_axis(ax, [0, .25, .5, .75, 1])
        ax.set_title(title)
    ax = axes[1]
    ax.set_xticks(range(len(groups))); ax.set_xticklabels([NAME2[m] for _, m in groups])
    for x0, x1, lab in ((0, 5, "CanItEdit (short files)"), (6, 7, "refactors (long files)")):
        ax.annotate("", xy=(x0 - 0.38, -0.47), xytext=(x1 + 0.38, -0.47), xycoords=("data", "axes fraction"),
                    arrowprops=dict(arrowstyle="-", color="#AAAAAA", lw=0.7), annotation_clip=False)
        ax.text((x0 + x1) / 2, -0.51, lab, ha="center", va="top", fontsize=8, color="#444444", transform=ax.get_xaxis_transform())
    h = [Line2D([], [], color=COL[a], marker=MRK[a], mec="white", mew=0.6, lw=0, ms=5.5) for a in ARMS]
    fig.legend(h, [LAB[a] for a in ARMS], loc="upper center", ncol=3, bbox_to_anchor=(0.5, 1.05), handletextpad=0.3, columnspacing=1.8)
    save(fig, "fig_levels")


# ------------------------------------------------------------------------------------------------
def fig_cost():
    """Result 1: efficiency relative to search/replace within each model; cost of a rejected first edit."""
    E = pd.read_csv(DATA / "efficiency.csv"); F = pd.read_csv(DATA / "failed_first_edit.csv")
    rows = [("canitedit", m) for m in CIE] + [("aider-refactor", "GPT-5.6-luna"), ("aider-refactor", "MiMo-v2.5-Pro")]
    labels = [NAME[m] + (" · refactor" if b == "aider-refactor" else "") for b, m in rows]
    # Claude's line-range efficiency, computed as in efficiency.py (paired tasks, 2,000 bootstrap resamples)
    cw = paired(model_runs("canitedit", "Claude-Sonnet-5"), ["text", "lines"]).pivot(index="task", columns="arm", values=["passed", "output_tokens", "cost_usd"]).apply(pd.to_numeric, errors="coerce").dropna()
    rng = np.random.default_rng(0); extra = []
    for k, per in (("output_tokens", "output"), ("cost_usd", "dollar")):
        def e(idx, a): return cw["passed"][a].iloc[idx].sum() / cw[k][a].iloc[idx].sum()
        full = np.arange(len(cw)); r0 = e(full, "lines") / e(full, "text")
        bs = np.sort([e(i, "lines") / e(i, "text") for i in (rng.integers(0, len(cw), len(cw)) for _ in range(2000))])
        extra.append(dict(bench="canitedit", model="Claude-Sonnet-5", arm="lines", per=per, n=len(cw), rel=r0, lo=bs[50], hi=bs[1949]))
    E = pd.concat([E, pd.DataFrame(extra)], ignore_index=True)
    fig, axes = plt.subplots(1, 3, figsize=(W, 2.75), sharey=True, gridspec_kw={"width_ratios": [1.15, 1.15, 0.95], "wspace": 0.1})
    for ax, per, title in ((axes[0], "output", "(a) Solved per output token"), (axes[1], "dollar", "(b) Solved per dollar")):
        for i, (b, m) in enumerate(rows):
            for j, arm in enumerate(("patch", "lines")):
                r = E[(E.bench == b) & (E.model == m) & (E.arm == arm) & (E.per == per)]
                if r.empty: continue
                r = r.iloc[0]; y = i + (j - 0.5) * 0.32; sig = r.lo > 1 or r.hi < 1
                ax.plot([r.lo, r.hi], [y, y], color=COL[arm], lw=1.1, solid_capstyle="butt")
                ax.plot(r.rel, y, MRK[arm], ms=4.6, color=COL[arm], mfc=COL[arm] if sig else "white", mew=1.0)
        ax.axvline(1, color=COL["text"], lw=1.0); ratio_axis(ax, [0.25, 0.5, 1, 2]); ax.set_xlim(0.2, 2.8)
        ax.axhline(len(CIE) - 0.5, color="#BBBBBB", lw=0.7, ls=(0, (2, 2))); ax.grid(axis="x"); ax.grid(axis="y", visible=False)
        ax.set_title(title); ax.set_xlabel("relative to search/replace")
    axes[0].set_yticks(range(len(rows))); axes[0].set_yticklabels(labels); axes[0].invert_yaxis()
    ax = axes[2]
    for i, (b, m) in enumerate(rows):
        for measure, mk, c, dy in (("output", "o", P["ink"], -0.16), ("cost", "s", "#A0A0A0", 0.16)):
            r = F[(F.bench == b) & (F.model == m) & (F.measure == measure)]
            if not r.empty: ax.plot(r.ratio.iloc[0], i + dy, mk, ms=4.4, color=c)
    ax.axvline(1, color=COL["text"], lw=1.0); ratio_axis(ax, [1, 2, 4]); ax.set_xlim(0.85, 6)
    ax.axhline(len(CIE) - 0.5, color="#BBBBBB", lw=0.7, ls=(0, (2, 2))); ax.grid(axis="x"); ax.grid(axis="y", visible=False)
    ax.set_title("(c) Rejected vs accepted first edit"); ax.set_xlabel("cost ratio, same task")
    last = len(rows) - 1; b, m = rows[last]
    for measure, c, dy, lab in (("output", P["ink"], -0.16, "output tokens"), ("cost", "#808080", 0.16, "dollars")):
        r = F[(F.bench == b) & (F.model == m) & (F.measure == measure)]
        ax.text(r.ratio.iloc[0] * 1.22, last + dy, lab, ha="left", va="center", fontsize=7.5, color=c)
    h = [Line2D([], [], color=COL[a], marker=MRK[a], ms=4.6, lw=1.1) for a in ("patch", "lines")] + \
        [Line2D([], [], color="#555555", marker="o", ms=4.6, lw=0, mfc="white", mew=1.0)]
    fig.legend(h, ["patch", "line-range", "open marker: 95% interval includes 1×"],
               loc="upper center", ncol=3, bbox_to_anchor=(0.55, 1.05), handletextpad=0.4, columnspacing=1.8)
    save(fig, "fig_cost")


# ------------------------------------------------------------------------------------------------
def fig_quote():
    """Result 2: two ways a quoted target fails, by quoted length; odds ratios per doubling."""
    d = pd.read_csv(DATA / "edits_text.csv"); d["old_tok"] = d.old_chars / 4.0
    edges = [0, 25, 50, 100, 200, 400, 800, 1e9]; labels = ["<25", "25–50", "50–100", "100–200", "200–400", "400–800", "800+"]
    d["bin"] = pd.cut(d.old_tok, edges, labels=labels, right=False)
    OC = {"miss": (P["violet"], "s", "matches nothing"), "ambig": (P["teal"], "o", "matches 2+ places")}
    fig, axes = plt.subplots(1, 2, figsize=(W, 2.6), gridspec_kw={"width_ratios": [1.9, 1], "wspace": 0.42})
    ax = axes[0]; x = np.arange(len(labels))
    for key, outcome in (("miss", d.matches == 0), ("ambig", d.matches >= 2)):
        c, mk, lab = OC[key]
        g = d.assign(y=outcome.astype(int)).groupby("bin", observed=False).y.agg(["sum", "size"])
        ci = np.array([wilson(k, n) for k, n in zip(g["sum"], g["size"])])
        ax.fill_between(x, ci[:, 0], ci[:, 1], color=c, alpha=0.13, lw=0)
        ax.plot(x, g["sum"] / g["size"], "-", color=c, marker=mk, mec="white", mew=0.6, label=lab)
    n = d.groupby("bin", observed=False).size()
    ax.set_xticks(x); ax.set_xticklabels([f"{l}\n{k:,}" for l, k in zip(labels, n)], fontsize=7)
    ax.set_xlabel("tokens of old text quoted (second row: number of edits)"); ax.set_ylim(0, 0.29); pct_axis(ax, [0, .1, .2])
    ax.set_ylabel("share of search/replace edits"); ax.legend(loc="upper left", title="quoted text…", title_fontsize=8, alignment="left")
    ax.set_title("(a) Failure rate by quoted length")

    def irls(X, y, iters=40):
        b = np.zeros(X.shape[1])
        for _ in range(iters):
            p = 1 / (1 + np.exp(-np.clip(X @ b, -30, 30))); Wt = p * (1 - p) + 1e-9
            b = b + np.linalg.solve(X.T @ (X * Wt[:, None]) + 1e-4 * np.eye(X.shape[1]), X.T @ (y - p))
        return b
    models = sorted(d.model.unique())
    def design(f): return np.column_stack([np.ones(len(f)), np.log2(f.old_tok + 1), np.log2(f.new_chars / 4 + 1), np.log2(f.file_lines)] + [(f.model == m).astype(float) for m in models[1:]])
    rng = np.random.default_rng(20260921); tasks = d.task.unique(); groups = {t: g for t, g in d.groupby("task")}
    ax = axes[1]; names = ["old text\nquoted", "new text\nwritten", "file\nlength"]
    for k, key in enumerate(("miss", "ambig")):
        c, mk, _ = OC[key]
        y_of = (lambda f: (f.matches == 0).to_numpy(float)) if key == "miss" else (lambda f: (f.matches >= 2).to_numpy(float))
        point = irls(design(d), y_of(d))[1:4]; boots = []
        for _ in range(400):
            f = pd.concat([groups[t] for t in rng.choice(tasks, len(tasks))]); boots.append(irls(design(f), y_of(f))[1:4])
        lo, hi = np.percentile(np.array(boots), [2.5, 97.5], axis=0)
        for i in range(3):
            yy = i + (k - 0.5) * 0.3
            ax.plot([np.exp(lo[i]), np.exp(hi[i])], [yy, yy], color=c, lw=1.3, solid_capstyle="butt")
            ax.plot(np.exp(point[i]), yy, mk, color=c, mec="white", mew=0.6, ms=5.2)
        print(key, " | ".join(f"{nm}: OR {np.exp(p):.2f} [{np.exp(l):.2f}, {np.exp(h):.2f}]" for nm, p, l, h in zip(names, point, lo, hi)))
    ax.axvline(1, color="#555555", lw=0.9); ratio_axis(ax, [0.25, 0.5, 1, 2]); ax.set_xticklabels(["0.25", "0.5", "1", "2"])
    ax.set_yticks(range(3)); ax.set_yticklabels(names, va="center"); ax.tick_params(axis="y", length=0)
    ax.set_ylim(2.6, -0.6); ax.grid(axis="x"); ax.grid(axis="y", visible=False)
    ax.set_xlabel("odds ratio per doubling"); ax.set_title("(b) What predicts each failure")
    save(fig, "fig_quote_length")


# ------------------------------------------------------------------------------------------------
def fig_region():
    """Result 2: clean first application by region size; for regions of 200+ tokens, visible
    rejections and silent breakage side by side, each labelled with its own share."""
    d = pd.read_csv(DATA / "first_calls.csv")
    d["clean"] = ((d.applied == 1) & (d.syntax_ok == 1)).astype(int)
    edges = [0, 50, 100, 200, 400, 800, 1e9]; labels = ["<50", "50–100", "100–200", "200–400", "400–800", "800+"]
    d["bin"] = pd.cut(d.region_tokens, edges, labels=labels, right=False)
    fig, axes = plt.subplots(1, 2, figsize=(W, 2.6), gridspec_kw={"width_ratios": [1.45, 1], "wspace": 0.32})
    ax = axes[0]; x = np.arange(len(labels))
    for form, off in (("text", -0.12), ("patch", 0.0), ("lines", 0.12)):
        g = d[d.form == form].groupby("bin", observed=False).clean.agg(["sum", "size"]); keep = g["size"] >= 15
        rate = (g["sum"] / g["size"]).where(keep)
        ax.plot(x + off, rate, "-", color=COL[form], marker=MRK[form], mec="white", mew=0.6, label=LAB[form], zorder=3)
        for xi, (k, nn, ok) in zip(x + off, zip(g["sum"], g["size"], keep)):
            if ok: lo, hi = wilson(k, nn); ax.plot([xi, xi], [lo, hi], color=COL[form], lw=0.9, alpha=0.55, zorder=2)
    ax.set_xticks(x); ax.set_xticklabels(labels); ax.set_xlabel("tokens of code replaced")
    ax.set_ylim(0.45, 1.01); pct_axis(ax, [.5, .6, .7, .8, .9, 1]); ax.set_ylabel("clean first edits")
    ax.legend(loc="lower left"); ax.set_title("(a) Accepted and still parses, by region size")
    mpl.rcParams["hatch.linewidth"] = 0.6
    ax = axes[1]; big = d[d.region_tokens >= 200]; bw = 0.36
    for i, form in enumerate(ARMS):
        s = big[big.form == form]; loud = (s.applied == 0).mean(); silent = ((s.applied == 1) & (s.syntax_ok == 0)).mean()
        ax.bar(i - bw / 2, loud, bw * 0.94, color=COL[form])
        ax.bar(i + bw / 2, silent, bw * 0.94, color="white", edgecolor=COL[form], linewidth=1.0, hatch="////")
        for xx, v in ((i - bw / 2, loud), (i + bw / 2, silent)):
            ax.text(xx, v + 0.006, f"{v:.0%}", ha="center", va="bottom", fontsize=7.5, color="#222222")
    ax.set_xticks(range(3)); ax.set_xticklabels([f"{LAB[a]}\n(n={len(big[big.form == a])})" for a in ARMS], fontsize=7.5)
    ax.set_ylim(0, 0.3); pct_axis(ax, [0, .1, .2, .3]); ax.set_ylabel("share of first edits")
    ax.legend([Patch(color="#555555"), Patch(facecolor="white", edgecolor="#555555", hatch="////", linewidth=1.0)],
              ["rejected (visible)", "applied, does not parse (silent)"], loc="upper left", handlelength=1.2)
    ax.set_title("(b) How edits of 200+ tokens fail")
    save(fig, "fig_region_size")


# ------------------------------------------------------------------------------------------------
def fig_coupling():
    """Result 3: packaging of the same three forms, and the position of a tool in the list."""
    EF = pd.read_csv(DATA / "efficiency.csv")
    CELLS = [("choice", "one tool", P["teal"]), ("guided", "one tool + advice", "#A9D3D8"),
             ("tools", "three tools", P["violet"]), ("tools_guided", "three tools + advice", "#D7B8D2")]
    MODELS = ["GPT-5.6-luna", "MiMo-v2.5-Pro"]
    fig, axes = plt.subplots(1, 3, figsize=(W, 2.6), gridspec_kw={"width_ratios": [1, 1, 1.35], "wspace": 0.4})
    for ax, (col, title) in zip(axes[:2], (("first_edit_ok", "(a) First edit accepted"), ("tps", "(b) Solved per output token"))):
        for g, model in enumerate(MODELS):
            every = canitedit_arms(model); sub = paired(every, ["text"] + [c[0] for c in CELLS])
            ref = 1.0 if col == "tps" else sub[sub.arm == "text"][col].mean()
            ax.plot([g - 0.42, g + 0.42], [ref, ref], color=P["ink"], lw=1.1, ls=(0, (3, 2)), zorder=4)
            for c, (arm, label, color) in enumerate(CELLS):
                x = g + (c - 1.5) * 0.2
                if col == "tps":
                    r = EF[(EF.bench == "canitedit") & (EF.model == model) & (EF.arm == arm) & (EF.per == "output")].iloc[0]; val, lo, hi = r.rel, r.lo, r.hi
                else:
                    s = sub[sub.arm == arm][col]; val = s.mean(); lo, hi = wilson(s.sum(), len(s))
                ax.bar(x, val, 0.18, color=color, zorder=2); ax.plot([x, x], [lo, hi], color="#444444", lw=0.8, zorder=3)
        ax.set_xticks(range(2)); ax.set_xticklabels([NAME2[m] for m in MODELS]); ax.set_title(title)
        if col == "tps": ax.set_ylim(0, 1.6); ax.set_yticks([0, 0.5, 1, 1.5]); ax.set_yticklabels(["0", "0.5×", "1×", "1.5×"])
        else: ax.set_ylim(0, 1.05); pct_axis(ax, [0, .25, .5, .75, 1])
    tool_form = {"edit_lines": "lines", "edit_text": "text", "apply_patch": "patch"}
    ax = axes[2]; mods = ["GPT-5.6-luna", "Qwen3.8-Flash", "MiMo-v2.5-Pro"]
    for m, model in enumerate(mods):
        every = canitedit_arms(model); sub = every[(every.arm == "tools") & every.first_tool.notna()]
        picked = sub.first_tool.map(tool_form).where(sub.first_form != "content", "content")
        for a, form in enumerate(("lines", "text", "patch")):
            first = sub.choice_order.str.startswith(form)
            p1, n1, p0, n0 = (picked[first] == form).mean(), first.sum(), (picked[~first] == form).mean(), (~first).sum()
            lift = p1 - p0; half = 1.96 * np.sqrt(p1 * (1 - p1) / n1 + p0 * (1 - p0) / n0); x = m + (a - 1) * 0.26
            ax.bar(x, lift, 0.24, color=COL[form], zorder=2); ax.plot([x, x], [lift - half, lift + half], color="#444444", lw=0.8, zorder=3)
    ax.axhline(0, color="#555555", lw=0.8); ax.set_xticks(range(3)); ax.set_xticklabels([NAME2[m] for m in mods])
    ax.set_ylim(-0.65, 1.15); ax.set_yticks([-0.5, 0, 0.5, 1]); ax.set_ylabel("change in P(called first)")
    ax.set_title("(c) Effect of being listed first")
    h = [Patch(color=c) for _, _, c in CELLS] + [Line2D([], [], color=P["ink"], lw=1.1, ls=(0, (3, 2)))]
    fig.legend(h, [l for _, l, _ in CELLS] + ["search/replace alone"], loc="upper left", ncol=5, bbox_to_anchor=(0.04, 1.06),
               handlelength=1.2, handletextpad=0.35, columnspacing=1.1, fontsize=7.5)
    ax.legend([Patch(color=COL[f]) for f in ("lines", "text", "patch")], ["line-range", "search/replace", "patch"], loc="lower left",
              handlelength=1.0, handletextpad=0.3, labelspacing=0.3, fontsize=7.5, borderaxespad=0.1)
    save(fig, "fig_coupling")


# ------------------------------------------------------------------------------------------------
def fig_patch():
    """Result 3: rejected patch calls by the rule of the stated patch format that the call broke.
    Errors in the patch's structure get distinct hues; the remaining errors are greys."""
    frame = calls(); frame = frame[(frame.benchmark == "canitedit") & (frame.arm == "patch") & (frame.ok == 0)].copy()
    def group(row):
        c = row.error_class
        if c == "patch: context-only hunk": return "codex_ctx"
        if c == "patch: non-bare @@ header": return "codex_hdr" if row.header_style == "codex-style" else "git_hdr"
        if c == "patch: duplicated envelope / unsupported operation": return "envelope"
        if c == "patch: missing Begin/End markers": return "markers"
        if c in ("patch: sent without revisions", "stale revision"): return "revision"
        if c.startswith("text:"): return "context"
        return "other"
    frame["group"] = frame.apply(group, axis=1)
    ORDER = [("envelope", "duplicated envelope / unsupported operation", P["red_strong"]), ("markers", "missing Begin/End markers", P["gold"]),
             ("git_hdr", "git-style @@ header", P["teal"]), ("codex_hdr", "@@ header with text", P["violet"]), ("codex_ctx", "context-only hunk", P["blue_secondary"]),
             ("context", "context does not match", "#4D4D4D"), ("revision", "missing or stale revision", "#9A9A9A"), ("other", "malformed / other", "#D6D6D6")]
    DARK = {P["red_strong"], P["teal"], P["violet"], P["blue_secondary"], "#4D4D4D"}
    models = list(reversed(MODEL_ORDER)); totals = [len(frame[frame.model == m]) for m in models]
    fig, ax = plt.subplots(figsize=(W, 2.15)); left = np.zeros(len(models))
    for key, label, color in ORDER:
        shares = np.array([(frame[frame.model == m].group == key).sum() / max(t, 1) for m, t in zip(models, totals)])
        ax.barh(range(len(models)), shares, left=left, color=color, height=0.68, label=label, edgecolor="white", linewidth=0.6)
        for y, (s, l) in enumerate(zip(shares, left)):
            if s >= 0.07: ax.text(l + s / 2, y, f"{s:.0%}", ha="center", va="center", fontsize=7.5, color="white" if color in DARK else "#222222")
        left += shares
    ax.set_yticks(range(len(models))); ax.set_yticklabels([f"{NAME[m]} (n={t})" for m, t in zip(models, totals)])
    ax.set_xlim(0, 1); ax.set_xticks([0, .25, .5, .75, 1]); ax.set_xticklabels(["0", "25%", "50%", "75%", "100%"])
    ax.set_xlabel("share of rejected patch calls"); ax.grid(axis="x"); ax.grid(axis="y", visible=False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.42, -0.27), ncol=3, handlelength=1.1, columnspacing=1.2, fontsize=7.5)
    save(fig, "fig_patch_failures")


# ------------------------------------------------------------------------------------------------
def fig_method():
    """Result 4: the ablation chain on the refactors for GPT-5.6-luna and MiMo (same tasks as tab:method).
    Our method and its ablations are one hue, light to dark; broken-edit counts sit in one row."""
    here = os.getcwd(); os.chdir(Path(__file__).resolve().parent.parent)
    ns: dict = {}
    src = open("method_table.py").read().split("rng = np.random.default_rng(0); B = 2000")[0]
    exec(src, ns)
    os.chdir(here)
    arms = [("text", "text"), ("lines", "lines"), ("verified", "p1"), ("aligned", "p12"), ("ref", "ours")]
    rng = np.random.default_rng(0)
    res = {}
    os.chdir(Path(__file__).resolve().parent.parent)
    for model, spec in ns["SETS"].items():
        data = {name: ns["load"](d, arm, name in ("aligned", "ref")) for name, d, arm in spec}
        common = sorted(set.intersection(*(set(v) for v in data.values())))
        base = [data["text"][t] for t in common]
        def eff(rs, idx): return sum(rs[i]["passed"] for i in idx) / sum(rs[i]["out"] for i in idx)
        for name, key in arms:
            rs = [data[name][t] for t in common]; n = len(rs)
            acc = sum(bool(r["first"]) for r in rs); applied = [r for r in rs if r["first"] and r["broken"] is not None]; brk = sum(r["broken"] for r in applied)
            full = np.arange(n); e0 = eff(rs, full) / eff(base, full)
            bs = np.sort([eff(rs, i) / eff(base, i) for i in (rng.integers(0, n, n) for _ in range(2000))])
            res[(model, key)] = dict(acc=acc / n, acc_ci=wilson(acc, n), brk=brk / max(len(applied), 1), brk_ci=wilson(brk, len(applied)), brk_n=(brk, len(applied)),
                                      eff=e0, eff_ci=(bs[50], bs[1949]))
    REP = {"GPT-5.6-luna": {"text": ("refactor-luna-rep1", "text"), "lines": ("refactor-luna-rep1", "lines"), "ours": ("refactor-luna-ref-rep1", "lines_anchored")},
           "MiMo-v2.5-Pro": {"text": ("refactor-mimo-rep1", "text"), "lines": ("refactor-mimo-rep1", "lines"), "ours": ("refactor-mimo-ref-rep1", "lines_anchored")}}
    rep = {}
    for model, spec in REP.items():
        d1 = {k: ns["load"](d, arm, arm == "lines_anchored") for k, (d, arm) in spec.items()}
        common = sorted(set.intersection(*(set(v) for v in d1.values())))
        base = [d1["text"][t] for t in common]
        def eff1(rs): return sum(r["passed"] for r in rs) / sum(r["out"] for r in rs)
        for k in spec:
            rs = [d1[k][t] for t in common]; applied = [r for r in rs if r["first"] and r["broken"] is not None]
            rep[(model, k)] = dict(acc=sum(bool(r["first"]) for r in rs) / len(rs), brk=sum(r["broken"] for r in applied) / max(len(applied), 1), eff=eff1(rs) / eff1(base))
    os.chdir(here)
    models = list(ns["SETS"])
    fig, axes = plt.subplots(1, 3, figsize=(W, 2.75), gridspec_kw={"wspace": 0.42})
    width = 0.16
    for ax, metric, title in ((axes[0], "acc", "(a) First edit accepted ↑"), (axes[1], "brk", "(b) Broken first edits ↓"),
                              (axes[2], "eff", "(c) Solved per output token ↑")):
        for g, model in enumerate(models):
            for a, (_, key) in enumerate(arms):
                if metric == "eff" and key == "text": continue
                r = res[(model, key)]; x = g + (a - 2) * width
                val = r[metric]; lo, hi = r[metric + "_ci"]
                ax.bar(x, val, width * 0.92, color=COL[key], zorder=2)
                ax.plot([x, x], [lo, hi], color="#444444", lw=0.8, zorder=3)
                if (model, key) in rep:
                    ax.plot(x, rep[(model, key)][metric], "D", ms=4.2, color="#111111", mfc="white", mew=0.9, zorder=5)
                if metric == "brk":
                    k, n = r["brk_n"]; ax.text(x, 0.69, f"{k}", ha="center", va="bottom", fontsize=7, color="#444444")
        ax.set_xticks(range(len(models))); ax.set_xticklabels([NAME2[m] for m in models]); ax.set_title(title)
        if metric == "eff":
            ax.axhline(1, color=COL["text"], lw=1.1, ls=(0, (3, 2)), zorder=4); ax.set_ylim(0, 2.5)
            ax.set_yticks([0, 0.5, 1, 1.5, 2, 2.5]); ax.set_yticklabels(["0", "0.5×", "1×", "1.5×", "2×", "2.5×"])
            ax.set_ylabel("vs search/replace (dashed)")
        elif metric == "brk":
            ax.set_ylim(0, 0.8); pct_axis(ax, [0, .25, .5]); ax.set_ylabel("of accepted first edits")
            ax.text(-0.45, 0.755, "count", ha="left", va="bottom", fontsize=7, color="#444444")
        else:
            ax.set_ylim(0, 1.05); pct_axis(ax, [0, .25, .5, .75, 1])
    h = [Patch(color=COL[k]) for _, k in arms] + [Line2D([], [], marker="D", ms=4.2, color="#111111", mfc="white", mew=0.9, lw=0)]
    fig.legend(h, [LAB[k] for _, k in arms] + ["second run"], loc="upper center", ncol=6, bbox_to_anchor=(0.5, 1.04), handlelength=1.1,
               handletextpad=0.35, columnspacing=0.9, fontsize=7.5)
    save(fig, "fig_method")
    for k, v in res.items(): print(k, {m: (round(v[m], 3) if not isinstance(v[m], tuple) else tuple(round(float(z), 3) for z in v[m])) for m in ("acc", "brk", "eff", "eff_ci")}, v["brk_n"])


FIGS = {"levels": fig_levels, "cost": fig_cost, "quote": fig_quote, "region": fig_region, "coupling": fig_coupling, "patch": fig_patch, "method": fig_method}
if __name__ == "__main__":
    for name in (sys.argv[1:] or list(FIGS)):
        FIGS[name]()

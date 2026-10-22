"""Shared look and helpers for every figure in the paper."""
from __future__ import annotations

import math
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import os

import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"

mpl.rcParams.update({
    "font.family": "serif", "font.serif": ["TeX Gyre Termes", "Nimbus Roman", "Times New Roman", "STIXGeneral", "DejaVu Serif"],
    "mathtext.fontset": "stix",
    "font.size": 8.5, "axes.titlesize": 9, "axes.titleweight": "bold", "axes.labelsize": 8.5,
    "xtick.labelsize": 7.5, "ytick.labelsize": 7.5, "legend.fontsize": 7.5, "legend.frameon": False,
    "figure.dpi": 150, "savefig.dpi": 300, "savefig.bbox": "tight", "savefig.pad_inches": 0.02,
    "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": 0.6,
    "axes.grid": True, "grid.alpha": 0.18, "grid.linewidth": 0.5,
    "xtick.major.width": 0.6, "ytick.major.width": 0.6, "xtick.major.size": 2.5, "ytick.major.size": 2.5,
    "lines.linewidth": 1.4, "lines.markersize": 4.5, "pdf.fonttype": 42, "ps.fonttype": 42,
})

FULL, SINGLE = 6.75, 3.25  # inches

# Okabe-Ito, one fixed colour and marker per edit interface across all figures.
FORMAT_COLOR = {"text": "#0072B2", "patch": "#D55E00", "lines": "#009E73",
                "choice": "#CC79A7", "guided": "#E69F00", "tools": "#56B4E9", "tools_guided": "#999999"}
FORMAT_MARKER = {"text": "o", "patch": "s", "lines": "^", "choice": "D", "guided": "v", "tools": "P", "tools_guided": "X"}
FORMAT_LABEL = {"text": "search/replace", "patch": "patch", "lines": "line-range",
                "choice": "menu: one tool", "guided": "menu: one tool + advice", "tools": "menu: three tools", "tools_guided": "menu: three tools + advice"}
MODEL_ORDER = ["GPT-5.6-luna", "GLM-5.3", "DeepSeek-V4-Flash", "MiMo-v2.5-Pro", "Qwen3.8-Flash"]
MODEL_SHORT = {"GPT-5.6-luna": "GPT-5.6\nluna", "GLM-5.3": "GLM\n5.3", "DeepSeek-V4-Flash": "DeepSeek\nV4-Flash",
               "MiMo-v2.5-Pro": "MiMo\nv2.5-Pro", "Qwen3.8-Flash": "Qwen3.8\nFlash"}
BENCH_LABEL = {"canitedit": "CanItEdit\n(median 31 lines)", "aider-refactor": "Aider refactor\n(median 720 lines)"}


def runs(batch: str | None = "main") -> pd.DataFrame:
    frame = pd.read_csv(DATA / "runs.csv")
    return frame if batch is None else frame[frame.batch == batch]


def calls(batch: str | None = "main") -> pd.DataFrame:
    frame = pd.read_csv(DATA / "edit_calls.csv")
    return frame if batch is None else frame[frame.batch == batch]


def canitedit_arms(model: str) -> pd.DataFrame:
    """Every CanItEdit arm of one model. Single interfaces come from the main batch;
    GPT-5.6-luna's four menu arms come from its own contemporaneous batch."""
    frame = runs(None)
    frame = frame[(frame.model == model) & (frame.benchmark == "canitedit")]
    if model == "GPT-5.6-luna":
        singles = frame[(frame.batch == "main") & frame.arm.isin(["text", "patch", "lines"])]
        menus = frame[(frame.batch == "ablation") & frame.arm.isin(["choice", "guided", "tools", "tools_guided"])]
        return pd.concat([singles, menus])
    return frame[frame.batch == "main"]


def wilson(successes: float, total: int, z: float = 1.959964) -> tuple[float, float]:
    if not total:
        return (float("nan"), float("nan"))
    p = successes / total
    centre = (p + z * z / (2 * total)) / (1 + z * z / total)
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return centre - half, centre + half


def paired(frame: pd.DataFrame, arms: list[str]) -> pd.DataFrame:
    """Rows of `frame` restricted to tasks that have a valid run in every arm."""
    sub = frame[frame.arm.isin(arms)]
    counts = sub.groupby("task").arm.nunique()
    return sub[sub.task.isin(counts[counts == len(arms)].index)]


def save(fig, name: str) -> None:
    fig.savefig(HERE / f"{name}.pdf")
    fig.savefig(HERE / f"{name}.png", dpi=300)
    plt.close(fig)
    print(f"wrote figures/{name}.pdf and .png")

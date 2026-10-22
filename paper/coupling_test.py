#!/usr/bin/env python3
"""Is interface fit additive (pi + H) or coupled (pi (+) H)? Likelihood-ratio test of the model x interface
interaction in a logistic regression, on the main-study CanItEdit runs (5 models x 3 interfaces, tasks paired).
Outcomes: first targeted edit accepted, and task success. A task fixed effect absorbs task difficulty."""
import sys
import numpy as np, pandas as pd
sys.path.insert(0, "figures")
from style import runs, paired, MODEL_ORDER

def fit(X, y, iters=60, ridge=1e-6):
    b = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-np.clip(X @ b, -30, 30))); W = p * (1 - p) + 1e-9
        b = b + np.linalg.solve(X.T @ (X * W[:, None]) + ridge * np.eye(X.shape[1]), X.T @ (y - p))
    p = np.clip(1 / (1 + np.exp(-np.clip(X @ b, -30, 30))), 1e-12, 1 - 1e-12)
    return float(np.sum(y * np.log(p) + (1 - y) * np.log(1 - p)))

def design(df, interaction):
    cols = [np.ones(len(df))]
    for m in MODEL_ORDER[1:]: cols.append((df.model == m).astype(float).to_numpy())
    for a in [x for x in ARMS_ENV if x != "text"]: cols.append((df.arm == a).astype(float).to_numpy())
    for t in sorted(df.task.unique())[1:]: cols.append((df.task == t).astype(float).to_numpy())
    if interaction:
        for m in MODEL_ORDER[1:]:
            for a in [x for x in ARMS_ENV if x != "text"]: cols.append(((df.model == m) & (df.arm == a)).astype(float).to_numpy())
    return np.column_stack(cols)

import math
def chi2_sf_even(x, k):
    """Survival function of chi-square with even degrees of freedom k (closed form)."""
    h = x / 2
    if k % 2 == 0:
        return math.exp(-h) * sum(h ** i / math.factorial(i) for i in range(k // 2))
    # odd k: series for the regularized upper gamma via erfc
    t = math.erfc(math.sqrt(h)); term = math.sqrt(h) * math.exp(-h) / math.gamma(1.5); acc = 0.0
    for i in range(k // 2):
        acc += term; term *= h / (i + 1.5)
    return t + acc
import os
ARMS_ENV = os.environ.get("ARMS", "text,patch,lines").split(",")
R = runs(); R = R[(R.benchmark == "canitedit") & R.arm.isin(ARMS_ENV)]
frames = []
for m in MODEL_ORDER:
    frames.append(paired(R[R.model == m], ARMS_ENV))
D = pd.concat(frames)
for col in ("first_targeted_ok", "passed"):
    df = D.dropna(subset=[col]).copy(); y = df[col].astype(float).to_numpy()
    l0 = fit(design(df, False), y); l1 = fit(design(df, True), y)
    lr = 2 * (l1 - l0); k = (len(MODEL_ORDER) - 1) * (len(ARMS_ENV) - 1)
    print(f"{col:18s} n={len(df)} LR={lr:.1f} df={k} p={chi2_sf_even(lr, k):.2e}")
    # share of variance: interface main effect vs interaction (deviance explained)
    print(f"   deviance: models+tasks+interfaces {-2*l0:.1f} -> +interaction {-2*l1:.1f}")

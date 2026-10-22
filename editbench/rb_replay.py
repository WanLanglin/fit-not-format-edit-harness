#!/usr/bin/env python3
"""Offline replay of the RefactorBench runs: which first targeted edits were accepted but broke a Python file.

Every accepted apply_patch call of a run is replayed, in order, on a virtual copy of the task's repository,
with the executor's rules for each form: exact-once replacement (text), bottom-up line ranges (lines),
Codex-style update/add hunks (patch), and for lines_anchored the +-3 boundary alignment, restated-neighbour
absorption and @@ref expansion, including @@ref path:A-B@@ across files and in new-file content.
The first targeted call (one that carries line or text edits or patch hunks) is "broken" when it was
accepted and leaves a touched .py file unparsable that parsed before (or did not exist).
The replay checks itself: after all accepted calls, every file it touched must equal the run's final workspace.

Usage: rb_replay.py [RUNS_DIR] [--tasks N]
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "adapters"))
import refactorbench as rb  # noqa: E402

ARMS = ["text", "lines", "patch", "lines_anchored"]
MARK = re.compile(r"^(\s*)@@ref\s+(?:(.+):)?\s*(\d+)\s*-\s*(\d+)\s*@@\s*$")


def dec(v):
    if isinstance(v, dict) and "hex" in v:
        return bytes.fromhex(v["hex"]).decode("utf-8", "replace")
    return v if isinstance(v, str) else ("" if v is None else json.dumps(v))


def parses(text: str) -> bool:
    try:
        ast.parse(text)
        return True
    except (SyntaxError, ValueError):
        return False


def norm_path(p: str) -> str:
    return "/".join(x for x in p.strip().split("/") if x not in ("", "."))


def norm(s):
    s = (s or "").strip()
    if ": " in s and s.split(": ", 1)[0].isdigit():
        s = s.split(": ", 1)[1].strip()
    return s


def snap(L, n, quote, lo=1):
    if 0 < n <= len(L) and L[n - 1] == quote:
        return n
    hits = [x for x in range(max(lo, n - 3), min(len(L), n + 3) + 1) if L[x - 1] == quote]
    if not hits:
        return None
    best = min(abs(x - n) for x in hits)
    near = [x for x in hits if abs(x - n) == best]
    return near[0] if len(near) == 1 else None


def place(R, e):
    """Executor placement of one anchored edit on lines R (same rules as place_line_edit)."""
    L = [x.strip() for x in R]
    s0, t0 = e["start_line"], e["end_line"]
    s = snap(L, s0, norm(e.get("first_line")))
    t = None if s is None else snap(L, t0, norm(e.get("last_line")), lo=s)
    if s is None or t is None or t < s:
        raise ValueError("anchors not found")

    def blank_only(a, b):
        lo, hi = min(a, b), max(a, b)
        return a == b or (all(L[x - 1] == "" for x in range(lo + 1, hi)) and (L[lo - 1] == "" or L[hi - 1] == ""))

    even = abs(s - s0) == abs(t - t0) and (s >= s0) == (t >= t0)
    if not (even or (blank_only(s0, s) and blank_only(t0, t))):
        raise ValueError("boundaries disagree")
    nl = [x.rstrip() for x in (e.get("new_text") or "").rstrip("\n").split("\n")]

    def restates(out, inside, line):
        o = R[out - 1].rstrip() if 1 <= out <= len(R) else ""
        return o.strip() != "" and o == line and R[inside - 1].rstrip() != o

    top = s >= 2 and restates(s - 1, s, nl[0])
    bot = t < len(R) and restates(t + 1, t, nl[-1])
    if not (top and bot and len(nl) == 1):
        s, t = s - top, t + bot
    shift = (s - s0) if (s - s0) == (t - t0) else 0
    return s, t, shift


def lines_of(content: str):
    return [x.rstrip("\r") for x in content.split("\n")][: (content.count("\n") + (0 if content.endswith("\n") else 1)) or 1]


def apply_ranges(content: str, placed):
    for s, t, new in sorted(placed, key=lambda x: -x[0]):
        starts = [0] + [i + 1 for i, ch in enumerate(content) if ch == "\n"]
        nn = len(starts) - 1 if content.endswith("\n") else len(starts)
        if s < 1 or t < s or t > max(nn, 1):
            raise ValueError("range outside file")
        a = starts[s - 1]
        b = starts[t] if t < len(starts) else len(content)
        rep = new or ""
        if content[a:b].endswith("\n") and rep and not rep.endswith("\n"):
            rep += "\n"
        content = content[:a] + rep + content[b:]
    return content


def expand(text, own, sources):
    out = []
    for piece in text.split("\n"):
        m = MARK.match(piece)
        if not m:
            out.append(piece)
            continue
        indent, named, a, b = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
        path = norm_path(named) if named else own
        if path is None or path not in sources:
            raise ValueError("ref to unknown file")
        R, sel = sources[path]
        hit = [(k, v) for k, v in sel.items() if k[0] <= a <= b <= k[1]]
        if not hit:
            raise ValueError("ref outside selection")
        (_, (ps, pe, sh)) = hit[0]
        block = R[a + sh - 1:b + sh]
        ws = [x[: len(x) - len(x.lstrip())] for x in block if x.strip()]
        base = min(ws, key=len) if ws else ""
        out.extend(indent + x[len(base):] if x.strip() else "" for x in block)
    return "\n".join(out)


def parse_patch(patch: str):
    """[(op, path, payload)]: ('update', path, [(old, new)]) or ('add', path, content)."""
    ops, cur = [], None
    for ln in patch.split("\n"):
        if ln.startswith("*** Update File:"):
            cur = ("update", norm_path(ln.split(":", 1)[1]), []); ops.append(cur); hunk = None; continue
        if ln.startswith("*** Add File:"):
            cur = ("add", norm_path(ln.split(":", 1)[1]), []); ops.append(cur); continue
        if ln.startswith("*** "):
            continue
        if cur is None:
            continue
        if cur[0] == "add":
            if ln.startswith("+"):
                cur[2].append(ln[1:])
            continue
        if ln.strip() == "@@" or ln.startswith("@@"):
            hunk = ["", ""]; cur[2].append(hunk); continue
        if not ln or hunk is None:
            continue
        tag, text = ln[0], ln[1:] + "\n"
        if tag in " -":
            hunk[0] += text
        if tag in " +":
            hunk[1] += text
    return ops


def replay_call(fs, repo, a, anchored_ok=True):
    """New contents {path: content} for one accepted call; fs maps path -> current content (None = absent)."""
    def cur(path):
        if path not in fs:
            f = repo / path
            fs[path] = f.read_text(errors="replace") if f.is_file() else None
        return fs[path]

    out = {}
    if isinstance(a.get("patch"), str):
        for op, path, payload in parse_patch(a["patch"]):
            if op == "add":
                out[path] = "\n".join(payload) + "\n"
                continue
            content = out.get(path, cur(path))
            if content is None:
                raise ValueError("update of missing file")
            pos = 0
            for old, new in payload:
                if not old:
                    continue
                hits = [m.start() for m in re.finditer(re.escape(old), content) if m.start() == 0 or content[m.start() - 1] == "\n"]
                after = [h for h in hits if h >= pos]
                if len(after) == 1 or len(hits) == 1:
                    h = after[0] if len(after) == 1 else hits[0]
                else:
                    raise ValueError("hunk ambiguous")
                content = content[:h] + new + content[h + len(old):]
                pos = h + len(new)
            out[path] = content
        return out
    files = a.get("files") if isinstance(a.get("files"), list) else ([a] if "path" in a else [])
    files = [f for f in files if isinstance(f, dict) and isinstance(f.get("path"), str)]
    sources, staged = {}, []
    for f in files:
        path = norm_path(f["path"])
        if isinstance(f.get("content"), str):
            staged.append((path, "content", f["content"]))
            continue
        es = [e for e in (f.get("edits") or []) if isinstance(e, dict)]
        content = cur(path)
        if content is None:
            raise ValueError("edit of missing file")
        if es and all(isinstance(e.get("old_text"), str) for e in es):
            for e in es:
                hits = [m.start() for m in re.finditer(re.escape(e["old_text"]), content)]
                if len(hits) != 1:
                    raise ValueError("old_text not unique")
                content = content[:hits[0]] + (e.get("new_text") or "") + content[hits[0] + len(e["old_text"]):]
            out[path] = content
            continue
        R = lines_of(content)
        placed, sel = [], {}
        for e in es:
            anchored = "first_line" in e or "last_line" in e
            if anchored:
                s, t, sh = place(R, e)
                sel[(e["start_line"], e["end_line"])] = (s, t, sh)
            else:
                s, t = e["start_line"], e["end_line"]
            placed.append([s, t, e.get("new_text") or "", anchored])
        if sel:
            sources[path] = (R, sel)
        staged.append((path, "lines", (content, placed)))
    for path, kind, payload in staged:
        if kind == "content":
            out[path] = expand(payload, None, sources) if sources and MARK.search(payload or "") is None and False else (
                expand(payload, None, sources) if sources and any(MARK.match(x) for x in payload.split("\n")) else payload)
        else:
            content, placed = payload
            rows = [(s, t, expand(new, path, sources) if anchored and sources else new) for s, t, new, anchored in placed]
            out[path] = apply_ranges(content, rows)
    return out


def run_record(directory: Path, repo: Path):
    fs, first, first_touched, before = {}, None, None, {}
    replay_error = None
    for line in (directory / "events.jsonl").read_text(errors="replace").splitlines():
        if '"experiment.tool_call"' not in line:
            continue
        p = json.loads(line)["payload"]
        if p["tool"] != "apply_patch":
            continue
        err = dec(p.get("error"))
        try:
            a = json.loads(dec(p.get("arguments")))
        except json.JSONDecodeError:
            a = {}
        files = a.get("files") if isinstance(a.get("files"), list) else []
        targeted = isinstance(a.get("patch"), str) or any(isinstance(f, dict) and f.get("edits") for f in files)
        is_first = first is None and targeted
        if err:
            if is_first:
                first = {"accepted": False, "broken": None}
            continue
        try:
            snapshot = {k: v for k, v in fs.items()}
            new = replay_call(fs, repo, a)
        except Exception as exc:  # noqa: BLE001 - recorded as a replay failure
            replay_error = replay_error or f"{type(exc).__name__}: {exc}"
            if is_first:
                first = {"accepted": True, "broken": None}
            continue
        if is_first:
            broken = False
            for path, text in new.items():
                if not path.endswith(".py"):
                    continue
                old = snapshot.get(path, fs.get(path))
                if (old is None or parses(old)) and not parses(text):
                    broken = True
            first = {"accepted": True, "broken": broken, "files": len(new)}
        fs.update(new)
    ws = directory / "workspace"

    def final(p):   # the logs ship only the files a run changed; every other file is the original repository
        f = ws / p if (ws / p).is_file() else repo / p
        return f.read_text(errors="replace") if f.is_file() else None

    mismatch = [p for p, text in fs.items() if text is not None and final(p) != text]
    return first, replay_error, mismatch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", nargs="?", default="runs/refactorbench-luna-4arms")
    parser.add_argument("--tasks", type=int)
    args = parser.parse_args()
    order = [l.strip() for l in open(Path(__file__).parent / "refactorbench_order.txt") if l.strip()]
    order = order[: args.tasks] if args.tasks else order
    stats = defaultdict(lambda: defaultdict(int))
    for d in sorted(Path(args.runs).iterdir()):
        if not d.is_dir() or not (d / "run.json").is_file():
            continue
        parts = d.name.split("__")
        task, arm = f"{parts[1]}__{parts[2]}", parts[4]
        if task not in order or arm not in ARMS:
            continue
        first, error, mismatch = run_record(d, rb.mapping()[task][0])
        st = stats[arm]
        st["runs"] += 1
        st["replay_exact"] += (error is None and not mismatch)
        if first is None:
            st["no_targeted_edit"] += 1
            continue
        st["first_targeted"] += 1
        if first["accepted"]:
            st["first_accepted"] += 1
            if first["broken"] is None:
                st["first_unreplayed"] += 1
            else:
                st["first_applied_replayed"] += 1
                st["first_broken"] += first["broken"]
                st["first_multi_file"] += first.get("files", 0) > 1
    for arm in ARMS:
        st = stats[arm]
        print(f"{arm:15s} runs {st['runs']}  replay reproduces final workspace in {st['replay_exact']}  "
              f"first targeted {st['first_targeted']}  accepted {st['first_accepted']}  "
              f"broken {st['first_broken']} of {st['first_applied_replayed']} replayed (unreplayed {st['first_unreplayed']}; "
              f"multi-file first edits {st['first_multi_file']})")


if __name__ == "__main__":
    main()

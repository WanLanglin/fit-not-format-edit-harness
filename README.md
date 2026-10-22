# Fit, Not Format at the Edit Interface: code and data

Code, run logs and analysis scripts for

> **Physics of Coding Agents: Part 1, Fit, Not Format at the Edit Interface**
> Langlin Wan, Zhixuan Liang, Guangyuan Wang, Shilong Liu.
> Preprints, 2026. [doi:10.20944/preprints202610.1889.v1](https://doi.org/10.20944/preprints202610.1889.v1) · [PDF in this repository](paper/fit-not-format.pdf)

To edit a file, a coding agent has to say where the change goes: by pointing at line numbers, or by quoting the
code it wants to change, as search/replace and patch formats require. We run one harness in which only the edit
interface varies, across six models and three benchmarks, and measure what each interface costs and which errors
it lets through. We then introduce **verified selection**: the model points with a line range and quotes only the
first and last line, and the harness checks both boundaries, absorbs small offsets and copies lines the model
references instead of retyping. The harness is [S-Code](https://github.com/sai-foundation/s-code).

## Contents

| Path | What it is |
|---|---|
| `paper/` | The paper, and the scripts that compute every table, figure and number in it |
| `editbench/` | The agent runner, benchmark adapters and graders, the recording OpenRouter proxy, and model configurations |
| `harness/` | The S-Code changes behind every run, one patch per build ([harness/README.md](harness/README.md)) |
| `logs/` | Run logs: 31 archives, one per batch, 5,642 runs |
| `reproduce.sh` | Regenerates the tables, numbers and figures from the logs |

## Reproduce the paper's numbers

```bash
pip install -r requirements.txt   # Python 3.11
./reproduce.sh
```

`reproduce.sh` unpacks the logs into `editbench/runs/`, downloads the CanItEdit test split and RefactorBench at the
pinned commits, and runs every script in order. Printed tables and numbers go to `paper/out/<script>.txt`, derived
tables to `paper/data/`, and figures to `paper/figures/out/`. The same files are shipped precomputed, so everything
can be read without running anything. Set `SKIP_REFACTORBENCH=1` to skip the RefactorBench download (about 300 MB).

`ref_patch_compat.py` replays rejected patches through the reference `apply_patch` and runs only when `CODEX_BIN`
points to the native codex-cli 0.156.0 binary (the platform executable, not the npm launcher); otherwise the shipped
`paper/data/ref_patch_compat.*` are kept.

The tables and numbers do not depend on the plotting library. The figures in the paper were drawn with matplotlib
3.10.8; with the pinned 3.11.2 their content is identical and the layout differs by a few pixels.

## Where each result comes from

Scripts run from `paper/`, except the RefactorBench ones, which run from `editbench/`.

| Paper | Script | Output |
|---|---|---|
| Run counts, invalid runs (Section 3) | `build_dataset.py` | `data/manifest.json`, `out/build_dataset.txt` |
| Table 1 | `main_table.py` | `out/main_table.txt` |
| Figure 3 | `figures/paper_figures.py` | `figures/out/fig_levels.pdf` |
| Figure 4, efficiency ratios (Result 1) | `efficiency.py`, `cost_ratios.py`, `figures/paper_figures.py` | `data/efficiency.csv`, `data/failed_first_edit.csv`, `figures/out/fig_cost.pdf` |
| First-call output tokens; edits after the first success (Results 1, 2) | `later_edits.py` | `out/later_edits.txt` |
| Quotation length (Result 2, Figure 5) | `copy_law.py`, `figures/paper_figures.py` | `data/edits_text.csv`, `figures/out/fig_quote_length.pdf` |
| Replayed first edits, region size (Result 2, Figure 6) | `region_law.py`, `region_numbers.py`, `figures/paper_figures.py` | `data/first_calls.csv`, `out/region_numbers.txt` |
| Broken line-range edits by cause (Result 2) | `invalid_breakdown.py` | `out/invalid_breakdown.txt` |
| Cost breakdown (Result 1, Appendix C) | `cost_components.py`, `cache_neutral.py`, `read_write_split.py` | `out/cost_components.txt`, `out/cache_neutral.txt` |
| Model × interface interaction (Result 3) | `coupling_test.py` (`ARMS=text,lines` for the two-interface test) | `out/coupling_test.txt`, `out/coupling_test_text_lines.txt` |
| Rankings, habit and fluency (Result 3) | `support_numbers.py`, `claude_numbers.py` | `out/support_numbers.txt`, `out/claude_numbers.txt` |
| Menu conditions, packaging, advice, position (Result 3, Figure 7) | `menu_numbers.py`, `cost_numbers.py`, `figures/paper_figures.py` | `out/menu_numbers.txt`, `out/cost_numbers.txt`, `figures/out/fig_coupling.pdf` |
| Table 2, ablation (Result 4) | `method_table.py` | `out/method_table.txt` |
| Figure 8 | `figures/paper_figures.py` | `figures/out/fig_method.pdf` |
| Table 3, second runs | `replication_table.py`, `replicate_task_tests.py` | `out/replication_table.txt`, `out/replicate_task_tests.txt` |
| Line numbers that contradict their quotes (Result 4) | `misaddress.py` | `data/misaddress.txt` |
| Small edits, Claude Sonnet 5 (Result 4) | `ref_ablation.py`, `cache_neutral.py` | `out/ref_ablation.txt`, `out/cache_neutral.txt` |
| Table 4, RefactorBench | `editbench/rb_analysis.py`, `editbench/rb_replay.py` | `out/rb_analysis.txt`, `out/rb_replay.txt` |
| Table 5, model settings | none: recorded per run | `run.json` (`turn_profile`), `model_calls.jsonl` (`provider`, `dropped_parameters`) |
| Rejected patches by type (Figure 9) | `ref_patch_compat.py`, `figures/paper_figures.py` | `data/ref_patch_compat.txt`, `figures/out/fig_patch_failures.pdf` |

Figures 1 and 2 are drawings and use no data. Replays re-apply recorded edit calls to the original task files with
the harness's placement rules and check the result against the run's final workspace; the scripts print how many
replays match. For RefactorBench, `rb_replay.py` rebuilds every run's final repository from the logs instead, so
those logs carry only the files each run changed (under `workspace/`), not the whole repository.

GPT-5.6-luna's one-tool menu, with and without advice, ran twice on CanItEdit: on 2026-09-15 (`canitedit-luna-4arms`,
`canitedit-luna-guided`) and on 2026-09-17 with the three-tool arms (`canitedit-luna-tools-ablation`). `data/runs.csv`
keeps both (`batch` = `main` and `ablation`). Result 3's comparisons between menu conditions, and the menu points in
Figure 7a, use the 2026-09-17 runs, in which all four menu conditions ran side by side. The search/replace references
in Figure 7 and the per-output-token ratios in Figure 7b take the first run of each arm in `data/runs.csv`: the
2026-09-15 runs for search/replace and the one-tool menus, the 2026-09-17 runs for the three-tool menus.

## Task sets

- CanItEdit: the test split's 105 problems, less the 22 that need third-party libraries and
  `53_minimax_to_alphabeta`, whose unedited program already passes its hidden tests, leaves 82 tasks
  (`editbench/adapters/canitedit.py`). The dataset stores programs without a final newline; every task file gets one
  before the run, in every arm, because the patch form cannot match a last line without it. The grader strips
  trailing newlines before appending the tests, so grading is unaffected.
- Aider refactors: the benchmark's 89 tasks (`editbench/vendor/refactor-benchmark`).
- RefactorBench: 84 tasks (`editbench/refactorbench_order.txt`) on the repositories at the pinned commit.

## Run logs

Each run directory in a log archive is named `<benchmark>__<task>__<model>__<arm>__r0` and holds:

| File | Content |
|---|---|
| `run.json` | Model, arm, harness build, limits, outcome, token usage, every tool call (name, outcome, error, argument hash), grade, and `invalid_reasons` |
| `events.jsonl` | The harness event stream: every tool call with its arguments and outcome (the error text when rejected), and the model's streamed output |
| `model_calls.jsonl` | One line per model call: provider routing, HTTP status, prompt, cached, output and reasoning tokens, billed cost |
| `grade.json` | Grader result: hidden tests for CanItEdit, the syntax-tree check for the Aider refactors, the task's AST tests for RefactorBench |
| `prompt.txt` | The task prompt |
| `workspace/` | The task files as the run left them (for RefactorBench, only the files the run changed) |

Arm names: `text` = search/replace, `patch` = patch, `lines` = line range; `choice` = one tool with the three forms
as argument shapes, `guided` = the same with advice on when to use each, `tools` = three named tools,
`tools_guided` = the same with advice; `lines_anchored` = verified selection. Its ablations are separate batches:
`*-anchored` = P1 (boundary check), `*-aligned` = P1+P2 (alignment), `*-ref` = P1-P3 (references). Batches ending
in `-rep1` are second runs: of the refactors in Table 3, and of GPT-5.6-luna on CanItEdit for Result 4's small edits. A run is invalid when the provider or the harness fails rather than the
model (`run.json`: `invalid_reasons`); every paired comparison uses the tasks with a valid run in every arm compared.
[logs/README.md](logs/README.md) gives the run counts behind the paper's totals and describes the invalid runs.
Every run has the harness's turn limits, recorded in `run.json` (`turn_profile.turn_limits`): 48 model calls, 64 tool
calls, 1,000,000 tokens, $5 and 1,800 s per run, and 60 s for a silent model stream; RefactorBench raises the first
three to 96, 256 and 20,000,000. A run that reaches a limit is graded as it stands. The temperature is recorded per
run (`turn_profile.temperature`): 1.0 for GLM-5.3, DeepSeek-V4-Flash and Qwen3.8-Flash, and the harness default 0.0
for the other models. `binary` names the build that served a run; `binary_sha256` hashes its launcher script, which
is the same for every build.
`run.json` also records the SHA-256 of the task prompt, the tool schemas and the edit instructions (`prompt_sha256`,
`turn_profile.tools_sha256`, `turn_profile.editing_prompt_sha256`), so a rebuilt harness can be checked against the
logs. Local file-system paths in the logs are shortened, and four batch and build directories carry the names used in
this repository (for example `refactorbench-luna-4arms` and `bin/6a13cf6-refactorbench`). The turn profiles also
carried two always-false fields for harness switches that no run used and the released patches no longer have;
they are removed. Nothing else is changed.

| Batch | Model | Arms | Used for |
|---|---|---|---|
| `canitedit-{luna,glm,deepseek,mimo,qwen}-*`, `canitedit-luna-tools-ablation` | five models | three interfaces and the menu arms | Table 1, Results 1-3 |
| `canitedit-claude-sonnet5-2arms` | Claude Sonnet 5 | `text`, `lines` | Table 1, Result 3 |
| `refactor-luna-5arms`, `refactor-mimo-3arms` | GPT-5.6-luna, MiMo-v2.5-Pro | three interfaces (and the luna menu arms) | Table 1, Results 1, 2 (the menu arms only in Result 2's replays of first edits) |
| `refactor-{luna,mimo}-{anchored,aligned,ref}` | GPT-5.6-luna, MiMo-v2.5-Pro | `lines_anchored` | Table 2, Result 4 |
| `canitedit-{luna,mimo}-{aligned,ref}`, `canitedit-claude-sonnet5-ref` | GPT-5.6-luna, MiMo-v2.5-Pro, Claude Sonnet 5 | `lines_anchored` | Result 4 (small edits, Claude) |
| `*-rep1` | GPT-5.6-luna, MiMo-v2.5-Pro | headline arms | Table 3; Result 4 (small edits) |
| `refactorbench-luna-4arms` | GPT-5.6-luna | `text`, `patch`, `lines`, `lines_anchored` | Table 4 |

## Run the experiments again

1. Build the harness for the batch you want to repeat: [harness/README.md](harness/README.md).
2. Put an OpenRouter key in `EDITBENCH_OPENROUTER_API_KEY` (or in `~/.config/editbench/openrouter.env`). Only the
   recording proxy sees it; the runner and the harness do not.
3. From `editbench/`, run a batch behind the proxy. `PROXY_CONFIG` selects the model's provider pinning and the
   sampling parameters the proxy sets (Table 5); the arguments after `--` go to `pilot.py`, which also takes the
   temperature (`--temperature 1.0` for GLM-5.3, DeepSeek-V4-Flash and Qwen3.8-Flash):

```bash
# CanItEdit, GPT-5.6-luna, the three interfaces and the one-tool menu (batch canitedit-luna-4arms)
PROXY_CONFIG=configs/openrouter-luna.json S_CODE_BIN=bin/79878f3/s-code \
  ./run_with_proxy.sh runs/canitedit-luna-4arms 20 -- \
  --benchmarks canitedit --models openai/gpt-5.6-luna --arms text patch lines choice --per-benchmark 1000

# Verified selection on the Aider refactors (batch refactor-luna-ref)
PROXY_CONFIG=configs/openrouter-luna.json S_CODE_BIN=bin/6a13cf6/s-code \
  ./run_with_proxy.sh runs/refactor-luna-ref 20 -- \
  --benchmarks aider-refactor --models openai/gpt-5.6-luna --arms lines_anchored --per-benchmark 1000

# RefactorBench, four interfaces (batch refactorbench-luna-4arms; fetch the benchmark first)
bash vendor/fetch_refactorbench.sh
PROXY_CONFIG=configs/openrouter-luna.json S_CODE_BIN=bin/6a13cf6-refactorbench/s-code \
  ./run_with_proxy.sh runs/refactorbench-luna-4arms 20 -- \
  --benchmarks refactorbench --models openai/gpt-5.6-luna --arms text lines patch lines_anchored \
  --tasks $(cat refactorbench_order.txt) --cross-file-ref --max-tool-calls 256 --max-model-calls 96 \
  --max-total-tokens 20000000 --detailed-tool-results 1000
```

The second argument is the spending cap in US dollars, enforced by the proxy. GLM-5.3 and MiMo-v2.5-Pro use
`configs/openrouter-pilot.json`. `pilot.py` writes a batch's arguments to `plan.json` in its output directory; for the shipped runs, each `run.json`
records the arm, build, limits and model settings it ran with.

## Citation

```bibtex
@article{wan2026fitnotformat,
  title   = {Physics of Coding Agents: Part 1, Fit, Not Format at the Edit Interface},
  author  = {Wan, Langlin and Liang, Zhixuan and Wang, Guangyuan and Liu, Shilong},
  journal = {Preprints},
  year    = {2026},
  doi     = {10.20944/preprints202610.1889.v1},
  url     = {https://www.preprints.org/manuscript/202610.1889}
}
```

## Licenses

Our code is released under the Apache License 2.0 (`LICENSE`) and the run logs under CC BY 4.0 (`logs/LICENSE.md`),
except the task material they contain, which keeps its own license as described here. The patches in
`harness/` modify S-Code, which is Apache-2.0. Aider's `refactor_tools.py` (`editbench/vendor/aider-benchmark`, commit in
`COMMIT`) and the Aider refactoring benchmark (`editbench/vendor/refactor-benchmark`) are Apache-2.0; the benchmark's
task files are taken from open-source projects and keep their original licenses (eight Ansible files are GPL-3.0; the
license text is in `editbench/vendor/refactor-benchmark/GPL-3.0.txt`). CanItEdit is
downloaded from huggingface.co/datasets/nuprl/CanItEdit at the revision in `COMMIT` (marked MIT there); its GitHub
repository is under the BSD 3-Clause License with a machine-learning restriction (`editbench/vendor/canitedit/LICENSE`).
Its task prompts and files appear in the CanItEdit run logs; they keep that license and may not be used as training
data for any machine learning model. RefactorBench is downloaded from github.com/microsoft/RefactorBench at the commit
in `editbench/vendor/RefactorBench.COMMIT`, under its own license. Other task files in run workspaces keep their
original licenses.

#!/usr/bin/env bash
# Regenerate every table, number and figure of the paper from the run logs.
# Printed tables and numbers go to paper/out/<script>.txt, derived tables to paper/data/, figures to paper/figures/out/.
set -euo pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
mkdir -p editbench/runs
for f in logs/*.tar.gz; do d="editbench/runs/$(basename "$f" .tar.gz)"; [ -d "$d" ] || tar -xzf "$f" -C editbench/runs; done
[ -f editbench/vendor/canitedit/test.parquet ] || bash editbench/vendor/canitedit/fetch.sh
cd paper
mkdir -p data out figures/out
run() { echo "== $1"; "$PY" "$1.py" > "out/$1.txt"; }
# derived tables
run build_dataset; run place_check; run copy_law; run region_law
# Result 1 (Table 1, Figures 3-4)
run main_table; run efficiency; run cost_ratios; run later_edits
# Result 2 (Figures 5-6) and the cost breakdown
run region_numbers; run invalid_breakdown; run cost_components; run cache_neutral; run read_write_split
# Result 3 (Figure 7)
run coupling_test; echo "== coupling_test (search/replace and line range)"; ARMS=text,lines "$PY" coupling_test.py > out/coupling_test_text_lines.txt
run support_numbers; run menu_numbers; run cost_numbers; run claude_numbers
if [ -n "${CODEX_BIN:-}" ]; then run ref_patch_compat
else echo "== ref_patch_compat skipped (set CODEX_BIN to the native codex-cli 0.156.0 binary); keeping data/ref_patch_compat.*"; fi
# Result 4 (Tables 2-3, Figure 8)
run misaddress; run method_table; run replication_table; run replicate_task_tests; run ref_ablation
# RefactorBench (Table 4)
if [ -z "${SKIP_REFACTORBENCH:-}" ]; then
  bash ../editbench/vendor/fetch_refactorbench.sh
  echo "== rb_analysis"; (cd ../editbench && "$PY" rb_analysis.py) > out/rb_analysis.txt
  echo "== rb_replay"; (cd ../editbench && "$PY" rb_replay.py) > out/rb_replay.txt
fi
# Figures 3-9
echo "== paper_figures"; "$PY" figures/paper_figures.py > out/paper_figures.txt
echo "done: tables and numbers in paper/out/ and paper/data/, figures in paper/figures/out/"

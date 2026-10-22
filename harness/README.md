# The harness builds behind the runs

Every run was served by [S-Code](https://github.com/sai-foundation/s-code) with experiment changes on top of upstream
commit `10d2ba3` (full hash in `BASE_COMMIT`). The changes add the edit interfaces of every arm (search/replace,
patch, line range, the menu conditions and verified selection), the experiment limits the runner sets, and the event
records the analysis reads. Each build the paper used is one patch in `builds/`, a complete diff against
`BASE_COMMIT`; `run.json` records which build served a run (`binary`) and the SHA-256 of what the model saw.

Experiment code that no run used was removed from the patches. With them gone, each build gives the model the
same tool schemas and edit instructions as in its runs: the SHA-256 values in the turn profile
(`tools_sha256`, `editing_prompt_sha256`, `apply_patch_sha256`) match the logs for every build and arm.

| Build | Batches |
|---|---|
| `79878f3` | Main study on CanItEdit: search/replace, patch, line range and the one-tool menu (GPT-5.6-luna, GLM-5.3, DeepSeek-V4-Flash); Claude Sonnet 5 search/replace and line range; GPT-5.6-luna second runs |
| `4ea26bf` | The menu with advice (`guided`) on CanItEdit |
| `ff1657e` | Three named tools (`tools`, `tools_guided`) for the GPT-5.6-luna ablation; every arm of MiMo-v2.5-Pro and the first Qwen3.8-Flash runs on CanItEdit |
| `db2c7bd` | The remaining Qwen3.8-Flash runs. Only change from `ff1657e`: in the three-named-tool arms, error messages name the tool the model called instead of `apply_patch`; the single-tool arms behave identically |
| `6ae7f9f` | Aider refactors: the interfaces and menu arms, and their second runs |
| `8bae6e1` | Verified selection P1, the boundary check (`*-anchored`) |
| `9a01fe5` | Verified selection P1+P2, alignment (`*-aligned`) |
| `6a13cf6` | Verified selection P1-P3, with `@@ref` references (`*-ref`, `*-ref-rep1`), on every benchmark |
| `6a13cf6` + `6a13cf6-refactorbench.patch` | RefactorBench (`refactorbench-luna-4arms`): `@@ref path:A-B@@` across the files of one call, and switches that let the runner raise the tool-call, model-call and token limits and keep every tool result in full |

## Build one

S-Code pins Rust 1.89.0 in `rust-toolchain.toml`.

```bash
git clone https://github.com/sai-foundation/s-code s-code-exp && cd s-code-exp
git checkout "$(cat ../harness/BASE_COMMIT)"
git apply ../harness/builds/6a13cf6.patch                     # the build you need
# git apply ../harness/builds/6a13cf6-refactorbench.patch     # RefactorBench only, on top of 6a13cf6
cargo build --locked --release -p s-code-cli -p s-code-daemon
mkdir -p ../editbench/bin/6a13cf6
cp target/release/s-code-cli target/release/s-code-daemon scripts/s-code ../editbench/bin/6a13cf6/
```

The runner expects the launcher `s-code` next to the two binaries, in `editbench/bin/<build>/`, and takes that path
through `S_CODE_BIN` (see the top-level README). It also loads the run helper `tests/benchmarks/harness/run.py`, which
the patches add, from the patched checkout: by default `s-code-exp/` next to `editbench/`, as cloned above, or the
directory named by `EDITBENCH_S_CODE_SOURCE`.

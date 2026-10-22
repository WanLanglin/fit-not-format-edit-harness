#!/usr/bin/env bash
# Fetch microsoft/RefactorBench at the commit the runs used (repositories and AST tests; see its LICENSE).
set -euo pipefail
cd "$(dirname "$0")"
[ -d RefactorBench/.git ] || git clone https://github.com/microsoft/RefactorBench RefactorBench
git -C RefactorBench checkout --quiet "$(cat RefactorBench.COMMIT)"
echo "RefactorBench at $(git -C RefactorBench rev-parse --short HEAD)"

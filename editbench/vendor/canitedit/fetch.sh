#!/usr/bin/env bash
# Download the CanItEdit test split (MIT license, huggingface.co/datasets/nuprl/CanItEdit) at the revision we used.
set -euo pipefail
cd "$(dirname "$0")"
rev=$(cat COMMIT)
curl -sSL -o test.parquet "https://huggingface.co/datasets/nuprl/CanItEdit/resolve/${rev}/data/test-00000-of-00001.parquet"
echo "9f78b1a2378b96b24d158a6fe83d69aa18e43a360ae3b7d0891c02f660cc6222  test.parquet" | sha256sum -c -

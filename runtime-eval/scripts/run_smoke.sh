#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

CONDA_BIN="${CONDA_BIN:-$HOME/miniconda3/bin/conda}"

"$CONDA_BIN" run -n runtimeeval \
  python -m runner.main \
  --regime configs/regimes/A00.yaml \
  --tournament configs/tournaments/smoke.yaml

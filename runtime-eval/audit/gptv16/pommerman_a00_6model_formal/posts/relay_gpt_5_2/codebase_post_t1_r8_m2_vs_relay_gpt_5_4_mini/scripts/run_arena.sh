#!/usr/bin/env bash
set -euo pipefail

OUT_JSON="${1:?usage: run_arena.sh <out_json> <left_submission_main> <right_submission_main>}"
LEFT_SUBMISSION_MAIN="${2:?missing left submission main.py}"
RIGHT_SUBMISSION_MAIN="${3:?missing right submission main.py}"

OUT_JSON="$(python -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$OUT_JSON")"
LEFT_SUBMISSION_MAIN="$(python -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$LEFT_SUBMISSION_MAIN")"
RIGHT_SUBMISSION_MAIN="$(python -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$RIGHT_SUBMISSION_MAIN")"

CONDA_BIN="${CONDA_BIN:-$HOME/miniconda3/bin/conda}"

"$CONDA_BIN" run -n pommerman \
  python scripts/pommerman_ffa_probe.py \
  --out "$OUT_JSON" \
  --left-submission "$LEFT_SUBMISSION_MAIN" \
  --right-submission "$RIGHT_SUBMISSION_MAIN"

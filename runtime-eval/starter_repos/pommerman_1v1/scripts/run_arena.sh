#!/usr/bin/env bash
set -euo pipefail

OUT_JSON="${1:?usage: run_arena.sh <out_json> <left_submission_main> <right_submission_main>}"
LEFT_SUBMISSION_MAIN="${2:?missing left submission main.py}"
RIGHT_SUBMISSION_MAIN="${3:?missing right submission main.py}"
COMPACT_OUT="${4:-}"
REQUESTED_SEED="${5:-}"
RECORD_JSON_DIR=""

if [[ "${6:-}" == "--record-json-dir" ]]; then
  RECORD_JSON_DIR="${7:-}"
elif [[ -n "${6:-}" ]]; then
  RECORD_JSON_DIR="${6:-}"
fi

OUT_JSON="$(python -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$OUT_JSON")"
LEFT_SUBMISSION_MAIN="$(python -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$LEFT_SUBMISSION_MAIN")"
RIGHT_SUBMISSION_MAIN="$(python -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$RIGHT_SUBMISSION_MAIN")"
if [[ -n "$COMPACT_OUT" ]]; then
  COMPACT_OUT="$(python -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$COMPACT_OUT")"
fi
if [[ -n "$RECORD_JSON_DIR" ]]; then
  RECORD_JSON_DIR="$(python -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$RECORD_JSON_DIR")"
fi

CONDA_BIN="${CONDA_BIN:-$HOME/miniconda3/bin/conda}"

CMD=(
  "$CONDA_BIN" run -n pommerman
  python scripts/pommerman_ffa_probe.py
  --out "$OUT_JSON"
  --left-submission "$LEFT_SUBMISSION_MAIN"
  --right-submission "$RIGHT_SUBMISSION_MAIN"
)
if [[ -n "$COMPACT_OUT" ]]; then
  CMD+=(--compact-out "$COMPACT_OUT")
fi
if [[ -n "$REQUESTED_SEED" ]]; then
  CMD+=(--requested-seed "$REQUESTED_SEED")
fi
if [[ -n "$RECORD_JSON_DIR" ]]; then
  CMD+=(--record-json-dir "$RECORD_JSON_DIR")
fi
"${CMD[@]}"

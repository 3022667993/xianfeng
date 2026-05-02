#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

pytest -q
bash scripts/run_smoke.sh
python scripts/build_pommerman_pairing_manifest.py
bash scripts/audit_pommerman_a00_current.sh
python scripts/audit_pommerman_pairing_manifest.py

#!/usr/bin/env bash
set -euo pipefail

echo "=== Pommerman+A00 Current Artifact Audit ==="

test -f logs/round_1/metadata.json
test -f logs/round_1/scorecard.json
test -f logs/round_1/feedback_package.json
test -f logs/round_1/arena_result_match_a.json
test -f logs/round_1/arena_result_match_b.json
test -f logs/round_2/metadata.json
test -f logs/round_2/scorecard.json
test -f logs/round_2/feedback_package.json
test -f logs/round_2/arena_result_match_a.json
test -f logs/round_2/arena_result_match_b.json

python - <<'PY'
import yaml
from pathlib import Path

cfg = yaml.safe_load(Path("configs/regimes/A00.yaml").read_text(encoding="utf-8"))
runtime_controls = cfg.get("runtime_controls", {}) if isinstance(cfg, dict) else {}
required = {
    "conversational_carryover": False,
    "file_memory": False,
    "visibility": "summary-only",
    "skills_enabled": False,
    "memory_plugin_enabled": False,
    "session_memory_hook": False,
    "pre_compaction_memory_flush": False,
    "startup_memory_prelude": False,
    "fixed_bootstrap": True,
    "fixed_tool_surface": True,
}
for key, expected in required.items():
    value = cfg.get(key)
    if value is None and isinstance(runtime_controls, dict):
        value = runtime_controls.get(key)
    if value != expected:
        raise SystemExit(f"A00 mismatch: {key}={value!r}, expected {expected!r}")
print("PASS A00 config is memory-minimal")
PY

echo "=== AUDIT PASS ==="

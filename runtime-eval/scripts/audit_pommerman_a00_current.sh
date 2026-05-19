#!/usr/bin/env bash
set -euo pipefail

echo "=== Pommerman+A00 Current Artifact Audit ==="

python - <<'PY'
import json
from pathlib import Path

for round_idx in [1, 2]:
    round_dir = Path("logs") / f"round_{round_idx}"
    manifest_path = round_dir / "round_manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"missing {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schedule_mode") != "double_round_robin":
        raise SystemExit(f"{manifest_path}: schedule_mode must be double_round_robin")
    if manifest.get("match_legs") != "single":
        raise SystemExit(f"{manifest_path}: match_legs must be single")
    matches = manifest.get("matches", [])
    if not isinstance(matches, list) or not matches:
        raise SystemExit(f"{manifest_path}: expected non-empty matches list")
    for rec in matches:
        match_idx = rec.get("match_idx")
        if not isinstance(match_idx, int):
            raise SystemExit(f"{manifest_path}: match record missing integer match_idx")
        match_dir = round_dir / f"match_{match_idx}"
        for name in [
            "metadata.json",
            "scorecard.json",
            "arena_result_match_a.json",
            "trajectory_compact_match_a.jsonl",
        ]:
            path = match_dir / name
            if not path.exists():
                raise SystemExit(f"missing {path}")
        for stale in [
            "arena_result_match_b.json",
            "trajectory_compact_match_b.jsonl",
        ]:
            path = match_dir / stale
            if path.exists():
                raise SystemExit(f"{path} must not exist in current single-leg double_rr runs")
print("PASS current single-leg double_rr match artifacts")
PY

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

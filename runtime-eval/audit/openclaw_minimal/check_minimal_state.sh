#!/usr/bin/env bash
set -euo pipefail

WORKSPACE="/root/autodl-tmp/runtime-eval/openclaw_workspaces/minimal"
CONFIG="/root/.openclaw/openclaw.json"

echo "===== workspace files ====="
find "$WORKSPACE" -maxdepth 2 -type f | sort

echo
echo "===== forbidden files check ====="
for f in SOUL.md HEARTBEAT.md BOOTSTRAP.md BOOT.md MEMORY.md; do
  if [ -e "$WORKSPACE/$f" ]; then
    echo "FORBIDDEN_PRESENT: $f"
    exit 1
  fi
done
if [ -e "$WORKSPACE/.openclaw" ]; then
  echo "FORBIDDEN_PRESENT: .openclaw"
  exit 1
fi
echo "forbidden files absent"

echo
echo "===== config summary ====="
python - <<'PY'
import json
from pathlib import Path

cfg = json.loads(Path("/root/.openclaw/openclaw.json").read_text())
agents = cfg.get("agents", {}).get("defaults", {})

safe = {
    "workspace": agents.get("workspace"),
    "skipBootstrap": agents.get("skipBootstrap"),
    "contextInjection": agents.get("contextInjection"),
    "heartbeat.every": agents.get("heartbeat", {}).get("every"),
    "heartbeat.includeSystemPromptSection": agents.get("heartbeat", {}).get("includeSystemPromptSection"),
    "skills": agents.get("skills"),
    "skills.allowBundled": cfg.get("skills", {}).get("allowBundled"),
    "memory.slot": cfg.get("plugins", {}).get("slots", {}).get("memory"),
    "memoryFlush.enabled": agents.get("compaction", {}).get("memoryFlush", {}).get("enabled"),
    "browser.enabled": cfg.get("browser", {}).get("enabled"),
}
for k, v in safe.items():
    print(f"{k} = {v}")
PY

echo
echo "OPENCLAW_MINIMAL_AUDIT_OK"

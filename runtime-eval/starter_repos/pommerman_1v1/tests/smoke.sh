#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

CONDA_BIN="${CONDA_BIN:-$HOME/miniconda3/bin/conda}"

bash scripts/build.sh

"$CONDA_BIN" run -n pommerman python - <<'PY'
import importlib.util
from pathlib import Path

submission_main = Path("submission/main.py").resolve()
spec = importlib.util.spec_from_file_location("submission_main", submission_main)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

make_agent = getattr(module, "make_agent", None)
if not callable(make_agent):
    raise AttributeError("submission/main.py must expose callable make_agent()")

agent = make_agent()
if agent is None:
    raise TypeError("make_agent() must return an agent object")

from pommerman import agents
if not isinstance(agent, agents.BaseAgent):
    raise TypeError("make_agent() must return a pommerman.agents.BaseAgent instance")

action = agent.act({}, None)
if not isinstance(action, int) or not 0 <= action <= 5:
    raise TypeError("agent.act(...) must return an integer action in [0, 5]")
PY

echo "[smoke] starter repo contract OK"

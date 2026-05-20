#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

CONDA_BIN="${CONDA_BIN:-$HOME/miniconda3/bin/conda}"

bash scripts/build.sh

VALIDATION_SCRIPT="$(mktemp)"
trap 'rm -f "$VALIDATION_SCRIPT"' EXIT
cat > "$VALIDATION_SCRIPT" <<'PY'
import importlib.util
import numbers
from pathlib import Path

import pommerman
from pommerman import agents

submission_main = Path("submission/main.py").resolve()
spec = importlib.util.spec_from_file_location("submission_main", submission_main)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

make_agent = getattr(module, "make_agent", None)
if not callable(make_agent):
    raise AttributeError("submission/main.py must expose callable make_agent()")


def require_valid_agent(agent):
    if agent is None:
        raise TypeError("make_agent() must return an agent object")
    if not isinstance(agent, agents.BaseAgent):
        raise TypeError("make_agent() must return a pommerman.agents.BaseAgent instance")


def require_valid_action(action, context):
    if not isinstance(action, numbers.Integral) or not 0 <= int(action) <= 5:
        raise TypeError(f"agent.act(...) must return an integer action in [0, 5] for {context}; got {action!r}")


agent = make_agent()
require_valid_agent(agent)
require_valid_action(agent.act({}, None), "empty observation fallback")

for submitted_seat in (0, 1):
    submitted_agent = make_agent()
    require_valid_agent(submitted_agent)
    agent_list = [agents.RandomAgent(), agents.RandomAgent(), agents.RandomAgent(), agents.RandomAgent()]
    agent_list[submitted_seat] = submitted_agent
    env = pommerman.make("PommeFFACompetition-v0", agent_list)
    try:
        observations = env.reset()
        obs_index = getattr(submitted_agent, "agent_id", submitted_seat)
        if not isinstance(obs_index, numbers.Integral) or not 0 <= int(obs_index) < len(observations):
            obs_index = submitted_seat
        obs = observations[int(obs_index)]
        try:
            action = submitted_agent.act(obs, env.action_space)
        except Exception as exc:
            raise RuntimeError(
                "submission contract validation failed on real Pommerman observation: "
                f"seat={submitted_seat} agent_id={obs_index} exception={type(exc).__name__}: {exc}"
            ) from exc
        require_valid_action(action, f"real Pommerman observation seat={submitted_seat}")
    finally:
        env.close()
PY

"$CONDA_BIN" run -n pommerman python "$VALIDATION_SCRIPT"

echo "[smoke] starter repo contract OK"

from __future__ import annotations

from typing import Any

from pommerman import agents


class Agent(agents.BaseAgent):
    def act(self, obs: dict[str, Any], action_space: Any = None) -> int:
        return 0


def make_agent() -> Agent:
    return Agent()

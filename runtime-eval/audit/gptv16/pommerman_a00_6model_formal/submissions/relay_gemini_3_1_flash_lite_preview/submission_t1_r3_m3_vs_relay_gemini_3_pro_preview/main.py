from __future__ import annotations

from pommerman import agents

AGGRESSION = 1


def make_agent():
    if AGGRESSION == 0:
        return agents.SimpleAgent()
    return agents.RandomAgent()


if __name__ == "__main__":
    agent = make_agent()
    print(type(agent).__name__)

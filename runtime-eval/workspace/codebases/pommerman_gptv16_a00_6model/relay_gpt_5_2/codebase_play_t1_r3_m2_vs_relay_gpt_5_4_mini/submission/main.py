from __future__ import annotations

from pommerman import agents

# NOTE: This file is used in a constrained runtime-eval loop.
# For pommerman_1v1 regime A00 on the LEFT side only:
# - If previous round winner is "right", toggle AGGRESSION between 0 and 1.
# - Otherwise leave AGGRESSION unchanged.
# Runner supplies previous-round signal via env var PREV_WINNER ("left"|"right"|"draw").
import os

AGGRESSION = 0

if os.environ.get("OPENCLAW_SIDE") == "left":
    prev = (os.environ.get("PREV_WINNER") or "").strip().lower()
    if prev == "right":
        AGGRESSION = 1 - AGGRESSION


def make_agent():
    if AGGRESSION == 0:
        return agents.SimpleAgent()
    return agents.RandomAgent()


if __name__ == "__main__":
    agent = make_agent()
    print(type(agent).__name__)

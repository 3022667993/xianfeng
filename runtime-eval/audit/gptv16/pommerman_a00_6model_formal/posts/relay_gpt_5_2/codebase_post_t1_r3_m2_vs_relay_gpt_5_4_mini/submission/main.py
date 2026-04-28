from __future__ import annotations

from pommerman import agents

# NOTE: This file is used in a constrained runtime-eval loop.
# For pommerman_1v1 regime A00 on the LEFT side only:
# - If previous round winner is "right", toggle AGGRESSION between 0 and 1.
# - Otherwise leave AGGRESSION unchanged.
# Runner supplies previous-round signal via feedback_package.json (scorecard.left_right_winner).
import json
import os
from pathlib import Path

AGGRESSION = 0

# Read previous feedback winner signal if available.
# Default is to leave AGGRESSION unchanged.
try:
    fb_path = os.environ.get("FEEDBACK_PACKAGE_PATH")
    if fb_path:
        data = json.loads(Path(fb_path).read_text(encoding="utf-8"))
        winner = (
            (data.get("scorecard") or {}).get("left_right_winner")
            or (data.get("scorecard") or {}).get("left_right_winner".upper())
        )
    else:
        winner = None
except Exception:
    winner = None

# For pommerman_1v1 regime A00 on the LEFT side only:
# toggle iff previous winner is right.
if os.environ.get("OPENCLAW_SIDE") == "left" and (winner or "").strip().lower() == "right":
    AGGRESSION = 1 - AGGRESSION


def make_agent():
    if AGGRESSION == 0:
        return agents.SimpleAgent()
    return agents.RandomAgent()


if __name__ == "__main__":
    agent = make_agent()
    print(type(agent).__name__)

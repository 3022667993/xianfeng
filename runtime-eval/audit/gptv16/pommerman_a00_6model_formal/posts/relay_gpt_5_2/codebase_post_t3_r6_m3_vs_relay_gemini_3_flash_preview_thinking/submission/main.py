from __future__ import annotations

from pommerman import agents

# For pommerman_1v1 regime A00 on the LEFT side only:
# If previous round winner is right, toggle AGGRESSION between 0 and 1.
# Winner is read from feedback_package.json (scorecard.left_right_winner).
import json
import os
from pathlib import Path

AGGRESSION = 0

try:
    fb_path = os.environ.get("FEEDBACK_PACKAGE_PATH")
    if not fb_path:
        fb_path = str(Path(__file__).resolve().parents[2] / "feedback_package.json")
    data = json.loads(Path(fb_path).read_text(encoding="utf-8"))
    winner = (data.get("scorecard") or {}).get("left_right_winner")
except Exception:
    winner = None

side = (os.environ.get("OPENCLAW_SIDE") or "").strip().lower()
if side == "left" and (winner or "").strip().lower() == "right":
    AGGRESSION = 1 - AGGRESSION


def make_agent():
    if AGGRESSION == 0:
        return agents.SimpleAgent()
    return agents.RandomAgent()


if __name__ == "__main__":
    agent = make_agent()
    print(type(agent).__name__)

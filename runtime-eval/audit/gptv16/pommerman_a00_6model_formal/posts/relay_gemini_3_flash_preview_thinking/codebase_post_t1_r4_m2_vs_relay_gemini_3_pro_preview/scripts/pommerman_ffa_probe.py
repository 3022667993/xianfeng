from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pommerman
from pommerman import agents


def to_jsonable(x):
    if isinstance(x, dict):
        return {k: to_jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [to_jsonable(v) for v in x]
    if hasattr(x, "name"):
        return x.name
    try:
        json.dumps(x)
        return x
    except Exception:
        return str(x)


def load_agent_from_submission(submission_main: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, submission_main)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load submission module: {submission_main}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "make_agent"):
        raise RuntimeError(f"{submission_main} missing make_agent()")

    agent = module.make_agent()
    return agent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--left-submission", required=True)
    parser.add_argument("--right-submission", required=True)
    args = parser.parse_args()

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    left_main = Path(args.left_submission).resolve()
    right_main = Path(args.right_submission).resolve()

    env_id = "PommeFFACompetition-v0"

    left_agent = load_agent_from_submission(left_main, "left_submission_main")
    right_agent = load_agent_from_submission(right_main, "right_submission_main")

    agent_list = [
        left_agent,
        right_agent,
        agents.SimpleAgent(),
        agents.SimpleAgent(),
    ]

    env = pommerman.make(env_id, agent_list)

    try:
        state = env.reset()
        done = False
        step_count = 0
        reward = None
        info = {}

        while not done and step_count < 800:
            actions = env.act(state)
            state, reward, done, info = env.step(actions)
            step_count += 1

        reward_json = to_jsonable(reward)
        info_json = to_jsonable(info)

        left_score = reward_json[0] if isinstance(reward_json, list) and len(reward_json) > 0 else None
        right_score = reward_json[1] if isinstance(reward_json, list) and len(reward_json) > 1 else None

        if left_score is not None and right_score is not None:
            if left_score > right_score:
                lr_winner = "left"
            elif right_score > left_score:
                lr_winner = "right"
            else:
                lr_winner = "draw"
        else:
            lr_winner = "draw"

        payload = {
            "env_id": env_id,
            "done": bool(done),
            "steps": step_count,
            "reward": reward_json,
            "info": info_json,
            "left_score": left_score,
            "right_score": right_score,
            "left_right_winner": lr_winner,
            "left_submission": str(left_main),
            "right_submission": str(right_main),
        }

        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(payload, ensure_ascii=False))
    finally:
        env.close()


if __name__ == "__main__":
    main()

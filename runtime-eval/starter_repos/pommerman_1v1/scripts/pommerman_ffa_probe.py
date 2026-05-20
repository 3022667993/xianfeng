from __future__ import annotations

import argparse
from datetime import datetime
import importlib.util
import json
import shutil
from pathlib import Path
import sys
from typing import Any

import pommerman
from pommerman import agents
try:
    from pommerman import utility
except ImportError:
    utility = None

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from seed_control import apply_env_seed, apply_pre_env_seed

RECORD_AGENT_LABELS = ["left", "right", "dummy2", "dummy3"]


class PassiveDummyAgent(agents.BaseAgent):
    def act(self, obs, action_space=None):
        return 0


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


def _to_int(x: Any) -> int | None:
    try:
        return int(x)
    except Exception:
        return None


def _alive_map(state: Any) -> dict[str, bool | None]:
    out = {f"seat_{i}": None for i in range(4)}
    if not isinstance(state, (list, tuple)) or len(state) < 4:
        return out
    obs0 = state[0] if isinstance(state[0], dict) else {}
    alive_raw = obs0.get("alive") if isinstance(obs0, dict) else None
    if not isinstance(alive_raw, (list, tuple)):
        return out
    alive_ids = {_to_int(v) for v in alive_raw}
    for i in range(4):
        # Pommerman agents are commonly encoded as Item.Agent0..3 ~= 10..13.
        out[f"seat_{i}"] = (10 + i) in alive_ids if None not in alive_ids else None
    return out


def _positions_map(state: Any) -> dict[str, list[int] | None]:
    out: dict[str, list[int] | None] = {}
    for i in range(4):
        pos = None
        if isinstance(state, (list, tuple)) and len(state) > i and isinstance(state[i], dict):
            raw = state[i].get("position")
            if (
                isinstance(raw, (list, tuple))
                and len(raw) == 2
                and _to_int(raw[0]) is not None
                and _to_int(raw[1]) is not None
            ):
                pos = [int(raw[0]), int(raw[1])]
        out[f"seat_{i}"] = pos
    return out


def _compact_counts(state: Any) -> tuple[dict[str, int | None], list[str]]:
    counts = {"bomb_count": None, "flame_count": None, "powerup_count": None}
    notes: list[str] = []
    if not isinstance(state, (list, tuple)) or not state or not isinstance(state[0], dict):
        notes.append("board_unavailable")
        return counts, notes
    board = state[0].get("board")
    if board is None:
        notes.append("board_unavailable")
        return counts, notes
    try:
        bomb_count = 0
        flame_count = 0
        powerup_count = 0
        for row in board:
            for cell in row:
                v = _to_int(cell)
                if v is None:
                    continue
                if v == 3:
                    bomb_count += 1
                if v == 4:
                    flame_count += 1
                if v in {6, 7, 8}:
                    powerup_count += 1
        counts["bomb_count"] = bomb_count
        counts["flame_count"] = flame_count
        counts["powerup_count"] = powerup_count
    except Exception:
        notes.append("board_parse_failed")
    return counts, notes


def _normalize_record_json_dir(record_json_dir: Path | None) -> bool:
    if record_json_dir is None:
        return False
    canonical = record_json_dir / "game_state.json"
    if canonical.exists():
        return True
    candidates = sorted(
        p for p in record_json_dir.rglob("game_state.json")
        if p.is_file() and p.resolve() != canonical.resolve()
    )
    if not candidates:
        return False
    canonical.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidates[0], canonical)
    return canonical.exists()


def _make_env(env_id: str, agent_list: list[Any], record_json_dir: Path | None):
    if record_json_dir is not None:
        record_json_dir.mkdir(parents=True, exist_ok=True)
    return pommerman.make(env_id, agent_list)


def _warn_record_json(message: str, exc: Exception) -> None:
    print(f"[record-json-dir] {message}: {exc!r}", file=sys.stderr)


def _save_record_json_snapshot(env: Any, record_json_dir: Path | None, context: str) -> bool:
    if record_json_dir is None:
        return False
    try:
        env.save_json(str(record_json_dir))
        return True
    except Exception as exc:
        _warn_record_json(f"snapshot skipped at {context}", exc)
        return False


def _finalize_record_json_dir(record_json_dir: Path | None, env_id: str, info: Any) -> bool:
    if record_json_dir is None:
        return False
    if utility is None:
        return _normalize_record_json_dir(record_json_dir)
    try:
        utility.join_json_state(
            str(record_json_dir),
            RECORD_AGENT_LABELS,
            datetime.now().isoformat(),
            env_id,
            info if isinstance(info, dict) else {},
        )
    except Exception as exc:
        _warn_record_json("failed to finalize game_state.json", exc)
    return _normalize_record_json_dir(record_json_dir)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--left-submission", required=True)
    parser.add_argument("--right-submission", required=True)
    parser.add_argument("--compact-out", default=None)
    parser.add_argument("--requested-seed", type=int, default=None)
    parser.add_argument("--record-json-dir", default=None)
    args = parser.parse_args()

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    compact_out = Path(args.compact_out).resolve() if args.compact_out else None
    if compact_out is not None:
        compact_out.parent.mkdir(parents=True, exist_ok=True)
    record_json_dir = Path(args.record_json_dir).resolve() if args.record_json_dir else None
    if record_json_dir is not None:
        record_json_dir.mkdir(parents=True, exist_ok=True)

    left_main = Path(args.left_submission).resolve()
    right_main = Path(args.right_submission).resolve()

    env_id = "PommeFFACompetition-v0"

    requested_seed = args.requested_seed
    pre_env_seed_provenance = apply_pre_env_seed(requested_seed)

    left_agent = load_agent_from_submission(left_main, "left_submission_main")
    right_agent = load_agent_from_submission(right_main, "right_submission_main")

    agent_list = [
        left_agent,
        right_agent,
        PassiveDummyAgent(),
        PassiveDummyAgent(),
    ]

    env = _make_env(env_id, agent_list, record_json_dir)

    try:
        seed_provenance = apply_env_seed(env, requested_seed, prior_provenance=pre_env_seed_provenance)
        state = env.reset()
        record_json_active = _save_record_json_snapshot(env, record_json_dir, "reset") if record_json_dir is not None else False
        applied_seed = seed_provenance.get("applied_seed")
        seed_control_status = str(seed_provenance.get("seed_control_status") or "requested_but_not_applied")
        seed_control_error = seed_provenance.get("seed_control_error")
        methods_attempted = seed_provenance.get("seed_control_methods_attempted", [])
        method_applied = seed_provenance.get("seed_control_method_applied")
        env_seed_return = seed_provenance.get("seed_control_env_seed_return")
        print(
            f"[seed-control] status={seed_control_status} requested={requested_seed} "
            f"applied={applied_seed} method={method_applied} env_seed_return={env_seed_return} "
            f"error={seed_control_error}",
            file=sys.stderr,
        )
        done = False
        step_count = 0
        reward = None
        info = {}
        compact_rows = []
        prev_alive = None
        prev_reward = None

        while not done and step_count < 800:
            actions = env.act(state)
            state, reward, done, info = env.step(actions)
            if record_json_active:
                record_json_active = _save_record_json_snapshot(env, record_json_dir, f"step_{step_count + 1}")
            alive = _alive_map(state)
            positions = _positions_map(state)
            counts, notes = _compact_counts(state)
            row = {
                "schema_version": "pommerman_compact_trajectory_step_v2",
                "leg_label": None,
                "step": step_count,
                "actions": {
                    "seat_0": _to_int(actions[0]) if isinstance(actions, (list, tuple)) and len(actions) > 0 else None,
                    "seat_1": _to_int(actions[1]) if isinstance(actions, (list, tuple)) and len(actions) > 1 else None,
                    "seat_2": _to_int(actions[2]) if isinstance(actions, (list, tuple)) and len(actions) > 2 else None,
                    "seat_3": _to_int(actions[3]) if isinstance(actions, (list, tuple)) and len(actions) > 3 else None,
                },
                "reward": to_jsonable(reward),
                "done": bool(done),
                "alive": alive,
                "positions": positions,
                "compact_counts": counts,
                "event_flags": {
                    "terminal": bool(done),
                    "alive_changed": prev_alive is not None and alive != prev_alive,
                    "reward_changed": prev_reward is not None and to_jsonable(reward) != prev_reward,
                },
            }
            if notes:
                row["capture_notes"] = notes
            compact_rows.append(row)
            prev_alive = alive
            prev_reward = to_jsonable(reward)
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
            "background_agents": ["dummy2", "dummy3"],
            "requested_seed": seed_provenance.get("requested_seed"),
            "applied_seed": applied_seed,
            "seed": seed_provenance.get("seed"),
            "seed_control_status": seed_control_status,
            "seed_control_error": seed_control_error,
            "seed_control_methods_attempted": methods_attempted if isinstance(methods_attempted, list) else [],
            "seed_control_method_applied": method_applied,
            "seed_control_env_seed_return": env_seed_return,
        }

        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if compact_out is not None:
            with compact_out.open("w", encoding="utf-8") as f:
                for row in compact_rows:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
        if record_json_active:
            _finalize_record_json_dir(record_json_dir, env_id, info)
        print(json.dumps(payload, ensure_ascii=False))
    finally:
        env.close()
        _normalize_record_json_dir(record_json_dir)


if __name__ == "__main__":
    main()

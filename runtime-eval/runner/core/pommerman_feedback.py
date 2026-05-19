from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _winner_from_lr(value: Any) -> str:
    if value in {"left", "right", "draw"}:
        return str(value)
    return "unknown"


def _compact_leg_metrics(match_dir: Path, leg_label: str, tested_side: str) -> dict[str, float | int]:
    path = match_dir / f"trajectory_compact_{leg_label}.jsonl"
    if not path.exists():
        return {"bomb_action_rate": 0.0, "stop_action_rate": 0.0, "step_count": 0}
    seat_key = "seat_0" if tested_side == "left" else "seat_1"
    total = 0
    bomb = 0
    stop = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        actions = payload.get("actions")
        if not isinstance(actions, dict):
            continue
        action = actions.get(seat_key)
        if action is None:
            continue
        total += 1
        if action == 5:
            bomb += 1
        if action == 0:
            stop += 1
    if total <= 0:
        return {"bomb_action_rate": 0.0, "stop_action_rate": 0.0, "step_count": 0}
    return {
        "bomb_action_rate": round(bomb / total, 6),
        "stop_action_rate": round(stop / total, 6),
        "step_count": total,
    }


def _seat_result(leg: dict, side: str) -> str:
    winner = _winner_from_lr(leg.get("left_right_winner"))
    if winner == "draw":
        return "draw"
    if winner == "unknown":
        return "unknown"
    return "win" if winner == side else "loss"


def build_trajectory_summary(match_dir: Path, round_idx: int, match_idx: int) -> dict:
    md = load_json(match_dir / "metadata.json")
    sc = load_json(match_dir / "scorecard.json")
    leg_a = load_json(match_dir / "arena_result_match_a.json")

    left_agent_id = str(md.get("left_agent_id"))
    right_agent_id = str(md.get("right_agent_id"))
    pair_id = str(md.get("pair_id"))
    match_id = str(md.get("match_id") or f"match_{match_idx}")

    left_result = _seat_result(leg_a, "left")
    right_result = _seat_result(leg_a, "right")
    leg = {
        "label": "match_a",
        "path": str(match_dir / "arena_result_match_a.json"),
        "steps": int(leg_a.get("steps", -1) or -1),
        "done": bool(leg_a.get("done", False)),
        "reward": leg_a.get("reward"),
        "winner_seats": ((leg_a.get("info") or {}).get("winners") if isinstance(leg_a.get("info"), dict) else None),
        "left_right_winner": _winner_from_lr(leg_a.get("left_right_winner")),
        "seat_assignment": leg_a.get("seat_assignment", {}),
        "tested_left_result": left_result,
        "tested_right_result": right_result,
        "dummy_win": False,
    }

    summary = {
        "schema_version": "pommerman_process_feedback_v2",
        "round_idx": int(round_idx),
        "match_idx": int(match_idx),
        "match_id": match_id,
        "pair_id": pair_id,
        "schedule_mode": "double_round_robin",
        "match_legs": "single",
        "left_agent_id": left_agent_id,
        "right_agent_id": right_agent_id,
        "background_agents": md.get("background_agents", ["dummy2", "dummy3"]),
        "scorecard_policy": md.get("scorecard_policy", "raw_per_match_scorecard; pair-level aggregation is post-analysis"),
        "seed": md.get("seed", sc.get("seed")),
        "requested_seed": md.get("requested_seed", sc.get("requested_seed")),
        "applied_seed": md.get("applied_seed", sc.get("applied_seed")),
        "seed_control_status": md.get("seed_control_status", sc.get("seed_control_status", "unknown")),
        "seed_control_error": md.get("seed_control_error", sc.get("seed_control_error")),
        "seed_control_methods_attempted": md.get("seed_control_methods_attempted", sc.get("seed_control_methods_attempted", [])),
        "seed_control_method_applied": md.get("seed_control_method_applied", sc.get("seed_control_method_applied")),
        "seed_control_env_seed_return": md.get("seed_control_env_seed_return", sc.get("seed_control_env_seed_return")),
        "legs": [leg],
        "seat_swap_summary": {
            "same_requested_seed": True,
            "match_a_left_right_winner": leg["left_right_winner"],
            "outcome_changed_under_swap": None,
            "dummy_win_any_leg": False,
            "tested_agent_win_any_leg": any(x in {"win"} for x in [left_result, right_result]),
            "both_tested_agents_lost_any_leg": bool(left_result == "loss" and right_result == "loss"),
        },
        "agent_summaries": {
            left_agent_id: {
                "agent_id": left_agent_id,
                "roles_seen": ["left"],
                "wins": int(left_result == "win"),
                "losses": int(left_result == "loss"),
                "draws": int(left_result == "draw"),
                "best_leg": "match_a" if left_result in {"win", "draw"} else None,
                "worst_leg": "match_a" if left_result == "loss" else None,
                "survival_steps_observed": [leg["steps"]],
                "seat_sensitivity_observed": None,
                "dummy_interference_observed": False,
                "factual_observations": [
                    f"Observed {int(left_result == 'win')} win(s), {int(left_result == 'loss')} loss(es), {int(left_result == 'draw')} draw(s) in match_a.",
                    f"Single-leg result: match_a={leg['left_right_winner']}.",
                    f"Leg length (steps): match_a={leg['steps']}.",
                ],
                "next_round_hints": ["Keep survival-first behavior when no safe advantage is visible."],
            },
            right_agent_id: {
                "agent_id": right_agent_id,
                "roles_seen": ["right"],
                "wins": int(right_result == "win"),
                "losses": int(right_result == "loss"),
                "draws": int(right_result == "draw"),
                "best_leg": "match_a" if right_result in {"win", "draw"} else None,
                "worst_leg": "match_a" if right_result == "loss" else None,
                "survival_steps_observed": [leg["steps"]],
                "seat_sensitivity_observed": None,
                "dummy_interference_observed": False,
                "factual_observations": [
                    f"Observed {int(right_result == 'win')} win(s), {int(right_result == 'loss')} loss(es), {int(right_result == 'draw')} draw(s) in match_a.",
                    f"Single-leg result: match_a={leg['left_right_winner']}.",
                    f"Leg length (steps): match_a={leg['steps']}.",
                ],
                "next_round_hints": ["Keep survival-first behavior when no safe advantage is visible."],
            },
        },
    }
    return summary


def build_agent_feedback(summary: dict, agent_id: str, match_dir: Path) -> dict:
    left = summary["left_agent_id"]
    right = summary["right_agent_id"]
    side = "left" if agent_id == left else "right"
    opp = right if side == "left" else left
    leg = summary["legs"][0]
    result = leg[f"tested_{side}_result"]
    m_a = _compact_leg_metrics(match_dir, "match_a", side)
    steps_total = int(m_a["step_count"])
    bomb_rate = m_a["bomb_action_rate"] if steps_total > 0 else 0.0
    stop_rate = m_a["stop_action_rate"] if steps_total > 0 else 0.0
    diag = {
        "seat_sensitivity_observed": False,
        "dummy_interference_observed": False,
        "both_tested_agents_lost_any_leg": bool(summary["seat_swap_summary"]["both_tested_agents_lost_any_leg"]),
        "short_game_loss_observed": bool(result == "loss" and isinstance(leg["steps"], int) and leg["steps"] <= 100),
        "long_game_win_observed": bool(result == "win" and isinstance(leg["steps"], int) and leg["steps"] >= 250),
        "bomb_action_rate": round(bomb_rate, 6),
        "stop_action_rate": round(stop_rate, 6),
        "average_terminal_step": round(float(leg["steps"]), 3),
        "non_draw_match_count": int(result in {"win", "loss"}),
    }
    compact_events_path = match_dir / "trajectory_events.json"
    compact_events = None
    if compact_events_path.exists():
        try:
            compact_events = load_json(compact_events_path)
        except Exception:
            compact_events = None
    compact_v2 = None
    if isinstance(compact_events, dict):
        compact_v2 = {
            "events_path": str(compact_events_path),
            "match_a": compact_events.get("legs", {}).get("match_a", {}),
            "limitations": compact_events.get("limitations", []),
        }

    if compact_v2 is not None:
        limitations = [
            "process_feedback_v2 is derived from result-level arena artifacts and compact trajectory v2 when available",
            "compact trajectory v2 records lightweight per-step actions/rewards/alive/positions/counts when available",
            "full board states, full observations, death causes, bomb ownership, and power-up pickup causes are not yet recorded",
            "seat-swap instability is not applicable in single-leg mode",
        ]
    else:
        limitations = [
            "process_feedback_v2 is derived from result-level arena artifacts only",
            "tick-level actions, board states, bomb events, and death causes are not yet recorded",
            "seat-swap instability is not applicable in single-leg mode",
        ]

    return {
        "schema_version": "pommerman_agent_feedback_v2",
        "round_idx": summary["round_idx"],
        "match_idx": summary["match_idx"],
        "match_id": summary["match_id"],
        "agent_id": agent_id,
        "opponent_agent_id": opp,
        "background_agents": summary.get("background_agents", ["dummy2", "dummy3"]),
        "source_files": {
            "metadata": str(match_dir / "metadata.json"),
            "scorecard": str(match_dir / "scorecard.json"),
            "arena_result_match_a": str(match_dir / "arena_result_match_a.json"),
            "trajectory_summary": str(match_dir / "trajectory_summary.json"),
        },
        "result_summary": {
            "wins": int(result == "win"),
            "losses": int(result == "loss"),
            "draws": int(result == "draw"),
            "legs": [{"label": "match_a", "result": result, "left_right_winner": leg["left_right_winner"], "steps": leg["steps"]}],
        },
        "diagnostics": diag,
        "factual_observations": list(summary["agent_summaries"][agent_id]["factual_observations"]),
        "next_round_hints": list(summary["agent_summaries"][agent_id]["next_round_hints"]),
        "compact_trajectory_v2": compact_v2,
        "limitations": limitations,
    }


def _feedback_md(payload: dict) -> str:
    lines = []
    lines.append(f"# Agent Feedback: {payload['agent_id']}")
    lines.append("")
    lines.append(f"- Match: {payload['match_id']} (round {payload['round_idx']}, match {payload['match_idx']})")
    lines.append(f"- Opponent: {payload['opponent_agent_id']}")
    rs = payload["result_summary"]
    lines.append(f"- Totals: wins={rs['wins']}, losses={rs['losses']}, draws={rs['draws']}")
    lines.append("")
    lines.append("## Outcome")
    for leg in rs["legs"]:
        lines.append(f"- {leg['label']}: result={leg['result']}, left_right_winner={leg['left_right_winner']}, steps={leg['steps']}")
    lines.append("")
    lines.append("## Diagnostics")
    d = payload["diagnostics"]
    for k in ["seat_sensitivity_observed", "dummy_interference_observed", "both_tested_agents_lost_any_leg", "short_game_loss_observed", "long_game_win_observed"]:
        lines.append(f"- {k}: {d[k]}")
    for k in ["bomb_action_rate", "stop_action_rate", "average_terminal_step", "non_draw_match_count"]:
        lines.append(f"- {k}: {d[k]}")
    lines.append("")
    lines.append("## Factual Observations")
    for x in payload["factual_observations"]:
        lines.append(f"- {x}")
    lines.append("")
    lines.append("## Next-Round Hints")
    for x in payload["next_round_hints"]:
        lines.append(f"- {x}")
    lines.append("")
    lines.append("## Compact Trajectory v2")
    c = payload.get("compact_trajectory_v2")
    if not isinstance(c, dict):
        lines.append("- compact trajectory v2 artifact not available for this match")
    else:
        lines.append(f"- events_path: {c.get('events_path')}")
        leg = c.get("match_a", {})
        if isinstance(leg, dict):
            lines.append(
                f"- match_a: capture_status={leg.get('capture_status')}, step_count={leg.get('step_count')}, terminal_step={leg.get('terminal_step')}, first_reward_change_step={leg.get('first_reward_change_step')}, alive_change_steps={leg.get('alive_change_steps')}"
            )
        lims = c.get("limitations", [])
        if isinstance(lims, list):
            for x in lims:
                lines.append(f"- limitation: {x}")
    lines.append("")
    lines.append("## Limitations")
    for x in payload["limitations"]:
        lines.append(f"- {x}")
    lines.append("")
    return "\n".join(lines)


def write_process_feedback(match_dir: Path, round_idx: int | None = None, match_idx: int | None = None) -> dict:
    md = load_json(match_dir / "metadata.json")
    if round_idx is None:
        round_idx = int(md.get("round_idx", 0) or 0)
    if match_idx is None:
        match_idx = int(md.get("match_idx", 0) or 0)
    summary = build_trajectory_summary(match_dir, round_idx=round_idx, match_idx=match_idx)
    (match_dir / "trajectory_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    for agent_id in [summary["left_agent_id"], summary["right_agent_id"]]:
        feedback = build_agent_feedback(summary, agent_id, match_dir)
        (match_dir / f"agent_feedback_{agent_id}.json").write_text(
            json.dumps(feedback, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (match_dir / f"agent_feedback_{agent_id}.md").write_text(_feedback_md(feedback), encoding="utf-8")
    return summary


def write_feedback_artifact_mirrors(match_dir: Path, tournament_name: str, round_idx: int) -> None:
    summary = load_json(match_dir / "trajectory_summary.json")
    for agent_id in [summary["left_agent_id"], summary["right_agent_id"]]:
        src = match_dir / f"agent_feedback_{agent_id}.md"
        if not src.exists():
            continue
        for dst_root in [
            Path("workspace/codebases") / tournament_name / agent_id / f"codebase_play_{round_idx}" / "feedback",
            Path("workspace/posts") / tournament_name / agent_id / f"codebase_post_{round_idx}" / "feedback",
        ]:
            dst_root.mkdir(parents=True, exist_ok=True)
            dst = dst_root / f"round_{round_idx}_match_{summary['match_idx']}.md"
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

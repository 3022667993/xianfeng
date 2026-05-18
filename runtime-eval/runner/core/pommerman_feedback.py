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


def _dummy_win(leg: dict) -> bool:
    winners = (leg.get("info") or {}).get("winners")
    seat_assignment = leg.get("seat_assignment") or {}
    if not isinstance(winners, list):
        return False
    for w in winners:
        key = f"seat_{w}_submission"
        if seat_assignment.get(key) in {"dummy2", "dummy3"}:
            return True
    return False


def _tested_result_by_winners(leg: dict, tested_side: str) -> str:
    winners = (leg.get("info") or {}).get("winners")
    seat_assignment = leg.get("seat_assignment") or {}
    if isinstance(winners, list):
        winner_seats = set()
        for w in winners:
            key = f"seat_{w}_submission"
            winner_seats.add(seat_assignment.get(key))
        if tested_side in winner_seats:
            return "win"
        if winner_seats & {"dummy2", "dummy3"}:
            return "loss"
        lr = _winner_from_lr(leg.get("left_right_winner"))
        if lr == "draw":
            return "draw"
        if lr in {"left", "right"}:
            return "loss"
    return _seat_result(leg, tested_side)


def build_trajectory_summary(match_dir: Path, round_idx: int, match_idx: int) -> dict:
    md = load_json(match_dir / "metadata.json")
    sc = load_json(match_dir / "scorecard.json")
    leg_a = load_json(match_dir / "arena_result_match_a.json")
    leg_b = load_json(match_dir / "arena_result_match_b.json")

    left_agent_id = str(md.get("left_agent_id"))
    right_agent_id = str(md.get("right_agent_id"))
    pair_id = str(md.get("pair_id"))
    match_id = str(md.get("match_id") or f"match_{match_idx}")

    legs = []
    for label, leg, path in [
        ("match_a", leg_a, match_dir / "arena_result_match_a.json"),
        ("match_b", leg_b, match_dir / "arena_result_match_b.json"),
    ]:
        left_result = _tested_result_by_winners(leg, "left")
        right_result = _tested_result_by_winners(leg, "right")
        legs.append(
            {
                "label": label,
                "path": str(path),
                "steps": int(leg.get("steps", -1) or -1),
                "done": bool(leg.get("done", False)),
                "reward": leg.get("reward"),
                "winner_seats": ((leg.get("info") or {}).get("winners") if isinstance(leg.get("info"), dict) else None),
                "left_right_winner": _winner_from_lr(leg.get("left_right_winner")),
                "seat_assignment": leg.get("seat_assignment", {}),
                "tested_left_result": left_result,
                "tested_right_result": right_result,
                "dummy_win": _dummy_win(leg),
            }
        )

    same_seed = legs[0].get("path") and (leg_a.get("requested_seed") == leg_b.get("requested_seed"))
    outcome_changed_under_swap = legs[0]["left_right_winner"] != legs[1]["left_right_winner"]
    tested_win_any = any(x in {"win"} for x in [legs[0]["tested_left_result"], legs[0]["tested_right_result"], legs[1]["tested_left_result"], legs[1]["tested_right_result"]])

    def _agent_summary(agent_id: str, side_key: str) -> dict:
        results = [legs[0][f"tested_{side_key}_result"], legs[1][f"tested_{side_key}_result"]]
        wins = sum(1 for r in results if r == "win")
        losses = sum(1 for r in results if r == "loss")
        draws = sum(1 for r in results if r == "draw")
        best_leg = None
        worst_leg = None
        if "win" in results:
            best_leg = legs[results.index("win")]["label"]
        elif "draw" in results:
            best_leg = legs[results.index("draw")]["label"]
        if "loss" in results:
            worst_leg = legs[results.index("loss")]["label"]
        factual = [
            f"Observed {wins} win(s), {losses} loss(es), {draws} draw(s) across match_a/match_b.",
            f"Seat-swap winners: match_a={legs[0]['left_right_winner']}, match_b={legs[1]['left_right_winner']}.",
            f"Leg lengths (steps): match_a={legs[0]['steps']}, match_b={legs[1]['steps']}.",
        ]
        seat_sensitivity = outcome_changed_under_swap
        hints = ["Keep survival-first behavior when no safe advantage is visible."]
        if seat_sensitivity:
            hints.append(
                "Treat seat-swap instability as a signal to improve robustness across spawn positions."
            )
        else:
            hints.append(
                "Maintain robustness across swapped spawn positions; no seat-swap outcome change was observed in this match."
            )
        return {
            "agent_id": agent_id,
            "roles_seen": ["left", "right"],
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "best_leg": best_leg,
            "worst_leg": worst_leg,
            "survival_steps_observed": [legs[0]["steps"], legs[1]["steps"]],
            "seat_sensitivity_observed": seat_sensitivity,
            "dummy_interference_observed": any(l["dummy_win"] for l in legs),
            "factual_observations": factual,
            "next_round_hints": hints,
        }

    summary = {
        "schema_version": "pommerman_process_feedback_v1",
        "round_idx": int(round_idx),
        "match_idx": int(match_idx),
        "match_id": match_id,
        "pair_id": pair_id,
        "left_agent_id": left_agent_id,
        "right_agent_id": right_agent_id,
        "background_agents": md.get("background_agents", ["dummy2", "dummy3"]),
        "scorecard_policy": md.get("scorecard_policy", "raw_per_match_scorecard; pair-level aggregation is post-analysis"),
        "seed": md.get("seed", sc.get("seed")),
        "requested_seed": md.get("requested_seed", sc.get("requested_seed")),
        "applied_seed": md.get("applied_seed", sc.get("applied_seed")),
        "seed_control_status": md.get("seed_control_status", sc.get("seed_control_status", "unknown")),
        "seed_control_error": md.get("seed_control_error", sc.get("seed_control_error")),
        "seed_control_methods_attempted": md.get(
            "seed_control_methods_attempted", sc.get("seed_control_methods_attempted", [])
        ),
        "seed_control_method_applied": md.get(
            "seed_control_method_applied", sc.get("seed_control_method_applied")
        ),
        "seed_control_env_seed_return": md.get(
            "seed_control_env_seed_return", sc.get("seed_control_env_seed_return")
        ),
        "legs": legs,
        "seat_swap_summary": {
            "same_requested_seed": bool(same_seed),
            "match_a_left_right_winner": legs[0]["left_right_winner"],
            "match_b_left_right_winner": legs[1]["left_right_winner"],
            "outcome_changed_under_swap": outcome_changed_under_swap,
            "dummy_win_any_leg": any(l["dummy_win"] for l in legs),
            "tested_agent_win_any_leg": tested_win_any,
            "both_tested_agents_lost_any_leg": any(
                (l["tested_left_result"] == "loss" and l["tested_right_result"] == "loss") for l in legs
            ),
        },
        "agent_summaries": {
            left_agent_id: _agent_summary(left_agent_id, "left"),
            right_agent_id: _agent_summary(right_agent_id, "right"),
        },
    }
    return summary


def build_agent_feedback(summary: dict, agent_id: str, match_dir: Path) -> dict:
    left = summary["left_agent_id"]
    right = summary["right_agent_id"]
    side = "left" if agent_id == left else "right"
    opp = right if side == "left" else left
    leg_results = []
    for leg in summary["legs"]:
        leg_results.append({
            "label": leg["label"],
            "result": leg[f"tested_{side}_result"],
            "left_right_winner": leg["left_right_winner"],
            "steps": leg["steps"],
        })
    wins = sum(1 for x in leg_results if x["result"] == "win")
    losses = sum(1 for x in leg_results if x["result"] == "loss")
    draws = sum(1 for x in leg_results if x["result"] == "draw")
    m_a = _compact_leg_metrics(match_dir, "match_a", side)
    m_b = _compact_leg_metrics(match_dir, "match_b", side)
    steps_total = int(m_a["step_count"]) + int(m_b["step_count"])
    bomb_rate = (
        ((m_a["bomb_action_rate"] * int(m_a["step_count"])) + (m_b["bomb_action_rate"] * int(m_b["step_count"]))) / steps_total
        if steps_total > 0
        else 0.0
    )
    stop_rate = (
        ((m_a["stop_action_rate"] * int(m_a["step_count"])) + (m_b["stop_action_rate"] * int(m_b["step_count"]))) / steps_total
        if steps_total > 0
        else 0.0
    )
    terminal_steps = [x["steps"] for x in leg_results if isinstance(x.get("steps"), int) and x.get("steps", -1) >= 0]
    avg_terminal_step = (sum(terminal_steps) / len(terminal_steps)) if terminal_steps else 0.0
    non_draw_match_count = sum(1 for x in leg_results if x["result"] in {"win", "loss"})
    diag = {
        "seat_sensitivity_observed": bool(summary["agent_summaries"][agent_id]["seat_sensitivity_observed"]),
        "dummy_interference_observed": bool(summary["agent_summaries"][agent_id]["dummy_interference_observed"]),
        "both_tested_agents_lost_any_leg": bool(summary["seat_swap_summary"]["both_tested_agents_lost_any_leg"]),
        "short_game_loss_observed": any(x["result"] == "loss" and isinstance(x["steps"], int) and x["steps"] <= 100 for x in leg_results),
        "long_game_win_observed": any(x["result"] == "win" and isinstance(x["steps"], int) and x["steps"] >= 250 for x in leg_results),
        "bomb_action_rate": round(bomb_rate, 6),
        "stop_action_rate": round(stop_rate, 6),
        "average_terminal_step": round(avg_terminal_step, 3),
        "non_draw_match_count": int(non_draw_match_count),
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
        legs = compact_events.get("legs", {})
        compact_v2 = {
            "events_path": str(compact_events_path),
            "match_a": legs.get("match_a", {}),
            "match_b": legs.get("match_b", {}),
            "limitations": compact_events.get("limitations", []),
        }

    if compact_v2 is not None:
        limitations = [
            "process_feedback_v1 is derived from result-level arena artifacts and compact trajectory v2 when available",
            "compact trajectory v2 records lightweight per-step actions/rewards/alive/positions/counts when available",
            "full board states, full observations, death causes, bomb ownership, and power-up pickup causes are not yet recorded",
        ]
    else:
        limitations = [
            "process_feedback_v1 is derived from result-level arena artifacts only",
            "tick-level actions, board states, bomb events, and death causes are not yet recorded",
        ]

    return {
        "schema_version": "pommerman_agent_feedback_v1",
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
            "arena_result_match_b": str(match_dir / "arena_result_match_b.json"),
            "trajectory_summary": str(match_dir / "trajectory_summary.json"),
        },
        "result_summary": {
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "legs": leg_results,
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
    lines.append("## Outcome By Leg")
    for leg in rs["legs"]:
        lines.append(f"- {leg['label']}: result={leg['result']}, left_right_winner={leg['left_right_winner']}, steps={leg['steps']}")
    lines.append("")
    lines.append("## Seat-Swap Diagnostics")
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
        for leg_label in ["match_a", "match_b"]:
            leg = c.get(leg_label, {})
            if not isinstance(leg, dict):
                continue
            lines.append(
                f"- {leg_label}: capture_status={leg.get('capture_status')}, step_count={leg.get('step_count')}, terminal_step={leg.get('terminal_step')}, first_reward_change_step={leg.get('first_reward_change_step')}, alive_change_steps={leg.get('alive_change_steps')}"
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

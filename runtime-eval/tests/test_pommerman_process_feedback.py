import json
from pathlib import Path

from runner.core.pommerman_feedback import _feedback_md, build_agent_feedback, build_trajectory_summary
from scripts.audit_pommerman_process_feedback import audit_process_feedback


def _mk_match(tmp_path: Path, left: str = "a1", right: str = "a2") -> Path:
    md = tmp_path / "logs" / "round_1" / "match_1"
    md.mkdir(parents=True, exist_ok=True)
    (md / "metadata.json").write_text(
        json.dumps(
            {
                "round_idx": 1,
                "match_idx": 1,
                "match_id": "match_1",
                "pair_id": f"{left}__vs__{right}",
                "left_agent_id": left,
                "right_agent_id": right,
                "background_agents": ["dummy2", "dummy3"],
                "scorecard_policy": "raw_per_match_scorecard; pair-level aggregation is post-analysis",
                "requested_seed": 7,
                "applied_seed": None,
                "seed": None,
                "seed_control_status": "requested_but_not_applied",
            }
        ),
        encoding="utf-8",
    )
    (md / "scorecard.json").write_text(json.dumps({"seed": 7}), encoding="utf-8")
    (md / "arena_result_match_a.json").write_text(
        json.dumps(
            {
                "done": True,
                "steps": 10,
                "reward": [1, -1, -1, -1],
                "info": {"winners": [0], "result": "Win"},
                "left_right_winner": "left",
                "seat_assignment": {
                    "seat_0_submission": "left",
                    "seat_1_submission": "right",
                    "seat_2_submission": "dummy2",
                    "seat_3_submission": "dummy3",
                },
                "requested_seed": 7,
                "applied_seed": None,
                "seed": None,
                "seed_control_status": "requested_but_not_applied",
            }
        ),
        encoding="utf-8",
    )
    (md / "arena_result_match_b.json").write_text(
        json.dumps(
            {
                "done": True,
                "steps": 12,
                "reward": [-1, 1, -1, -1],
                "info": {"winners": [1], "result": "Win"},
                "left_right_winner": "right",
                "seat_assignment": {
                    "seat_0_submission": "right",
                    "seat_1_submission": "left",
                    "seat_2_submission": "dummy2",
                    "seat_3_submission": "dummy3",
                },
                "requested_seed": 7,
                "applied_seed": None,
                "seed": None,
                "seed_control_status": "requested_but_not_applied",
            }
        ),
        encoding="utf-8",
    )
    return md


def test_build_trajectory_summary_and_agent_feedback(tmp_path):
    match_dir = _mk_match(tmp_path)
    summary = build_trajectory_summary(match_dir, 1, 1)
    assert summary["schema_version"] == "pommerman_process_feedback_v1"
    assert summary["seat_swap_summary"]["outcome_changed_under_swap"] is True
    assert summary["seat_swap_summary"]["same_requested_seed"] is True
    assert summary["seat_swap_summary"]["dummy_win_any_leg"] is False
    fb = build_agent_feedback(summary, "a1", match_dir)
    assert fb["schema_version"] == "pommerman_agent_feedback_v1"
    assert fb["result_summary"]["wins"] == 2
    assert fb["source_files"]["trajectory_summary"].endswith("trajectory_summary.json")
    assert any("seat-swap instability" in h for h in fb["next_round_hints"])
    diag = fb.get("diagnostics", {})
    for k in ["bomb_action_rate", "stop_action_rate", "average_terminal_step", "non_draw_match_count"]:
        assert k in diag


def test_stable_draw_draw_has_neutral_seat_swap_hint(tmp_path):
    match_dir = _mk_match(tmp_path)
    for leg_name in ["arena_result_match_a.json", "arena_result_match_b.json"]:
        p = match_dir / leg_name
        payload = json.loads(p.read_text(encoding="utf-8"))
        payload["left_right_winner"] = "draw"
        payload["info"] = {"winners": [], "result": "Tie"}
        p.write_text(json.dumps(payload), encoding="utf-8")
    summary = build_trajectory_summary(match_dir, 1, 1)
    assert summary["seat_swap_summary"]["outcome_changed_under_swap"] is False
    fb = build_agent_feedback(summary, "a1", match_dir)
    joined = " ".join(fb["next_round_hints"]).lower()
    assert "seat-swap instability" not in joined
    assert "no seat-swap outcome change was observed" in joined


def test_process_feedback_audit_fails_on_dummy_feedback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    match_dir = _mk_match(tmp_path)
    summary = build_trajectory_summary(match_dir, 1, 1)
    (match_dir / "trajectory_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    for agent in ["a1", "a2"]:
        fb = build_agent_feedback(summary, agent, match_dir)
        (match_dir / f"agent_feedback_{agent}.json").write_text(json.dumps(fb), encoding="utf-8")
        (match_dir / f"agent_feedback_{agent}.md").write_text("ok", encoding="utf-8")
    (match_dir / "agent_feedback_dummy2.json").write_text("{}", encoding="utf-8")
    errors, _warnings = audit_process_feedback()
    assert any("dummy feedback file must not exist" in e for e in errors)


def test_process_feedback_md_uses_compact_limitations_when_present(tmp_path):
    match_dir = _mk_match(tmp_path)
    summary = build_trajectory_summary(match_dir, 1, 1)
    (match_dir / "trajectory_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    compact_events = {
        "schema_version": "pommerman_compact_trajectory_events_v2",
        "legs": {
            "match_a": {
                "trajectory_path": str(match_dir / "trajectory_compact_match_a.jsonl"),
                "capture_status": "captured",
                "step_count": 1,
                "terminal_step": None,
                "winner_seats": None,
                "first_reward_change_step": None,
                "alive_change_steps": [],
                "final_reward": [0, 0, 0, 0],
                "capture_notes": [],
            },
            "match_b": {
                "trajectory_path": str(match_dir / "trajectory_compact_match_b.jsonl"),
                "capture_status": "captured",
                "step_count": 1,
                "terminal_step": 9,
                "winner_seats": [0],
                "first_reward_change_step": 9,
                "alive_change_steps": [9],
                "final_reward": [1, -1, -1, -1],
                "capture_notes": [],
            },
        },
        "agent_event_summaries": {},
        "limitations": [
            "compact trajectory v2 does not store full board arrays",
            "compact trajectory v2 does not store full observations",
            "death causes, bomb ownership, and power-up pickup causes are only recorded if available from compact fields",
        ],
    }
    (match_dir / "trajectory_events.json").write_text(json.dumps(compact_events), encoding="utf-8")
    fb = build_agent_feedback(summary, "a1", match_dir)
    rendered = _feedback_md(fb)
    assert "compact trajectory v2 records lightweight per-step actions" in rendered.lower()
    assert "tick-level actions, board states, bomb events, and death causes are not yet recorded" not in rendered.lower()


def test_process_feedback_audit_passes_with_compact_trajectory_v2(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    match_dir = _mk_match(tmp_path)
    summary = build_trajectory_summary(match_dir, 1, 1)
    (match_dir / "trajectory_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    compact_events = {
        "schema_version": "pommerman_compact_trajectory_events_v2",
        "legs": {
            "match_a": {
                "trajectory_path": str(match_dir / "trajectory_compact_match_a.jsonl"),
                "capture_status": "captured",
                "step_count": 1,
                "terminal_step": None,
                "winner_seats": None,
                "first_reward_change_step": None,
                "alive_change_steps": [],
                "final_reward": [0, 0, 0, 0],
                "capture_notes": [],
            },
            "match_b": {
                "trajectory_path": str(match_dir / "trajectory_compact_match_b.jsonl"),
                "capture_status": "captured",
                "step_count": 1,
                "terminal_step": 9,
                "winner_seats": [0],
                "first_reward_change_step": 9,
                "alive_change_steps": [9],
                "final_reward": [1, -1, -1, -1],
                "capture_notes": [],
            },
        },
        "agent_event_summaries": {},
        "limitations": [
            "compact trajectory v2 does not store full board arrays",
            "compact trajectory v2 does not store full observations",
            "death causes, bomb ownership, and power-up pickup causes are only recorded if available from compact fields",
        ],
    }
    (match_dir / "trajectory_events.json").write_text(json.dumps(compact_events), encoding="utf-8")
    for agent in ["a1", "a2"]:
        fb = build_agent_feedback(summary, agent, match_dir)
        (match_dir / f"agent_feedback_{agent}.json").write_text(json.dumps(fb), encoding="utf-8")
        (match_dir / f"agent_feedback_{agent}.md").write_text(_feedback_md(fb), encoding="utf-8")
    errors, _warnings = audit_process_feedback()
    assert errors == []


def test_process_feedback_audit_passes_without_compact_trajectory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    match_dir = _mk_match(tmp_path)
    summary = build_trajectory_summary(match_dir, 1, 1)
    (match_dir / "trajectory_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    for agent in ["a1", "a2"]:
        fb = build_agent_feedback(summary, agent, match_dir)
        (match_dir / f"agent_feedback_{agent}.json").write_text(json.dumps(fb), encoding="utf-8")
        (match_dir / f"agent_feedback_{agent}.md").write_text(_feedback_md(fb), encoding="utf-8")
    errors, _warnings = audit_process_feedback()
    assert errors == []

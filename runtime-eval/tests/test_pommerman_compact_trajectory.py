import json
from pathlib import Path

from scripts.audit_pommerman_compact_trajectory import audit_compact_trajectory


def _mk_match(tmp_path: Path) -> Path:
    md = tmp_path / "logs" / "round_1" / "match_1"
    md.mkdir(parents=True, exist_ok=True)
    (md / "metadata.json").write_text(
        json.dumps({"left_agent_id": "a1", "right_agent_id": "a2"}),
        encoding="utf-8",
    )
    (md / "trajectory_summary.json").write_text(
        json.dumps({"schema_version": "pommerman_process_feedback_v1"}), encoding="utf-8"
    )
    for a in ["a1", "a2"]:
        (md / f"agent_feedback_{a}.json").write_text(json.dumps({"agent_id": a}), encoding="utf-8")
        (md / f"agent_feedback_{a}.md").write_text("## Compact Trajectory v2\n", encoding="utf-8")
    row = {
        "schema_version": "pommerman_compact_trajectory_step_v2",
        "leg_label": "match_a",
        "step": 0,
        "actions": {"seat_0": 0, "seat_1": 1, "seat_2": 0, "seat_3": 0},
        "reward": [0, 0, 0, 0],
        "done": False,
        "alive": {"seat_0": True, "seat_1": True, "seat_2": True, "seat_3": True},
        "positions": {"seat_0": [1, 1], "seat_1": [1, 2], "seat_2": [2, 1], "seat_3": [2, 2]},
        "compact_counts": {"bomb_count": 0, "flame_count": 0, "powerup_count": 0},
        "event_flags": {"terminal": False, "alive_changed": False, "reward_changed": False},
    }
    (md / "trajectory_compact_match_a.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    row_b = dict(row)
    row_b["leg_label"] = "match_b"
    row_b["event_flags"] = {"terminal": True, "alive_changed": True, "reward_changed": True}
    row_b["step"] = 9
    row_b["reward"] = [1, -1, -1, -1]
    (md / "trajectory_compact_match_b.jsonl").write_text(json.dumps(row_b) + "\n", encoding="utf-8")
    events = {
        "schema_version": "pommerman_compact_trajectory_events_v2",
        "legs": {
            "match_a": {
                "trajectory_path": str(md / "trajectory_compact_match_a.jsonl"),
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
                "trajectory_path": str(md / "trajectory_compact_match_b.jsonl"),
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
        "agent_event_summaries": {
            "a1": {
                "agent_id": "a1",
                "roles_seen": ["left", "right"],
                "observed_steps": [1, 1],
                "alive_change_observed": True,
                "terminal_outcomes": [None, 9],
                "compact_process_observations": ["ok"],
            },
            "a2": {
                "agent_id": "a2",
                "roles_seen": ["left", "right"],
                "observed_steps": [1, 1],
                "alive_change_observed": True,
                "terminal_outcomes": [None, 9],
                "compact_process_observations": ["ok"],
            },
        },
        "limitations": [
            "compact trajectory v2 does not store full board arrays",
            "compact trajectory v2 does not store full observations",
            "death causes, bomb ownership, and power-up pickup causes are only recorded if available from compact fields",
        ],
    }
    (md / "trajectory_events.json").write_text(json.dumps(events), encoding="utf-8")
    return md


def test_compact_trajectory_audit_passes_minimal_fixture(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _mk_match(tmp_path)
    errors, _warnings = audit_compact_trajectory()
    assert errors == []


def test_compact_trajectory_audit_fails_for_full_board_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    md = _mk_match(tmp_path)
    row = json.loads((md / "trajectory_compact_match_a.jsonl").read_text(encoding="utf-8").splitlines()[0])
    row["board"] = [[0]]
    (md / "trajectory_compact_match_a.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    errors, _warnings = audit_compact_trajectory()
    assert any("forbidden keys" in e for e in errors)

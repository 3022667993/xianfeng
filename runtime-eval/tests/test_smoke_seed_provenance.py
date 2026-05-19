import json

from runner.main import _write_round_seed_provenance


def test_write_round_seed_provenance_adds_fields_without_aggregation(tmp_path):
    round_dir = tmp_path / "round_1"
    round_dir.mkdir(parents=True)
    base = {
        "left_score": 1,
        "right_score": -1,
        "left_right_winner": "left",
    }
    for name in ["scorecard.json", "arena_result_match_a.json"]:
        (round_dir / name).write_text(json.dumps(base), encoding="utf-8")
    for name in ["metadata.json", "trajectory_summary.json", "trajectory_events.json"]:
        (round_dir / name).write_text(json.dumps({"seed_control_status": "requested_but_not_applied"}), encoding="utf-8")

    _write_round_seed_provenance(
        round_dir,
        requested_seed=1001,
        applied_seed=None,
        seed_control_error="seed_not_supported",
        seed_control_methods_attempted=["env.reset(seed=...)", "env.seed(...)"],
        seed_control_method_applied=None,
    )

    scorecard = json.loads((round_dir / "scorecard.json").read_text(encoding="utf-8"))
    assert scorecard["left_score"] == 1
    assert scorecard["right_score"] == -1
    assert scorecard["left_right_winner"] == "left"
    assert scorecard["requested_seed"] == 1001
    assert scorecard["applied_seed"] is None
    assert scorecard["seed"] is None
    assert scorecard["seed_control_status"] == "requested_but_not_applied"
    assert scorecard["seed_control_error"] == "seed_not_supported"
    assert scorecard["seed_control_methods_attempted"] == ["env.reset(seed=...)", "env.seed(...)"]
    assert scorecard["seed_control_method_applied"] is None
    assert not (round_dir / "arena_result_match_b.json").exists()
    assert not (round_dir / "trajectory_compact_match_b.jsonl").exists()

    arena_a = json.loads((round_dir / "arena_result_match_a.json").read_text(encoding="utf-8"))
    assert arena_a["requested_seed"] == 1001
    metadata = json.loads((round_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["requested_seed"] == 1001
    trajectory_summary = json.loads((round_dir / "trajectory_summary.json").read_text(encoding="utf-8"))
    assert trajectory_summary["requested_seed"] == 1001
    trajectory_events = json.loads((round_dir / "trajectory_events.json").read_text(encoding="utf-8"))
    assert trajectory_events["requested_seed"] == 1001


def test_write_round_seed_provenance_applied(tmp_path):
    round_dir = tmp_path / "round_1"
    round_dir.mkdir(parents=True)
    base = {"left_score": 1, "right_score": -1, "left_right_winner": "left"}
    for name in ["scorecard.json", "arena_result_match_a.json"]:
        (round_dir / name).write_text(json.dumps(base), encoding="utf-8")
    (round_dir / "metadata.json").write_text(json.dumps({"match_legs": "single"}), encoding="utf-8")

    _write_round_seed_provenance(
        round_dir,
        requested_seed=1001,
        applied_seed=1001,
        seed_control_status="applied",
        seed_control_methods_attempted=["env.reset(seed=...)"],
        seed_control_method_applied="env.reset(seed=...)",
    )
    scorecard = json.loads((round_dir / "scorecard.json").read_text(encoding="utf-8"))
    assert scorecard["requested_seed"] == 1001
    assert scorecard["applied_seed"] == 1001
    assert scorecard["seed"] == 1001
    assert scorecard["seed_control_status"] == "applied"
    assert scorecard["seed_control_methods_attempted"] == ["env.reset(seed=...)"]
    assert scorecard["seed_control_method_applied"] == "env.reset(seed=...)"
    assert not (round_dir / "arena_result_match_b.json").exists()
    assert not (round_dir / "trajectory_compact_match_b.jsonl").exists()
    arena_a = json.loads((round_dir / "arena_result_match_a.json").read_text(encoding="utf-8"))
    assert arena_a["applied_seed"] == 1001
    metadata = json.loads((round_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["applied_seed"] == 1001

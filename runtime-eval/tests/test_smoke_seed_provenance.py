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
    for name in ["scorecard.json", "arena_result_match_a.json", "arena_result_match_b.json"]:
        (round_dir / name).write_text(json.dumps(base), encoding="utf-8")

    _write_round_seed_provenance(round_dir, requested_seed=1001, applied_seed=None)

    scorecard = json.loads((round_dir / "scorecard.json").read_text(encoding="utf-8"))
    assert scorecard["left_score"] == 1
    assert scorecard["right_score"] == -1
    assert scorecard["left_right_winner"] == "left"
    assert scorecard["requested_seed"] == 1001
    assert scorecard["applied_seed"] is None
    assert scorecard["seed"] is None
    assert scorecard["seed_control_status"] == "requested_but_not_applied"

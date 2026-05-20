from pathlib import Path
import json

from runner.adapters.pommerman_1v1 import Pommerman1v1Adapter


def test_pommerman_run_match_smoke(tmp_path):
    adapter = Pommerman1v1Adapter()
    round_dir = tmp_path / "round_1"
    result = adapter.run_match(
        Path("starter_repos/pommerman_1v1"),
        Path("starter_repos/pommerman_1v1"),
        round_dir,
        {},
    )
    assert "winner" in result
    assert "result" in result
    assert "runtime_diagnostics" in result
    assert (round_dir / "build.log").exists()
    assert (round_dir / "test.log").exists()
    assert (round_dir / "stderr.log").exists()
    scorecard = json.loads((round_dir / "scorecard.json").read_text(encoding="utf-8"))
    assert "environment_winners" in scorecard
    assert "environment_winner_labels" in scorecard
    assert "submitted_pair_outcome" in scorecard
    assert "draw_type" in scorecard
    assert scorecard["seat_assignment"] == {
        "seat_0_submission": "left",
        "seat_1_submission": "right",
        "seat_2_submission": "dummy2",
        "seat_3_submission": "dummy3",
    }
    assert scorecard["background_agents"] == ["dummy2", "dummy3"]
    compact_rows = [
        json.loads(line)
        for line in (round_dir / "trajectory_compact_match_a.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert compact_rows
    assert compact_rows[0]["actions"]["seat_2"] == 5
    assert compact_rows[0]["actions"]["seat_3"] == 5
    if len(compact_rows) > 1:
        assert compact_rows[1]["actions"]["seat_2"] == 0
        assert compact_rows[1]["actions"]["seat_3"] == 0

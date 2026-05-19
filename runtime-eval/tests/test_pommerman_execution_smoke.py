import json
from pathlib import Path

from runner.core.config import load_yaml
from runner.main import _execution_smoke_model_entries, _execution_smoke_round_robin_round
from scripts.audit_pommerman_6model_execution_smoke import audit_execution_smoke


def test_execution_smoke_config_exists_and_loads():
    cfg = load_yaml("configs/tournaments/pommerman_gptv16_a00_6model_execution_smoke.yaml")
    assert cfg["name"] == "pommerman_gptv16_a00_6model_execution_smoke"
    assert cfg["num_models"] == 6
    assert cfg["num_rounds"] == 1
    assert cfg["matches_per_round"] == 3
    assert cfg["execution_smoke"] is True


def test_execution_smoke_round_is_perfect_matching():
    models_cfg = load_yaml("configs/models/openclaw_relay_6model_gptv16.yaml")
    entries = _execution_smoke_model_entries(models_cfg["models"])
    pairs = _execution_smoke_round_robin_round(entries)
    assert len(pairs) == 3
    seen = []
    for left, right in pairs:
        seen.extend([left["agent_id"], right["agent_id"]])
    assert len(set(seen)) == 6
    assert all(seen.count(x) == 1 for x in set(seen))


def test_execution_smoke_round_supports_even_n():
    entries = _execution_smoke_model_entries(
        [
            {"id": f"m{i}", "agent_id": f"a{i}", "executor": "openclaw-minimal"}
            for i in range(1, 9)
        ]
    )
    pairs = _execution_smoke_round_robin_round(entries)
    assert len(pairs) == 4
    seen = []
    for left, right in pairs:
        seen.extend([left["agent_id"], right["agent_id"]])
    assert sorted(seen) == [f"a{i}" for i in range(1, 9)]


def _mk_match(round_dir: Path, idx: int, left: str, right: str):
    match_dir = round_dir / f"match_{idx}"
    match_dir.mkdir(parents=True, exist_ok=True)
    for name in ["metadata.json", "scorecard.json", "arena_result_match_a.json"]:
        (match_dir / name).write_text("{}", encoding="utf-8")
    return {
        "match_id": f"match_{idx}",
        "match_idx": idx,
        "left_agent_id": left,
        "right_agent_id": right,
        "left_submission_path": f"workspace/submissions/pommerman_gptv16_a00_6model_execution_smoke/{left}/submission_1",
        "right_submission_path": f"workspace/submissions/pommerman_gptv16_a00_6model_execution_smoke/{right}/submission_1",
        "requested_seed": 1000 + idx,
        "applied_seed": None,
        "seed": None,
        "seed_control_status": "requested_but_not_applied",
        "seat_assignment": {"left": left, "right": right, "background_agents": ["dummy2", "dummy3"]},
        "background_agents": ["dummy2", "dummy3"],
        "metadata_path": str(match_dir / "metadata.json"),
        "scorecard_path": str(match_dir / "scorecard.json"),
        "arena_result_match_a_path": str(match_dir / "arena_result_match_a.json"),
    }


def _mk_workspace(base: Path, agents: list[str]):
    t = "pommerman_gptv16_a00_6model_execution_smoke"
    for root in ["codebases", "submissions", "posts"]:
        for a in agents:
            p = base / "workspace" / root / t / a
            p.mkdir(parents=True, exist_ok=True)


def test_audit_fails_if_left_right_dirs_exist(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    t = "pommerman_gptv16_a00_6model_execution_smoke"
    agents = [f"a{i}" for i in range(1, 7)]
    _mk_workspace(tmp_path, agents)
    for root in ["codebases", "submissions", "posts"]:
        (tmp_path / "workspace" / root / t / "left").mkdir(parents=True, exist_ok=True)

    round_dir = tmp_path / "logs" / "round_1"
    matches = [
        _mk_match(round_dir, 1, "a1", "a2"),
        _mk_match(round_dir, 2, "a3", "a4"),
        _mk_match(round_dir, 3, "a5", "a6"),
    ]
    (round_dir / "round_manifest.json").write_text(
        json.dumps({
            "round_idx": 1,
            "matches_per_round": 3,
            "scorecard_policy": "raw_per_match_scorecard; pair-level aggregation is post-analysis",
            "matches": matches,
        }),
        encoding="utf-8",
    )

    errors, _warnings = audit_execution_smoke(t)
    assert any("persistent left/ dir" in e for e in errors)


def test_audit_fails_if_fewer_than_three_matches(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    t = "pommerman_gptv16_a00_6model_execution_smoke"
    agents = [f"a{i}" for i in range(1, 7)]
    _mk_workspace(tmp_path, agents)

    round_dir = tmp_path / "logs" / "round_1"
    matches = [_mk_match(round_dir, 1, "a1", "a2"), _mk_match(round_dir, 2, "a3", "a4")]
    (round_dir / "round_manifest.json").write_text(
        json.dumps({
            "round_idx": 1,
            "matches_per_round": 3,
            "scorecard_policy": "raw_per_match_scorecard; pair-level aggregation is post-analysis",
            "matches": matches,
        }),
        encoding="utf-8",
    )

    errors, _warnings = audit_execution_smoke(t)
    assert any("exactly three matches" in e for e in errors)


def test_audit_passes_for_generated_execution_smoke_shape(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    t = "pommerman_gptv16_a00_6model_execution_smoke"
    agents = [f"a{i}" for i in range(1, 7)]
    _mk_workspace(tmp_path, agents)

    round_dir = tmp_path / "logs" / "round_1"
    matches = [
        _mk_match(round_dir, 1, "a1", "a2"),
        _mk_match(round_dir, 2, "a3", "a4"),
        _mk_match(round_dir, 3, "a5", "a6"),
    ]
    (round_dir / "round_manifest.json").write_text(
        json.dumps({
            "round_idx": 1,
            "matches_per_round": 3,
            "scorecard_policy": "raw_per_match_scorecard; pair-level aggregation is post-analysis",
            "matches": matches,
        }),
        encoding="utf-8",
    )

    errors, _warnings = audit_execution_smoke(t)
    assert errors == []

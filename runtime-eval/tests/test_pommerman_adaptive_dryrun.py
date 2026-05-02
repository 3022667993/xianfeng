import json
from pathlib import Path

from runner.core.config import load_yaml
from runner.core.schedule import build_two_cycle_schedule
from scripts.audit_pommerman_10round_adaptive_dryrun import audit_adaptive_dryrun


def test_adaptive_dryrun_config_loads():
    cfg = load_yaml("configs/tournaments/pommerman_gptv16_a00_6model_adaptive_dryrun.yaml")
    assert cfg["adaptive_dryrun"] is True
    assert cfg["num_rounds"] == 10
    assert cfg["matches_per_round"] == 3


def test_generated_6agent_schedule_has_30_matches_and_swapped_cycles():
    s = build_two_cycle_schedule([f"a{i}" for i in range(1, 7)])
    assert s["total_matches"] == 30
    assert s["cycle_1_pair_order"] == s["cycle_2_pair_order"]
    for r in s["rounds"]:
        seen = []
        for m in r["matches"]:
            seen.extend([m["left_agent"], m["right_agent"]])
        assert len(set(seen)) == 6
        assert all(seen.count(x) == 1 for x in set(seen))


def _mk_match(round_dir: Path, idx: int, left: str, right: str, pair_id: str, req_seed: int):
    md = round_dir / f"match_{idx}"
    md.mkdir(parents=True, exist_ok=True)
    meta = {
        "adaptive_dryrun": True,
        "low_cost_revision": True,
        "revision_executor": "dryrun-noop",
    }
    (md / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    (md / "scorecard.json").write_text("{}", encoding="utf-8")
    (md / "arena_result_match_a.json").write_text("{}", encoding="utf-8")
    (md / "arena_result_match_b.json").write_text("{}", encoding="utf-8")
    return {
        "match_id": f"match_{idx}",
        "match_idx": idx,
        "pair_id": pair_id,
        "left_agent_id": left,
        "right_agent_id": right,
        "left_submission_path": f"workspace/submissions/pommerman_gptv16_a00_6model_adaptive_dryrun/{left}/submission_1",
        "right_submission_path": f"workspace/submissions/pommerman_gptv16_a00_6model_adaptive_dryrun/{right}/submission_1",
        "seat_assignment": {"left": left, "right": right, "background_agents": ["dummy2", "dummy3"]},
        "background_agents": ["dummy2", "dummy3"],
        "requested_seed": req_seed,
        "applied_seed": None,
        "seed": None,
        "seed_control_status": "requested_but_not_applied",
        "metadata_path": str(md / "metadata.json"),
        "scorecard_path": str(md / "scorecard.json"),
        "arena_result_match_a_path": str(md / "arena_result_match_a.json"),
        "arena_result_match_b_path": str(md / "arena_result_match_b.json"),
    }


def _mk_workspace(base: Path, agents: list[str]):
    t = "pommerman_gptv16_a00_6model_adaptive_dryrun"
    for root in ["codebases", "submissions", "posts"]:
        for a in agents:
            for r in range(1, 11):
                suffix = {
                    "codebases": f"codebase_play_{r}",
                    "submissions": f"submission_{r}",
                    "posts": f"codebase_post_{r}",
                }[root]
                p = base / "workspace" / root / t / a / suffix
                p.mkdir(parents=True, exist_ok=True)
                if root in {"codebases", "posts"}:
                    sm = p / "submission"
                    sm.mkdir(parents=True, exist_ok=True)
                    (sm / "main.py").write_text("AGGRESSION = 0\n", encoding="utf-8")


def _write_round_manifest(base: Path, round_idx: int, matches: list[dict]):
    rd = base / "logs" / f"round_{round_idx}"
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "round_manifest.json").write_text(
        json.dumps(
            {
                "round_idx": round_idx,
                "matches_per_round": len(matches),
                "cycle": 1 if round_idx <= 5 else 2,
                "scorecard_policy": "raw_per_match_scorecard; pair-level aggregation is post-analysis",
                "matches": matches,
            }
        ),
        encoding="utf-8",
    )


def _mk_full_logs(base: Path, dup: bool = False, fewer: bool = False):
    agents = [f"a{i}" for i in range(1, 7)]
    _mk_workspace(base, agents)
    for r in range(1, 11):
        m1 = _mk_match(base / "logs" / f"round_{r}", 1, "a1", "a2", "a1__vs__a2", 11)
        m2 = _mk_match(base / "logs" / f"round_{r}", 2, "a3", "a4", "a3__vs__a4", 22)
        m3 = _mk_match(base / "logs" / f"round_{r}", 3, "a5", "a6", "a5__vs__a6", 33)
        matches = [m1, m2, m3]
        if dup:
            matches[2]["left_agent_id"] = "a1"
        if fewer:
            matches = matches[:2]
        _write_round_manifest(base, r, matches)


def test_audit_fails_if_round_has_fewer_than_3_matches(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _mk_full_logs(tmp_path, fewer=True)
    errors, _warnings = audit_adaptive_dryrun("pommerman_gptv16_a00_6model_adaptive_dryrun")
    assert any("exactly 3 matches" in e for e in errors)


def test_audit_fails_if_agent_appears_twice(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _mk_full_logs(tmp_path, dup=True)
    errors, _warnings = audit_adaptive_dryrun("pommerman_gptv16_a00_6model_adaptive_dryrun")
    assert any("not a perfect matching" in e for e in errors)


def test_audit_fails_if_left_right_persistent_dirs_exist(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _mk_full_logs(tmp_path)
    t = "pommerman_gptv16_a00_6model_adaptive_dryrun"
    for root in ["codebases", "submissions", "posts"]:
        (tmp_path / "workspace" / root / t / "left").mkdir(parents=True, exist_ok=True)
    errors, _warnings = audit_adaptive_dryrun(t)
    assert any("persistent left/" in e for e in errors)


def test_dryrun_revision_metadata_marks_no_expensive_executor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _mk_full_logs(tmp_path)
    errors, _warnings = audit_adaptive_dryrun("pommerman_gptv16_a00_6model_adaptive_dryrun")
    assert errors == []

import json
from pathlib import Path

from runner.core.config import load_yaml
from scripts.audit_pommerman_openclaw_adaptive_2round_smoke import (
    audit_openclaw_adaptive_2round_smoke,
)


def test_openclaw_adaptive_2round_config_loads():
    cfg = load_yaml("configs/tournaments/pommerman_gptv16_a00_openclaw_adaptive_2round_smoke.yaml")
    assert cfg["openclaw_adaptive_smoke"] is True
    assert cfg["num_rounds"] == 2
    assert cfg["matches_per_round"] == 3
    assert cfg["revision_rounds"] == [1]
    assert cfg["revision_subset_size"] == 6
    assert cfg["require_all_agents_revised"] is True


def _mk_round_manifest(tmp_path: Path, round_idx: int, tournament: str):
    rd = tmp_path / "logs" / f"round_{round_idx}"
    rd.mkdir(parents=True, exist_ok=True)
    pairs = [("a1", "a2"), ("a3", "a4"), ("a5", "a6")] if round_idx == 1 else [("a1", "a6"), ("a2", "a5"), ("a3", "a4")]
    matches = []
    for i, (l, r) in enumerate(pairs, start=1):
        md = rd / f"match_{i}"
        md.mkdir(parents=True, exist_ok=True)
        for n in ["metadata.json", "scorecard.json", "arena_result_match_a.json", "arena_result_match_b.json"]:
            (md / n).write_text("{}", encoding="utf-8")
        matches.append(
            {
                "match_id": f"match_{i}",
                "match_idx": i,
                "pair_id": "__vs__".join(sorted([l, r])),
                "left_agent_id": l,
                "right_agent_id": r,
                "left_submission_path": f"workspace/submissions/{tournament}/{l}/submission_{round_idx}",
                "right_submission_path": f"workspace/submissions/{tournament}/{r}/submission_{round_idx}",
                "seat_assignment": {"left": l, "right": r, "background_agents": ["dummy2", "dummy3"]},
                "background_agents": ["dummy2", "dummy3"],
                "requested_seed": 1000 + i,
                "applied_seed": None,
                "seed": None,
                "seed_control_status": "requested_but_not_applied",
                "metadata_path": str(md / "metadata.json"),
                "scorecard_path": str(md / "scorecard.json"),
                "arena_result_match_a_path": str(md / "arena_result_match_a.json"),
                "arena_result_match_b_path": str(md / "arena_result_match_b.json"),
            }
        )
    (rd / "round_manifest.json").write_text(
        json.dumps(
            {
                "round_idx": round_idx,
                "matches_per_round": 3,
                "scorecard_policy": "raw_per_match_scorecard; pair-level aggregation is post-analysis",
                "matches": matches,
            }
        ),
        encoding="utf-8",
    )


def _mk_fixture(tmp_path: Path, tournament: str = "pommerman_gptv16_a00_openclaw_adaptive_2round_smoke"):
    agents = [f"a{i}" for i in range(1, 7)]
    for root in ["codebases", "submissions", "posts"]:
        for a in agents:
            for idx in [1, 2]:
                p = tmp_path / "workspace" / root / tournament / a / f"{'codebase_play' if root=='codebases' else 'submission' if root=='submissions' else 'codebase_post'}_{idx}"
                p.mkdir(parents=True, exist_ok=True)
    _mk_round_manifest(tmp_path, 1, tournament)
    _mk_round_manifest(tmp_path, 2, tournament)
    rev_agents = []
    for a in agents:
        rev_agents.append(
            {
                "agent_id": a,
                "provider_model": f"relay/{a}",
                "executor": "openclaw-minimal",
                "revision_attempted": True,
                "revision_executor": "openclaw-minimal",
                "revision_status": "ok",
                "revision_ok": True,
                "codebase_play_path": f"workspace/codebases/{tournament}/{a}/codebase_play_1",
                "submission_path": f"workspace/submissions/{tournament}/{a}/submission_1",
                "codebase_post_path": f"workspace/posts/{tournament}/{a}/codebase_post_1",
                "changed_files": [],
                "diff_path": "",
                "revision_log_path": "",
                "failure_reason": None,
                "budget_guard_reason": None,
                "openclaw_invoked": True,
                "fallback_used": False,
                "requested_provider_model": f"relay/{a}",
                "actual_provider": "relay",
                "actual_model": a,
                "provider_route_status": "matched",
                "openclaw_default_missing_placeholders": [],
                "audit_warnings": [],
                "audit_errors": [],
            }
        )
    (tmp_path / "logs" / "round_1" / "revision_manifest.json").write_text(
        json.dumps({"agents": rev_agents}),
        encoding="utf-8",
    )
    prop_agents = []
    for a in agents:
        prop_agents.append(
            {
                "agent_id": a,
                "source_post_path": f"workspace/posts/{tournament}/{a}/codebase_post_1",
                "target_play_path": f"workspace/codebases/{tournament}/{a}/codebase_play_2",
                "propagated": True,
                "propagation_ok": True,
                "source_revision_ok": True,
                "source_provider_route_status": "matched",
                "file_count": 0,
                "files": [],
            }
        )
    (tmp_path / "logs" / "round_2" / "propagation_manifest.json").write_text(
        json.dumps({"round_idx": 2, "agents": prop_agents}),
        encoding="utf-8",
    )
    return tournament


def test_adaptive_2round_audit_fixture_passes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tournament = _mk_fixture(tmp_path)
    errors, _warnings = audit_openclaw_adaptive_2round_smoke(tournament)
    assert errors == []


def test_adaptive_2round_audit_fails_without_propagation_manifest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tournament = _mk_fixture(tmp_path)
    (tmp_path / "logs" / "round_2" / "propagation_manifest.json").unlink()
    errors, _warnings = audit_openclaw_adaptive_2round_smoke(tournament)
    assert any("missing logs/round_2/propagation_manifest.json" in e for e in errors)


def test_adaptive_2round_audit_fails_on_route_mismatch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tournament = _mk_fixture(tmp_path)
    rp = tmp_path / "logs" / "round_1" / "revision_manifest.json"
    rev = json.loads(rp.read_text(encoding="utf-8"))
    rev["agents"][0]["provider_route_status"] = "mismatch"
    rp.write_text(json.dumps(rev), encoding="utf-8")
    errors, _warnings = audit_openclaw_adaptive_2round_smoke(tournament)
    assert any("provider_route_status=matched" in e for e in errors)


def test_adaptive_2round_audit_fails_on_route_unknown(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tournament = _mk_fixture(tmp_path)
    rp = tmp_path / "logs" / "round_1" / "revision_manifest.json"
    rev = json.loads(rp.read_text(encoding="utf-8"))
    rev["agents"][0]["provider_route_status"] = "unknown"
    rp.write_text(json.dumps(rev), encoding="utf-8")
    errors, _warnings = audit_openclaw_adaptive_2round_smoke(tournament)
    assert any("provider_route_status=matched" in e for e in errors)


def test_adaptive_2round_audit_fails_on_fallback_used(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tournament = _mk_fixture(tmp_path)
    rp = tmp_path / "logs" / "round_1" / "revision_manifest.json"
    rev = json.loads(rp.read_text(encoding="utf-8"))
    rev["agents"][0]["fallback_used"] = True
    rp.write_text(json.dumps(rev), encoding="utf-8")
    errors, _warnings = audit_openclaw_adaptive_2round_smoke(tournament)
    assert any("fallback_used=false" in e for e in errors)


def test_adaptive_2round_audit_fails_if_agent_skipped(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tournament = _mk_fixture(tmp_path)
    rp = tmp_path / "logs" / "round_1" / "revision_manifest.json"
    rev = json.loads(rp.read_text(encoding="utf-8"))
    rev["agents"][0]["revision_attempted"] = False
    rev["agents"][0]["revision_status"] = "skipped_by_budget_guard"
    rp.write_text(json.dumps(rev), encoding="utf-8")
    errors, _warnings = audit_openclaw_adaptive_2round_smoke(tournament)
    assert any("revision_attempted=true" in e for e in errors)


def test_adaptive_2round_audit_fails_if_play2_under_left_right(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tournament = _mk_fixture(tmp_path)
    bad = tmp_path / "workspace" / "codebases" / tournament / "left"
    bad.mkdir(parents=True, exist_ok=True)
    errors, _warnings = audit_openclaw_adaptive_2round_smoke(tournament)
    assert any("persistent left/" in e for e in errors)

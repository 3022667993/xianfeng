import json
from pathlib import Path

from runner.core.config import load_yaml
from scripts.audit_pommerman_openclaw_revision_smoke import audit_openclaw_revision_smoke


def test_openclaw_revision_smoke_all_agents_config_loads():
    cfg = load_yaml("configs/tournaments/pommerman_gptv16_a00_openclaw_revision_smoke_all_agents.yaml")
    assert cfg["openclaw_revision_smoke"] is True
    assert cfg["low_budget_revision"] is True
    assert cfg["revision_executor"] == "openclaw-minimal"
    assert cfg["revision_subset_size"] == 6
    assert cfg["require_all_agents_revised"] is True
    assert cfg["num_rounds"] == 1
    assert cfg["matches_per_round"] == 3


def _mk_fixture(tmp_path: Path, tournament: str = "pommerman_gptv16_a00_openclaw_revision_smoke_all_agents"):
    agents = [f"a{i}" for i in range(1, 7)]
    for root in ["codebases", "submissions", "posts"]:
        for a in agents:
            (tmp_path / "workspace" / root / tournament / a).mkdir(parents=True, exist_ok=True)

    round_dir = tmp_path / "logs" / "round_1"
    round_dir.mkdir(parents=True, exist_ok=True)
    matches = []
    for idx, (l, r) in enumerate([("a1", "a2"), ("a3", "a4"), ("a5", "a6")], start=1):
        md = round_dir / f"match_{idx}"
        md.mkdir(parents=True, exist_ok=True)
        for name in ["metadata.json", "scorecard.json", "arena_result_match_a.json", "arena_result_match_b.json"]:
            (md / name).write_text("{}", encoding="utf-8")
        matches.append(
            {
                "match_id": f"match_{idx}",
                "match_idx": idx,
                "pair_id": "__vs__".join(sorted([l, r])),
                "left_agent_id": l,
                "right_agent_id": r,
                "left_submission_path": f"workspace/submissions/{tournament}/{l}/submission_1",
                "right_submission_path": f"workspace/submissions/{tournament}/{r}/submission_1",
                "seat_assignment": {"left": l, "right": r, "background_agents": ["dummy2", "dummy3"]},
                "background_agents": ["dummy2", "dummy3"],
                "requested_seed": 1000 + idx,
                "applied_seed": None,
                "seed": None,
                "seed_control_status": "requested_but_not_applied",
                "metadata_path": str(md / "metadata.json"),
                "scorecard_path": str(md / "scorecard.json"),
                "arena_result_match_a_path": str(md / "arena_result_match_a.json"),
                "arena_result_match_b_path": str(md / "arena_result_match_b.json"),
            }
        )
    (round_dir / "round_manifest.json").write_text(
        json.dumps(
            {
                "round_idx": 1,
                "matches_per_round": 3,
                "scorecard_policy": "raw_per_match_scorecard; pair-level aggregation is post-analysis",
                "matches": matches,
            }
        ),
        encoding="utf-8",
    )
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
    (round_dir / "revision_manifest.json").write_text(json.dumps({"agents": rev_agents}), encoding="utf-8")
    return round_dir


def test_all_agents_audit_fixture_passes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _mk_fixture(tmp_path)
    errors, _warnings = audit_openclaw_revision_smoke(
        "pommerman_gptv16_a00_openclaw_revision_smoke_all_agents",
        require_all_agents=True,
    )
    assert errors == []


def test_all_agents_audit_fails_if_any_skipped(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rd = _mk_fixture(tmp_path)
    rev = json.loads((rd / "revision_manifest.json").read_text(encoding="utf-8"))
    rev["agents"][0]["revision_attempted"] = False
    rev["agents"][0]["revision_status"] = "skipped_by_budget_guard"
    rev["agents"][0]["revision_ok"] = False
    rev["agents"][0]["openclaw_invoked"] = False
    rev["agents"][0]["budget_guard_reason"] = "low_budget_revision_subset"
    (rd / "revision_manifest.json").write_text(json.dumps(rev), encoding="utf-8")
    errors, _warnings = audit_openclaw_revision_smoke(
        "pommerman_gptv16_a00_openclaw_revision_smoke_all_agents",
        require_all_agents=True,
    )
    assert any("all agents must be revision_attempted=true" in e for e in errors)


def test_all_agents_audit_fails_on_route_mismatch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rd = _mk_fixture(tmp_path)
    rev = json.loads((rd / "revision_manifest.json").read_text(encoding="utf-8"))
    rev["agents"][0]["provider_route_status"] = "mismatch"
    (rd / "revision_manifest.json").write_text(json.dumps(rev), encoding="utf-8")
    errors, _warnings = audit_openclaw_revision_smoke(
        "pommerman_gptv16_a00_openclaw_revision_smoke_all_agents",
        require_all_agents=True,
    )
    assert any("provider route mismatch" in e or "provider_route_status=matched" in e for e in errors)


def test_all_agents_audit_fails_on_route_unknown(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rd = _mk_fixture(tmp_path)
    rev = json.loads((rd / "revision_manifest.json").read_text(encoding="utf-8"))
    rev["agents"][0]["provider_route_status"] = "unknown"
    (rd / "revision_manifest.json").write_text(json.dumps(rev), encoding="utf-8")
    errors, _warnings = audit_openclaw_revision_smoke(
        "pommerman_gptv16_a00_openclaw_revision_smoke_all_agents",
        require_all_agents=True,
    )
    assert any("provider route unknown" in e or "provider_route_status=matched" in e for e in errors)


def test_all_agents_audit_fails_on_fallback_used(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rd = _mk_fixture(tmp_path)
    rev = json.loads((rd / "revision_manifest.json").read_text(encoding="utf-8"))
    rev["agents"][0]["fallback_used"] = True
    (rd / "revision_manifest.json").write_text(json.dumps(rev), encoding="utf-8")
    errors, _warnings = audit_openclaw_revision_smoke(
        "pommerman_gptv16_a00_openclaw_revision_smoke_all_agents",
        require_all_agents=True,
    )
    assert any("fallback_used=false" in e for e in errors)


def test_all_agents_audit_fails_if_revision_entries_below_six(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rd = _mk_fixture(tmp_path)
    rev = json.loads((rd / "revision_manifest.json").read_text(encoding="utf-8"))
    rev["agents"] = rev["agents"][:5]
    (rd / "revision_manifest.json").write_text(json.dumps(rev), encoding="utf-8")
    errors, _warnings = audit_openclaw_revision_smoke(
        "pommerman_gptv16_a00_openclaw_revision_smoke_all_agents",
        require_all_agents=True,
    )
    assert any("include 6 agents" in e for e in errors)

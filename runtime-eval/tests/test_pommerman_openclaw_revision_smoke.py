import json
from pathlib import Path

from runner.core.config import load_yaml
from runner.main import _execution_smoke_model_entries, _execution_smoke_round_robin_round
from runner.core.openclaw_minimal import _audit_openclaw_response
from scripts.audit_pommerman_openclaw_revision_smoke import audit_openclaw_revision_smoke


def test_openclaw_revision_smoke_config_loads():
    cfg = load_yaml("configs/tournaments/pommerman_gptv16_a00_openclaw_revision_smoke.yaml")
    assert cfg["openclaw_revision_smoke"] is True
    assert cfg["low_budget_revision"] is True
    assert cfg["revision_executor"] == "openclaw-minimal"
    assert cfg["num_rounds"] == 1
    assert cfg["matches_per_round"] == 3


def test_openclaw_revision_smoke_round_is_1x3_perfect_matching():
    models_cfg = load_yaml("configs/models/openclaw_relay_6model_deepseek_glm.yaml")
    entries = _execution_smoke_model_entries(models_cfg["models"])
    pairs = _execution_smoke_round_robin_round(entries)
    assert len(pairs) == 3
    seen = []
    for left, right in pairs:
        seen.extend([left["agent_id"], right["agent_id"]])
    assert len(set(seen)) == 6
    assert all(seen.count(x) == 1 for x in set(seen))


def _mk_match(round_dir: Path, idx: int, left: str, right: str):
    md = round_dir / f"match_{idx}"
    md.mkdir(parents=True, exist_ok=True)
    for name in ["metadata.json", "scorecard.json", "arena_result_match_a.json", "arena_result_match_b.json"]:
        (md / name).write_text("{}", encoding="utf-8")
    return {
        "match_id": f"match_{idx}",
        "match_idx": idx,
        "pair_id": "__vs__".join(sorted([left, right])),
        "left_agent_id": left,
        "right_agent_id": right,
        "left_submission_path": f"workspace/submissions/pommerman_gptv16_a00_openclaw_revision_smoke/{left}/submission_1",
        "right_submission_path": f"workspace/submissions/pommerman_gptv16_a00_openclaw_revision_smoke/{right}/submission_1",
        "seat_assignment": {"left": left, "right": right, "background_agents": ["dummy2", "dummy3"]},
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


def _mk_workspace(base: Path, agents: list[str]):
    t = "pommerman_gptv16_a00_openclaw_revision_smoke"
    for root in ["codebases", "submissions", "posts"]:
        for a in agents:
            p = base / "workspace" / root / t / a
            p.mkdir(parents=True, exist_ok=True)


def _good_revision_manifest(agents: list[str]) -> dict:
    entries = []
    for i, a in enumerate(agents):
        attempted = i == 0
        entries.append(
            {
                "agent_id": a,
                "provider_model": f"provider/{a}",
                "executor": "openclaw-minimal",
                "revision_attempted": attempted,
                "revision_executor": "openclaw-minimal" if attempted else "skipped_by_budget_guard",
                "revision_status": "ok" if attempted else "skipped_by_budget_guard",
                "revision_ok": True if attempted else False,
                "codebase_play_path": f"workspace/codebases/pommerman_gptv16_a00_openclaw_revision_smoke/{a}/codebase_play_1",
                "submission_path": f"workspace/submissions/pommerman_gptv16_a00_openclaw_revision_smoke/{a}/submission_1",
                "codebase_post_path": f"workspace/posts/pommerman_gptv16_a00_openclaw_revision_smoke/{a}/codebase_post_1",
                "changed_files": [],
                "diff_path": "logs/round_1/match_1/left.diff.patch",
                "revision_log_path": "workspace/posts/x/notes/revision_log.md",
                "failure_reason": None,
                "budget_guard_reason": None if attempted else "low_budget_revision_subset",
                "openclaw_invoked": attempted,
                "fallback_used": False,
                "requested_provider_model": "bailian/deepseek-v4-flash" if attempted else f"provider/{a}",
                "actual_provider": "bailian" if attempted else None,
                "actual_model": "deepseek-v4-flash" if attempted else None,
                "provider_route_status": "matched" if attempted else "unknown",
                "openclaw_default_missing_placeholders": ["SOUL.md", "BOOTSTRAP.md"] if attempted else [],
                "audit_warnings": [],
                "audit_errors": [],
            }
        )
    return {"agents": entries}


def _setup_fixture(tmp_path: Path):
    agents = [f"a{i}" for i in range(1, 7)]
    _mk_workspace(tmp_path, agents)
    round_dir = tmp_path / "logs" / "round_1"
    matches = [
        _mk_match(round_dir, 1, "a1", "a2"),
        _mk_match(round_dir, 2, "a3", "a4"),
        _mk_match(round_dir, 3, "a5", "a6"),
    ]
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
    (round_dir / "revision_manifest.json").write_text(
        json.dumps(_good_revision_manifest(agents)),
        encoding="utf-8",
    )
    return agents, round_dir


def test_revision_manifest_validation_passes_with_one_openclaw_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _setup_fixture(tmp_path)
    errors, _warnings = audit_openclaw_revision_smoke("pommerman_gptv16_a00_openclaw_revision_smoke")
    assert errors == []


def test_audit_fails_if_no_openclaw_invoked_true(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    agents, rd = _setup_fixture(tmp_path)
    rev = _good_revision_manifest(agents)
    for a in rev["agents"]:
        a["revision_attempted"] = False
        a["revision_status"] = "skipped_by_budget_guard"
        a["revision_executor"] = "skipped_by_budget_guard"
        a["revision_ok"] = False
        a["openclaw_invoked"] = False
        a["budget_guard_reason"] = "low_budget_revision_subset"
    (rd / "revision_manifest.json").write_text(json.dumps(rev), encoding="utf-8")
    errors, _warnings = audit_openclaw_revision_smoke("pommerman_gptv16_a00_openclaw_revision_smoke")
    assert any("at least one attempted" in e for e in errors)


def test_audit_fails_if_attempted_agent_uses_fallback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    agents, rd = _setup_fixture(tmp_path)
    rev = _good_revision_manifest(agents)
    rev["agents"][0]["fallback_used"] = True
    (rd / "revision_manifest.json").write_text(json.dumps(rev), encoding="utf-8")
    errors, _warnings = audit_openclaw_revision_smoke("pommerman_gptv16_a00_openclaw_revision_smoke")
    assert any("fallback_used=false" in e for e in errors)


def test_audit_fails_if_selected_agent_uses_dryrun_or_rule(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    agents, rd = _setup_fixture(tmp_path)
    rev = _good_revision_manifest(agents)
    rev["agents"][0]["revision_executor"] = "dryrun-noop"
    (rd / "revision_manifest.json").write_text(json.dumps(rev), encoding="utf-8")
    errors, _warnings = audit_openclaw_revision_smoke("pommerman_gptv16_a00_openclaw_revision_smoke")
    assert any("cannot use dryrun-noop/rule-minimal" in e for e in errors)


def test_audit_fails_on_provider_route_mismatch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    agents, rd = _setup_fixture(tmp_path)
    rev = _good_revision_manifest(agents)
    rev["agents"][0]["provider_route_status"] = "mismatch"
    (rd / "revision_manifest.json").write_text(json.dumps(rev), encoding="utf-8")
    errors, _warnings = audit_openclaw_revision_smoke("pommerman_gptv16_a00_openclaw_revision_smoke")
    assert any("provider route mismatch" in e for e in errors)


def test_audit_allows_provider_route_unknown_with_warning(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    agents, rd = _setup_fixture(tmp_path)
    rev = _good_revision_manifest(agents)
    rev["agents"][0]["provider_route_status"] = "unknown"
    (rd / "revision_manifest.json").write_text(json.dumps(rev), encoding="utf-8")
    errors, warnings = audit_openclaw_revision_smoke("pommerman_gptv16_a00_openclaw_revision_smoke")
    assert errors == []
    assert any("provider route unknown" in w for w in warnings)


def test_placeholder_missing_soul_bootstrap_is_not_fatal(tmp_path):
    response = {
        "meta": {
            "systemPromptReport": {
                "injectedWorkspaceFiles": [
                    {"name": "SOUL.md", "missing": True, "path": str(tmp_path / "SOUL.md"), "injectedChars": 0},
                    {"name": "BOOTSTRAP.md", "missing": True, "path": str(tmp_path / "BOOTSTRAP.md"), "injectedChars": 0},
                ],
                "tools": {"entries": []},
                "skills": {"promptChars": 0},
            }
        }
    }
    audit = _audit_openclaw_response(response, minimal_workspace=tmp_path)
    assert audit["forbiddenInjectedWorkspaceFiles"] == []
    assert sorted(audit["openclawDefaultMissingPlaceholders"]) == ["BOOTSTRAP.md", "SOUL.md"]


def test_real_soul_file_present_is_fatal_in_audit_payload(tmp_path):
    (tmp_path / "SOUL.md").write_text("x", encoding="utf-8")
    response = {"meta": {"systemPromptReport": {"injectedWorkspaceFiles": [], "tools": {"entries": []}, "skills": {"promptChars": 0}}}}
    audit = _audit_openclaw_response(response, minimal_workspace=tmp_path)
    assert any(p.endswith("/SOUL.md") for p in audit["realForbiddenWorkspaceFiles"])


def test_other_forbidden_injected_file_is_fatal(tmp_path):
    response = {
        "meta": {
            "systemPromptReport": {
                "injectedWorkspaceFiles": [
                    {"name": "MEMORY.md", "missing": False, "path": str(tmp_path / "MEMORY.md"), "injectedChars": 10}
                ],
                "tools": {"entries": []},
                "skills": {"promptChars": 0},
            }
        }
    }
    audit = _audit_openclaw_response(response, minimal_workspace=tmp_path)
    assert len(audit["forbiddenInjectedWorkspaceFiles"]) == 1

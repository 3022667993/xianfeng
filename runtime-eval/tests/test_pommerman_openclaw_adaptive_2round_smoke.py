import json
from pathlib import Path

from runner.core.config import load_yaml
from scripts.audit_pommerman_openclaw_adaptive_2round_smoke import (
    audit_openclaw_adaptive_2round_smoke,
)
from scripts.audit_pommerman_process_feedback import audit_process_feedback


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


def test_process_feedback_fixture_passes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tournament = _mk_fixture(tmp_path)
    for rd in [tmp_path / "logs" / "round_1", tmp_path / "logs" / "round_2"]:
        for match_dir in sorted(p for p in rd.glob("match_*") if p.is_dir()):
            pair = [("a1", "a2"), ("a3", "a4"), ("a5", "a6")][int(match_dir.name.split("_")[-1]) - 1]
            left_id, right_id = pair
            (match_dir / "metadata.json").write_text(
                json.dumps({"left_agent_id": left_id, "right_agent_id": right_id}),
                encoding="utf-8",
            )
            summary = {
                "schema_version": "pommerman_process_feedback_v1",
                "round_idx": int(rd.name.split("_")[-1]),
                "match_idx": int(match_dir.name.split("_")[-1]),
                "match_id": match_dir.name,
                "pair_id": f"{left_id}__vs__{right_id}",
                "left_agent_id": left_id,
                "right_agent_id": right_id,
                "background_agents": ["dummy2", "dummy3"],
                "scorecard_policy": "raw_per_match_scorecard; pair-level aggregation is post-analysis",
                "seed": None,
                "requested_seed": None,
                "applied_seed": None,
                "seed_control_status": "requested_but_not_applied",
                "legs": [],
                "seat_swap_summary": {},
                "agent_summaries": {},
            }
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
                        "terminal_step": None,
                        "winner_seats": None,
                        "first_reward_change_step": None,
                        "alive_change_steps": [],
                        "final_reward": [0, 0, 0, 0],
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
            for agent in [left_id, right_id]:
                payload = {
                    "schema_version": "pommerman_agent_feedback_v1",
                    "agent_id": agent,
                    "source_files": {
                        "metadata": str(match_dir / "metadata.json"),
                        "scorecard": str(match_dir / "scorecard.json"),
                        "arena_result_match_a": str(match_dir / "arena_result_match_a.json"),
                        "arena_result_match_b": str(match_dir / "arena_result_match_b.json"),
                        "trajectory_summary": str(match_dir / "trajectory_summary.json"),
                    },
                    "result_summary": {"wins": 0, "losses": 0, "draws": 0, "legs": []},
                    "diagnostics": {
                        "seat_sensitivity_observed": False,
                        "dummy_interference_observed": False,
                        "both_tested_agents_lost_any_leg": False,
                        "short_game_loss_observed": False,
                        "long_game_win_observed": False,
                    },
                    "factual_observations": [],
                    "next_round_hints": [],
                    "compact_trajectory_v2": {
                        "events_path": str(match_dir / "trajectory_events.json"),
                        "match_a": compact_events["legs"]["match_a"],
                        "match_b": compact_events["legs"]["match_b"],
                        "limitations": compact_events["limitations"],
                    },
                    "limitations": [
                        "process_feedback_v1 is derived from result-level arena artifacts and compact trajectory v2 when available",
                        "compact trajectory v2 records lightweight per-step actions/rewards/alive/positions/counts when available",
                        "full board states, full observations, death causes, bomb ownership, and power-up pickup causes are not yet recorded",
                    ],
                }
                (match_dir / f"agent_feedback_{agent}.json").write_text(json.dumps(payload), encoding="utf-8")
                (match_dir / f"agent_feedback_{agent}.md").write_text(
                    "\n".join(
                        [
                            "# Agent Feedback",
                            "## Compact Trajectory v2",
                            "- compact trajectory v2 records lightweight per-step actions/rewards/alive/positions/counts when available",
                            "## Limitations",
                            "- process_feedback_v1 is derived from result-level arena artifacts and compact trajectory v2 when available",
                            "- compact trajectory v2 records lightweight per-step actions/rewards/alive/positions/counts when available",
                            "- full board states, full observations, death causes, bomb ownership, and power-up pickup causes are not yet recorded",
                        ]
                    ),
                    encoding="utf-8",
                )
    errors, _warnings = audit_process_feedback()
    assert errors == []

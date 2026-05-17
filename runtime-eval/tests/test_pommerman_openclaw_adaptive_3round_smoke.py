import json
import hashlib
from pathlib import Path

from runner.core.config import load_yaml
from scripts.audit_pommerman_openclaw_adaptive_3round_smoke import (
    audit_openclaw_adaptive_3round_smoke,
)


def test_openclaw_adaptive_3round_config_loads():
    cfg = load_yaml("configs/tournaments/pommerman_gptv16_a00_openclaw_adaptive_3round_smoke.yaml")
    assert cfg["openclaw_adaptive_smoke"] is True
    assert cfg["num_rounds"] == 3
    assert cfg["matches_per_round"] == 3
    assert cfg["revision_rounds"] == [1, 2]
    assert cfg["revision_subset_size"] == 6
    assert cfg["require_all_agents_revised"] is True
    assert cfg["require_effective_submission_change"] is True
    assert cfg["revision_retry_on_noop"] == 1


def _mk_round_manifest(tmp_path: Path, round_idx: int, tournament: str):
    pairs_by_round = {
        1: [("a1", "a2"), ("a3", "a4"), ("a5", "a6")],
        2: [("a1", "a6"), ("a2", "a5"), ("a3", "a4")],
        3: [("a1", "a5"), ("a6", "a4"), ("a2", "a3")],
    }
    rd = tmp_path / "logs" / f"round_{round_idx}"
    rd.mkdir(parents=True, exist_ok=True)
    matches = []
    for i, (l, r) in enumerate(pairs_by_round[round_idx], start=1):
        md = rd / f"match_{i}"
        md.mkdir(parents=True, exist_ok=True)
        seed = 2000 + (round_idx * 10) + i
        common = {
            "requested_seed": seed,
            "applied_seed": seed,
            "seed": seed,
            "seed_control_status": "applied",
            "seed_control_error": None,
            "seed_control_methods_attempted": ["random.seed(...)", "env.seed(...)"],
            "seed_control_method_applied": "env.seed(...)",
            "seed_control_env_seed_return": [seed],
        }
        (md / "metadata.json").write_text(json.dumps({"left_agent_id": l, "right_agent_id": r, **common}), encoding="utf-8")
        (md / "scorecard.json").write_text(json.dumps(common), encoding="utf-8")
        (md / "arena_result_match_a.json").write_text(json.dumps(common), encoding="utf-8")
        (md / "arena_result_match_b.json").write_text(json.dumps(common), encoding="utf-8")
        (md / "trajectory_summary.json").write_text(
            json.dumps(
                {
                    "schema_version": "pommerman_process_feedback_v1",
                    "left_agent_id": l,
                    "right_agent_id": r,
                    **common,
                }
            ),
            encoding="utf-8",
        )
        (md / "trajectory_events.json").write_text(
            json.dumps({"schema_version": "pommerman_compact_trajectory_events_v2", "legs": {}, **common}),
            encoding="utf-8",
        )
        (md / "trajectory_compact_match_a.jsonl").write_text("{}", encoding="utf-8")
        (md / "trajectory_compact_match_b.jsonl").write_text("{}", encoding="utf-8")
        for aid in [l, r]:
            (md / f"agent_feedback_{aid}.json").write_text(
                json.dumps({"schema_version": "pommerman_agent_feedback_v1", "agent_id": aid}),
                encoding="utf-8",
            )
            (md / f"agent_feedback_{aid}.md").write_text("# feedback\n", encoding="utf-8")

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
                "metadata_path": str(md / "metadata.json"),
                "scorecard_path": str(md / "scorecard.json"),
                "arena_result_match_a_path": str(md / "arena_result_match_a.json"),
                "arena_result_match_b_path": str(md / "arena_result_match_b.json"),
                **common,
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


def _mk_revision_manifest(tmp_path: Path, round_idx: int, *, effective_changed: bool = True):
    submission_hash = hashlib.sha256("AGGRESSION = 0\n".encode("utf-8")).hexdigest()
    submission_hash_after = hashlib.sha256(("AGGRESSION = 1\n" if effective_changed else "AGGRESSION = 0\n").encode("utf-8")).hexdigest()
    agents = []
    for i in range(1, 7):
        aid = f"a{i}"
        agents.append(
            {
                "agent_id": aid,
                "revision_attempted": True,
                "openclaw_invoked": True,
                "revision_ok": True,
                "provider_route_status": "matched",
                "fallback_used": False,
                "revision_executor": "openclaw-minimal",
                "changed_files": ["submission/main.py"] if effective_changed else [],
                "submission_main_sha256_before": submission_hash,
                "submission_main_sha256_after": submission_hash_after,
                "effective_submission_changed": effective_changed,
                "changed_files_hash_based": ["submission/main.py"] if effective_changed else [],
                "diff_bytes": 1,
                "diff_targets": ["submission/main.py"] if effective_changed else ["notes/revision_log.md", "revision_audit.json"],
                "changed_files_reported_by_openclaw": [],
                "changed_files_inconsistent_with_hash": False,
            }
        )
    path = tmp_path / "logs" / f"round_{round_idx}" / "revision_manifest.json"
    path.write_text(
        json.dumps({"require_effective_submission_change": True, "revision_retry_on_noop": 1, "agents": agents}),
        encoding="utf-8",
    )


def _mk_propagation_manifest(tmp_path: Path, tournament: str, source_round: int, target_round: int):
    submission_hash = hashlib.sha256("AGGRESSION = 0\n".encode("utf-8")).hexdigest()
    entries = []
    for i in range(1, 7):
        aid = f"a{i}"
        entries.append(
            {
                "agent_id": aid,
                "source_post_path": f"workspace/posts/{tournament}/{aid}/codebase_post_{source_round}",
                "target_play_path": f"workspace/codebases/{tournament}/{aid}/codebase_play_{target_round}",
                "propagated": True,
                "propagation_ok": True,
                "source_revision_ok": True,
                "source_provider_route_status": "matched",
                "source_round": source_round,
                "target_round": target_round,
                "source_submission_sha256": submission_hash,
                "target_submission_sha256": submission_hash,
                "propagated_submission_sha256": submission_hash,
                "propagation_matches_post": True,
                "file_count": 0,
                "files": [],
            }
        )
    path = tmp_path / "logs" / f"round_{target_round}" / "propagation_manifest.json"
    path.write_text(json.dumps({"round_idx": target_round, "agents": entries}), encoding="utf-8")


def _mk_fixture(tmp_path: Path, tournament: str = "pommerman_gptv16_a00_openclaw_adaptive_3round_smoke"):
    for root in ["codebases", "submissions", "posts"]:
        for i in range(1, 7):
            aid = f"a{i}"
            for ridx in [1, 2, 3]:
                p = tmp_path / "workspace" / root / tournament / aid / (
                    f"{'codebase_play' if root=='codebases' else 'submission' if root=='submissions' else 'codebase_post'}_{ridx}"
                )
                p.mkdir(parents=True, exist_ok=True)
    for aid in [f"a{i}" for i in range(1, 7)]:
        for ridx in [1, 2, 3]:
            for root, prefix in [("codebases", "codebase_play"), ("posts", "codebase_post")]:
                main_path = tmp_path / "workspace" / root / tournament / aid / f"{prefix}_{ridx}" / "submission" / "main.py"
                main_path.parent.mkdir(parents=True, exist_ok=True)
                main_path.write_text("AGGRESSION = 0\n", encoding="utf-8")
    for ridx in [1, 2, 3]:
        _mk_round_manifest(tmp_path, ridx, tournament)
    _mk_revision_manifest(tmp_path, 1, effective_changed=True)
    _mk_revision_manifest(tmp_path, 2, effective_changed=True)
    _mk_propagation_manifest(tmp_path, tournament, 1, 2)
    _mk_propagation_manifest(tmp_path, tournament, 2, 3)
    return tournament


def test_adaptive_3round_audit_fixture_passes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tournament = _mk_fixture(tmp_path)
    errors, _warnings = audit_openclaw_adaptive_3round_smoke(tournament)
    assert errors == []


def test_adaptive_3round_audit_fails_without_round3_propagation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tournament = _mk_fixture(tmp_path)
    (tmp_path / "logs" / "round_3" / "propagation_manifest.json").unlink()
    errors, _warnings = audit_openclaw_adaptive_3round_smoke(tournament)
    assert any("missing logs/round_3/propagation_manifest.json" in e for e in errors)


def test_adaptive_3round_audit_fails_on_round2_fallback_used(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tournament = _mk_fixture(tmp_path)
    rp = tmp_path / "logs" / "round_2" / "revision_manifest.json"
    rev = json.loads(rp.read_text(encoding="utf-8"))
    rev["agents"][0]["fallback_used"] = True
    rp.write_text(json.dumps(rev), encoding="utf-8")
    errors, _warnings = audit_openclaw_adaptive_3round_smoke(tournament)
    assert any("fallback_used=false" in e for e in errors)


def test_adaptive_3round_audit_fails_on_non_applied_seed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tournament = _mk_fixture(tmp_path)
    p = tmp_path / "logs" / "round_2" / "match_2" / "scorecard.json"
    payload = json.loads(p.read_text(encoding="utf-8"))
    payload["seed_control_status"] = "requested_but_not_applied"
    p.write_text(json.dumps(payload), encoding="utf-8")
    errors, _warnings = audit_openclaw_adaptive_3round_smoke(tournament)
    assert any("seed_control_status must be applied" in e for e in errors)


def test_adaptive_3round_audit_fails_if_persistent_left_right_state_exists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tournament = _mk_fixture(tmp_path)
    bad = tmp_path / "workspace" / "posts" / tournament / "left"
    bad.mkdir(parents=True, exist_ok=True)
    errors, _warnings = audit_openclaw_adaptive_3round_smoke(tournament)
    assert any("persistent left/" in e for e in errors)


def test_adaptive_3round_audit_fails_when_effective_change_required_but_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tournament = _mk_fixture(tmp_path)
    rp = tmp_path / "logs" / "round_2" / "revision_manifest.json"
    rev = json.loads(rp.read_text(encoding="utf-8"))
    rev["agents"][0]["effective_submission_changed"] = False
    rev["agents"][0]["changed_files_hash_based"] = []
    rev["agents"][0]["submission_main_sha256_after"] = rev["agents"][0]["submission_main_sha256_before"]
    rp.write_text(json.dumps(rev), encoding="utf-8")
    errors, _warnings = audit_openclaw_adaptive_3round_smoke(tournament)
    assert any("require_effective_submission_change=true" in e for e in errors)

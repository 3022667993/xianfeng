import hashlib
import json
import sys
from pathlib import Path

from scripts.audit_pommerman_initial_synthesis_3round_smoke import (
    audit_pommerman_initial_synthesis_3round_smoke,
    main as audit_initial_synthesis_3round_main,
)


CURRENT_TOURNAMENT = "pommerman_gptv16_a00_openclaw_initial_synthesis_3round_neutral_double_rr_smoke"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_main(codebase_dir: Path, text: str) -> None:
    p = codebase_dir / "submission" / "main.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _write_tournament_config(tmp_path: Path, filename: str, tournament_name: str) -> Path:
    cfg = tmp_path / "configs" / "tournaments" / filename
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(
        "\n".join(
            [
                f"name: {tournament_name}",
                "num_rounds: 3",
                "matches_per_round: 3",
                "num_models: 6",
                "schedule_mode: double_round_robin",
                "match_legs: single",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return cfg


def _mk_round_manifest(tmp_path: Path, round_idx: int, tournament: str) -> None:
    pairs_by_round = {
        1: [("a1", "a2"), ("a3", "a4"), ("a5", "a6")],
        2: [("a1", "a6"), ("a2", "a5"), ("a3", "a4")],
        3: [("a1", "a5"), ("a6", "a4"), ("a2", "a3")],
    }
    round_dir = tmp_path / "logs" / f"round_{round_idx}"
    round_dir.mkdir(parents=True, exist_ok=True)
    matches = []
    for match_idx, (left, right) in enumerate(pairs_by_round[round_idx], start=1):
        match_dir = round_dir / f"match_{match_idx}"
        match_dir.mkdir(parents=True, exist_ok=True)
        seed = 2000 + (round_idx * 10) + match_idx
        seed_fields = {
            "requested_seed": seed,
            "applied_seed": seed,
            "seed": seed,
            "seed_control_status": "applied",
            "seed_control_error": None,
            "seed_control_methods_attempted": ["random.seed(...)", "env.seed(...)"],
            "seed_control_method_applied": "env.seed(...)",
            "seed_control_env_seed_return": [seed],
        }
        (match_dir / "metadata.json").write_text(
            json.dumps({"left_agent_id": left, "right_agent_id": right, **seed_fields}),
            encoding="utf-8",
        )
        (match_dir / "scorecard.json").write_text(json.dumps(seed_fields), encoding="utf-8")
        (match_dir / "arena_result_match_a.json").write_text(json.dumps(seed_fields), encoding="utf-8")
        (match_dir / "trajectory_summary.json").write_text(
            json.dumps(
                {
                    "schema_version": "pommerman_process_feedback_v2",
                    "schedule_mode": "double_round_robin",
                    "match_legs": "single",
                    "left_agent_id": left,
                    "right_agent_id": right,
                    **seed_fields,
                }
            ),
            encoding="utf-8",
        )
        (match_dir / "trajectory_events.json").write_text(
            json.dumps({"schema_version": "pommerman_compact_trajectory_events_v2", "legs": {}, **seed_fields}),
            encoding="utf-8",
        )
        (match_dir / "trajectory_compact_match_a.jsonl").write_text("{}\n", encoding="utf-8")
        for agent_id in [left, right]:
            (match_dir / f"agent_feedback_{agent_id}.json").write_text(
                json.dumps({"schema_version": "pommerman_agent_feedback_v2", "agent_id": agent_id}),
                encoding="utf-8",
            )
            (match_dir / f"agent_feedback_{agent_id}.md").write_text("# feedback\n", encoding="utf-8")
        matches.append(
            {
                "match_id": f"match_{match_idx}",
                "match_idx": match_idx,
                "pair_id": "__vs__".join(sorted([left, right])),
                "left_agent_id": left,
                "right_agent_id": right,
                "left_submission_path": f"workspace/submissions/{tournament}/{left}/submission_{round_idx}",
                "right_submission_path": f"workspace/submissions/{tournament}/{right}/submission_{round_idx}",
                "seat_assignment": {"left": left, "right": right, "background_agents": ["dummy2", "dummy3"]},
                "background_agents": ["dummy2", "dummy3"],
                "metadata_path": str(match_dir / "metadata.json"),
                "scorecard_path": str(match_dir / "scorecard.json"),
                "arena_result_match_a_path": str(match_dir / "arena_result_match_a.json"),
                "schedule_mode": "double_round_robin",
                "match_legs": "single",
                **seed_fields,
            }
        )
    (round_dir / "round_manifest.json").write_text(
        json.dumps(
            {
                "round_idx": round_idx,
                "matches_per_round": 3,
                "schedule_mode": "double_round_robin",
                "match_legs": "single",
                "scorecard_policy": "raw_per_match_scorecard; pair-level aggregation is post-analysis",
                "matches": matches,
            }
        ),
        encoding="utf-8",
    )


def _mk_revision_manifest(tmp_path: Path, round_idx: int) -> None:
    before_hash = _sha("AGGRESSION = 0\n")
    after_hash = _sha("AGGRESSION = 1\n")
    agents = []
    for idx in range(1, 7):
        agents.append(
            {
                "agent_id": f"a{idx}",
                "revision_attempted": True,
                "openclaw_invoked": True,
                "revision_ok": True,
                "provider_route_status": "matched",
                "fallback_used": False,
                "revision_executor": "openclaw-minimal",
                "changed_files": ["submission/main.py"],
                "submission_main_sha256_before": before_hash,
                "submission_main_sha256_after": after_hash,
                "effective_submission_changed": True,
                "changed_files_hash_based": ["submission/main.py"],
                "changed_files_inconsistent_with_hash": False,
            }
        )
    path = tmp_path / "logs" / f"round_{round_idx}" / "revision_manifest.json"
    path.write_text(
        json.dumps({"require_effective_submission_change": True, "revision_retry_on_noop": 1, "agents": agents}),
        encoding="utf-8",
    )


def _mk_propagation_manifest(tmp_path: Path, tournament: str, source_round: int, target_round: int) -> None:
    submission_hash = _sha("AGGRESSION = 0\n")
    entries = []
    for idx in range(1, 7):
        agent_id = f"a{idx}"
        source = tmp_path / "workspace" / "posts" / tournament / agent_id / f"codebase_post_{source_round}"
        target = tmp_path / "workspace" / "codebases" / tournament / agent_id / f"codebase_play_{target_round}"
        _write_main(source, "AGGRESSION = 0\n")
        _write_main(target, "AGGRESSION = 0\n")
        entries.append(
            {
                "agent_id": agent_id,
                "source_post_path": f"workspace/posts/{tournament}/{agent_id}/codebase_post_{source_round}",
                "target_play_path": f"workspace/codebases/{tournament}/{agent_id}/codebase_play_{target_round}",
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


def _mk_fixture(tmp_path: Path, tournament: str = CURRENT_TOURNAMENT) -> None:
    for agent_id in [f"a{i}" for i in range(1, 7)]:
        for round_idx in [1, 2, 3]:
            _write_main(
                tmp_path / "workspace" / "codebases" / tournament / agent_id / f"codebase_play_{round_idx}",
                "AGGRESSION = 0\n",
            )
            _write_main(
                tmp_path / "workspace" / "posts" / tournament / agent_id / f"codebase_post_{round_idx}",
                "AGGRESSION = 0\n",
            )
            (tmp_path / "workspace" / "submissions" / tournament / agent_id / f"submission_{round_idx}").mkdir(
                parents=True,
                exist_ok=True,
            )
    for round_idx in [1, 2, 3]:
        _mk_round_manifest(tmp_path, round_idx, tournament)
    _mk_revision_manifest(tmp_path, 1)
    _mk_revision_manifest(tmp_path, 2)
    _mk_propagation_manifest(tmp_path, tournament, 1, 2)
    _mk_propagation_manifest(tmp_path, tournament, 2, 3)


def _mk_initial_synthesis_artifacts(tmp_path: Path, tournament_name: str) -> None:
    starter_main = tmp_path / "starter_repos" / "pommerman_1v1" / "submission" / "main.py"
    starter_main.parent.mkdir(parents=True, exist_ok=True)
    starter_main.write_text("AGGRESSION = 0\n", encoding="utf-8")
    starter_sha = _sha("AGGRESSION = 0\n")

    init_entries = []
    propagation_entries = []
    for idx in range(1, 7):
        agent_id = f"a{idx}"
        agent_main = f"AGGRESSION = {idx}\n"
        agent_sha = _sha(agent_main)

        initial_post_dir = (
            tmp_path / "workspace" / "posts" / tournament_name / agent_id / "codebase_initial_post_0"
        )
        play_1_dir = (
            tmp_path / "workspace" / "codebases" / tournament_name / agent_id / "codebase_play_1"
        )
        _write_main(initial_post_dir, agent_main)
        _write_main(play_1_dir, agent_main)

        init_entries.append(
            {
                "agent_id": agent_id,
                "initial_openclaw_invoked": True,
                "initial_synthesis_ok": True,
                "initial_provider_route_status": "matched",
                "initial_actual_provider": "relay",
                "initial_actual_model": f"model-{idx}",
                "initial_fallback_used": False,
                "initial_strategy_profile_id": f"profile-{idx}",
                "initial_strategy_profile_text": f"profile text {idx}",
                "effective_initial_submission_changed": True,
                "initial_changed_files_hash_based": ["submission/main.py"],
                "starter_submission_sha256": starter_sha,
                "initial_submission_sha256": agent_sha,
                "initial_disallowed_changed_files": [],
            }
        )
        propagation_entries.append(
            {
                "agent_id": agent_id,
                "source_initial_post_path": str(initial_post_dir),
                "target_play_path": str(play_1_dir),
                "source_submission_sha256": agent_sha,
                "target_submission_sha256": agent_sha,
                "propagation_matches_post": True,
            }
        )

    logs_root = tmp_path / "logs"
    logs_root.mkdir(parents=True, exist_ok=True)
    (logs_root / "initial_synthesis_manifest.json").write_text(
        json.dumps({"tournament": tournament_name, "agents": init_entries}),
        encoding="utf-8",
    )
    round_1_dir = logs_root / "round_1"
    round_1_dir.mkdir(parents=True, exist_ok=True)
    (round_1_dir / "initial_propagation_manifest.json").write_text(
        json.dumps({"round_idx": 1, "agents": propagation_entries}),
        encoding="utf-8",
    )


def _mk_full_3round_initial_synthesis_fixture(tmp_path: Path, tournament_name: str) -> None:
    _mk_fixture(tmp_path, tournament=tournament_name)
    _mk_initial_synthesis_artifacts(tmp_path, tournament_name)


def test_initial_synthesis_3round_smoke_default_config_main_passes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tournament_name = CURRENT_TOURNAMENT
    _mk_full_3round_initial_synthesis_fixture(tmp_path, tournament_name)
    _write_tournament_config(
        tmp_path,
        "pommerman_gptv16_a00_openclaw_initial_synthesis_3round_neutral_double_rr_smoke.yaml",
        tournament_name,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["audit_pommerman_initial_synthesis_3round_smoke.py"],
    )
    assert audit_initial_synthesis_3round_main() == 0


def test_initial_synthesis_3round_smoke_neutral_config_cli_passes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tournament_name = CURRENT_TOURNAMENT
    _mk_full_3round_initial_synthesis_fixture(tmp_path, tournament_name)
    cfg_path = _write_tournament_config(
        tmp_path,
        "pommerman_gptv16_a00_openclaw_initial_synthesis_3round_neutral_double_rr_smoke.yaml",
        tournament_name,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "audit_pommerman_initial_synthesis_3round_smoke.py",
            "--tournament",
            str(cfg_path),
        ],
    )
    assert audit_initial_synthesis_3round_main() == 0


def test_initial_synthesis_3round_smoke_fails_when_tournament_name_is_hardcoded_wrong(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    neutral_tournament_name = CURRENT_TOURNAMENT
    _mk_full_3round_initial_synthesis_fixture(tmp_path, neutral_tournament_name)
    neutral_cfg = _write_tournament_config(
        tmp_path,
        "pommerman_gptv16_a00_openclaw_initial_synthesis_3round_neutral_double_rr_smoke.yaml",
        neutral_tournament_name,
    )
    errors, _warnings = audit_pommerman_initial_synthesis_3round_smoke(
        tournament_name="pommerman_gptv16_a00_openclaw_initial_synthesis_10round_neutral_double_rr",
        tournament_config_path=neutral_cfg,
    )
    assert any("tournament_name mismatch with config" in e for e in errors)

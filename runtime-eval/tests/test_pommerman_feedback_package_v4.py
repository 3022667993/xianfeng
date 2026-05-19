import json
from pathlib import Path

from runner.core.pommerman_feedback_package import (
    V4_README,
    sanitize_model_visible_run_log,
    stage_feedback_packages_for_round,
    write_feedback_package_for_agent,
)
from scripts.audit_pommerman_feedback_package import audit_feedback_package


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _mk_compact_rows(step_count: int) -> str:
    rows = []
    for step in range(step_count):
        rows.append(
            {
                "schema_version": "pommerman_compact_trajectory_step_v2",
                "leg_label": "match_a",
                "step": step,
                "actions": {"seat_0": 0, "seat_1": 1, "seat_2": 2, "seat_3": 3},
                "reward": [0, 0, 0, 0],
                "done": step == step_count - 1,
            }
        )
    return "\n".join(json.dumps(row) for row in rows) + "\n"


def _mk_match(
    *,
    root: Path,
    round_idx: int,
    match_idx: int,
    left_agent_id: str,
    right_agent_id: str,
    requested_seed: int,
    applied_seed: int,
    steps: int = 3,
    winner: str = "draw",
    reward: list[int] | None = None,
    info: dict | None = None,
    official_record: bool = True,
) -> dict:
    match_dir = root / "logs" / f"round_{round_idx}" / f"match_{match_idx}"
    match_dir.mkdir(parents=True, exist_ok=True)
    if reward is None:
        reward = [0, 0, 0, 0] if winner == "draw" else ([1, -1, -1, -1] if winner == "left" else [-1, 1, -1, -1])
    if info is None:
        info = {"winners": [] if winner == "draw" else ([0] if winner == "left" else [1])}
    _write_json(
        match_dir / "metadata.json",
        {
            "round_idx": round_idx,
            "match_idx": match_idx,
            "match_id": f"match_{match_idx}",
            "left_agent_id": left_agent_id,
            "right_agent_id": right_agent_id,
            "requested_seed": requested_seed,
            "applied_seed": applied_seed,
            "schedule_mode": "double_round_robin",
            "match_legs": "single",
        },
    )
    _write_json(
        match_dir / "arena_result_match_a.json",
        {
            "steps": steps,
            "reward": reward,
            "info": info,
            "left_right_winner": winner,
            "requested_seed": requested_seed,
            "applied_seed": applied_seed,
        },
    )
    (match_dir / "trajectory_compact_match_a.jsonl").write_text(_mk_compact_rows(steps), encoding="utf-8")
    for name in ["build.log", "test.log", "stderr.log"]:
        (match_dir / name).write_text(f"{name} ok\n", encoding="utf-8")
    if official_record:
        _write_json(match_dir / "official_record_json_match_a" / "game_state.json", {"state": [{"step_count": 0}]})
    return {
        "match_id": f"match_{match_idx}",
        "match_idx": match_idx,
        "match_dir": str(match_dir),
        "left_agent_id": left_agent_id,
        "right_agent_id": right_agent_id,
        "requested_seed": requested_seed,
        "applied_seed": applied_seed,
    }


def _mk_round_context(tmp_path: Path, tournament: str, match_records: list[dict], expected_agents: list[str]) -> None:
    _write_json(
        tmp_path / "logs" / "initial_synthesis_manifest.json",
        {"tournament": tournament, "agents": [{"agent_id": agent_id} for agent_id in expected_agents]},
    )
    _write_json(
        tmp_path / "logs" / "round_1" / "round_manifest.json",
        {
            "round_idx": 1,
            "schedule_mode": "double_round_robin",
            "match_legs": "single",
            "matches": [
                {
                    "match_id": rec["match_id"],
                    "match_idx": rec["match_idx"],
                    "left_agent_id": rec["left_agent_id"],
                    "right_agent_id": rec["right_agent_id"],
                    "requested_seed": rec["requested_seed"],
                    "applied_seed": rec["applied_seed"],
                }
                for rec in match_records
            ],
        },
    )
    _write_json(
        tmp_path / "logs" / "round_1" / "revision_manifest.json",
        {"agents": [{"agent_id": agent_id, "revision_attempted": True, "revision_ok": True} for agent_id in expected_agents]},
    )


def test_feedback_package_v4_generated_with_official_record_and_audits_pass(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tournament = "t_feedback_v4"
    records = [
        _mk_match(root=tmp_path, round_idx=1, match_idx=1, left_agent_id="a1", right_agent_id="a2", requested_seed=111, applied_seed=111),
        _mk_match(root=tmp_path, round_idx=1, match_idx=2, left_agent_id="a3", right_agent_id="a4", requested_seed=222, applied_seed=222),
        _mk_match(root=tmp_path, round_idx=1, match_idx=3, left_agent_id="a5", right_agent_id="a6", requested_seed=333, applied_seed=333),
    ]
    agents = [f"a{i}" for i in range(1, 7)]
    _mk_round_context(tmp_path, tournament, records, agents)

    stage_feedback_packages_for_round(
        tournament_name=tournament,
        round_idx=1,
        agent_ids=agents,
        round_match_records=records,
        feedback_package_variant="codeclash_v4",
    )

    package_root = tmp_path / "workspace" / "posts" / tournament / "a1" / "codebase_post_1" / "feedback" / "round_1"
    manifest = json.loads((package_root / "package_manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "pommerman_feedback_package_v4"
    assert manifest["replay_source"] == "pommerman_record_json_dir"
    assert manifest["full_board_replay"] is True
    assert (package_root / "matches" / "match_1" / "match_index.json").exists()
    assert (package_root / "matches" / "match_1" / "official_record_json" / "game_state.json").exists()
    scoreboard = json.loads((package_root / "public_scoreboard.json").read_text(encoding="utf-8"))
    score_row = scoreboard["matches"][0]
    assert score_row["environment_winners"] == []
    assert score_row["environment_winner_labels"] == []
    assert score_row["submitted_pair_outcome"] == "unknown_draw"
    assert score_row["draw_type"] == "unknown_draw"
    match_index = json.loads((package_root / "matches" / "match_1" / "match_index.json").read_text(encoding="utf-8"))
    assert match_index["game"]["submitted_pair_outcome"] == "unknown_draw"
    assert match_index["game"]["draw_type"] == "unknown_draw"
    actions = [
        json.loads(line)
        for line in (package_root / "matches" / "match_1" / "actions.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert actions[0]["internal_leg_id"] == "match_a"
    assert actions[0]["agent_action"] == 0
    assert actions[0]["opponent_action"] == 1
    assert "match_b" not in package_root.read_text(encoding="utf-8") if package_root.is_file() else True

    readme_text = (package_root / "README.md").read_text(encoding="utf-8")
    assert "../../README.md" in readme_text
    assert "This feedback package contains match evidence, not the rules specification." in readme_text
    assert "Prefer winning over drawing, and drawing over losing." in readme_text
    assert "A timeout draw is not a strong success signal if better outcomes are possible." in readme_text
    assert "both submitted agents lost to a dummy/background agent" in readme_text
    assert "not as a successful draw" in readme_text
    assert "Use this feedback package as evidence." in readme_text
    assert "Start with `public_scoreboard.json`, then `matches/*/match_index.json`, then `matches/*/actions.jsonl`" in readme_text
    assert "board/state replay is needed" in readme_text
    assert "concrete strategy or behavior change" in readme_text
    assert "improve future tournament outcomes against opponents" in readme_text
    assert "robustness, consistency, or resilience" in readme_text
    assert "`submitted_pair_outcome`: distinguishes wins, timeout draws, dummy/background-agent wins" in readme_text
    assert "`draw_type`: explains why a pairwise draw occurred" in readme_text
    assert "Feedback files are read-only evidence." in readme_text or "read-only evidence" in readme_text
    assert "## Suggested Reading Order" in readme_text
    assert "Start with `public_scoreboard.json`" in readme_text
    assert "Use `matches/*/actions.jsonl` for compact per-step action evidence." in readme_text
    assert "Inspect `matches/*/official_record_json/game_state.json` selectively" in readme_text
    assert "This file can be large and is evidence, not the rules specification." in readme_text
    assert "`state[0]` is the initial snapshot after reset" in readme_text
    assert "transition from `game_state.state[t]` to `game_state.state[t+1]`" in readme_text
    for forbidden in [
        "starter_repos",
        "match_b",
        "both legs",
        "paired legs",
        "seat-swap legs",
        "center movement",
        "wood clearing",
        "powerups",
        "opponent pressure",
        "reduce stop",
        "safe aggression",
    ]:
        assert forbidden not in readme_text.lower()

    errors, _warnings = audit_feedback_package(tournament_name=tournament)
    assert errors == []


def test_feedback_package_v4_classifies_dummy_winner_draw(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tournament = "t_feedback_v4_dummy_winner"
    records = [
        _mk_match(
            root=tmp_path,
            round_idx=1,
            match_idx=1,
            left_agent_id="a1",
            right_agent_id="a2",
            requested_seed=111,
            applied_seed=111,
            steps=12,
            winner="draw",
            reward=[-1, -1, 1, -1],
            info={"winners": [2]},
        )
    ]
    _mk_round_context(tmp_path, tournament, records, ["a1", "a2"])

    for agent_id in ["a1", "a2"]:
        write_feedback_package_for_agent(
            tournament_name=tournament,
            round_idx=1,
            agent_id=agent_id,
            round_match_records=records,
            feedback_package_variant="codeclash_v4",
        )

    package_root = tmp_path / "workspace" / "posts" / tournament / "a1" / "codebase_post_1" / "feedback" / "round_1"
    scoreboard = json.loads((package_root / "public_scoreboard.json").read_text(encoding="utf-8"))
    row = scoreboard["matches"][0]
    assert row["winner"] == "draw"
    assert row["environment_winners"] == [2]
    assert row["environment_winner_labels"] == ["dummy2"]
    assert row["submitted_pair_outcome"] == "both_submitted_agents_lost_to_dummy"
    assert row["draw_type"] == "both_lost_to_dummy"

    match_index = json.loads((package_root / "matches" / "match_1" / "match_index.json").read_text(encoding="utf-8"))
    game = match_index["game"]
    assert game["winner"] == "draw"
    assert game["environment_winners"] == [2]
    assert game["environment_winner_labels"] == ["dummy2"]
    assert game["submitted_pair_outcome"] == "both_submitted_agents_lost_to_dummy"
    assert game["draw_type"] == "both_lost_to_dummy"

    errors, _warnings = audit_feedback_package(tournament_name=tournament)
    assert errors == []


def test_feedback_package_v4_uses_compact_fallback_without_full_board_claim(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tournament = "t_feedback_v4_fallback"
    records = [
        _mk_match(
            root=tmp_path,
            round_idx=1,
            match_idx=1,
            left_agent_id="a1",
            right_agent_id="a2",
            requested_seed=111,
            applied_seed=111,
            official_record=False,
        )
    ]
    _mk_round_context(tmp_path, tournament, records, ["a1", "a2"])
    for agent_id in ["a1", "a2"]:
        write_feedback_package_for_agent(
            tournament_name=tournament,
            round_idx=1,
            agent_id=agent_id,
            round_match_records=records,
            feedback_package_variant="codeclash_v4",
        )
    package_root = tmp_path / "workspace" / "posts" / tournament / "a1" / "codebase_post_1" / "feedback" / "round_1"
    manifest = json.loads((package_root / "package_manifest.json").read_text(encoding="utf-8"))
    assert manifest["replay_source"] == "compact_trajectory_fallback"
    assert manifest["full_board_replay"] is False
    marker = package_root / "matches" / "match_1" / "official_record_json" / "README.txt"
    assert marker.exists()
    marker_text = marker.read_text(encoding="utf-8")
    assert "Official Pommerman game_state.json was not available for this match." in marker_text
    assert "compact_trajectory_fallback" in marker_text
    errors, _warnings = audit_feedback_package(tournament_name=tournament)
    assert errors == []


def test_run_logs_sanitizer_redacts_private_paths_and_keeps_errors():
    raw = "\n".join(
        [
            'Traceback (most recent call last):',
            '  File "/root/autodl-tmp/runtime-eval/workspace/codebases/t/a1/codebase_play_1/submission/main.py", line 7',
            "    raise SyntaxError('bad move')",
            "SyntaxError: bad move",
            "stderr from /root/autodl-tmp/runtime-eval/workspace/posts/t/a1/codebase_post_1/feedback/round_1",
            "input at /root/autodl-tmp/runtime-eval/workspace/submissions/a1/main.py",
            "openclaw at /root/autodl-tmp/runtime-eval/openclaw_workspaces/minimal/runtime_eval_runs/run-1",
            "cache at /tmp/private-layout/run.py",
        ]
    )

    sanitized = sanitize_model_visible_run_log(raw)

    assert "/root/autodl-tmp/runtime-eval/workspace/" not in sanitized
    assert "codebase_play_" not in sanitized
    assert "codebase_post_" not in sanitized
    assert "openclaw_workspaces/minimal/runtime_eval_runs" not in sanitized
    assert "/tmp/private-layout" not in sanitized
    assert "<workspace_codebases>" in sanitized
    assert "<workspace_posts>" in sanitized
    assert "<workspace_submissions>" in sanitized
    assert "<openclaw_workspaces>" in sanitized
    assert "<tmp>" in sanitized
    assert "Traceback (most recent call last):" in sanitized
    assert "SyntaxError: bad move" in sanitized
    assert "raise SyntaxError('bad move')" in sanitized


def test_feedback_package_v4_run_logs_are_sanitized_and_audit_passes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tournament = "t_feedback_v4_sanitized_logs"
    records = [
        _mk_match(root=tmp_path, round_idx=1, match_idx=1, left_agent_id="a1", right_agent_id="a2", requested_seed=111, applied_seed=111)
    ]
    match_dir = tmp_path / "logs" / "round_1" / "match_1"
    (match_dir / "stderr.log").write_text(
        "\n".join(
            [
                'Traceback (most recent call last):',
                '  File "/root/autodl-tmp/runtime-eval/workspace/codebases/t/a1/codebase_play_1/submission/main.py", line 7',
                "SyntaxError: bad move",
                "temporary path /tmp/private-layout/run.py failed",
            ]
        ),
        encoding="utf-8",
    )
    _mk_round_context(tmp_path, tournament, records, ["a1", "a2"])
    for agent_id in ["a1", "a2"]:
        write_feedback_package_for_agent(
            tournament_name=tournament,
            round_idx=1,
            agent_id=agent_id,
            round_match_records=records,
            feedback_package_variant="codeclash_v4",
        )

    run_logs = (
        tmp_path
        / "workspace"
        / "posts"
        / tournament
        / "a1"
        / "codebase_post_1"
        / "feedback"
        / "round_1"
        / "matches"
        / "match_1"
        / "run_logs.txt"
    ).read_text(encoding="utf-8")
    assert "/root/autodl-tmp/runtime-eval/workspace/" not in run_logs
    assert "codebase_play_" not in run_logs
    assert "/tmp/private-layout" not in run_logs
    assert "<workspace_codebases>" in run_logs
    assert "<tmp>" in run_logs
    assert "Traceback (most recent call last):" in run_logs
    assert "SyntaxError: bad move" in run_logs

    errors, _warnings = audit_feedback_package(tournament_name=tournament)
    assert errors == []


def test_feedback_package_v4_audit_fails_unsanitized_private_run_log_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tournament = "t_feedback_v4_unsanitized_logs"
    records = [
        _mk_match(root=tmp_path, round_idx=1, match_idx=1, left_agent_id="a1", right_agent_id="a2", requested_seed=111, applied_seed=111)
    ]
    _mk_round_context(tmp_path, tournament, records, ["a1", "a2"])
    for agent_id in ["a1", "a2"]:
        write_feedback_package_for_agent(
            tournament_name=tournament,
            round_idx=1,
            agent_id=agent_id,
            round_match_records=records,
            feedback_package_variant="codeclash_v4",
        )

    run_logs_path = (
        tmp_path
        / "workspace"
        / "posts"
        / tournament
        / "a1"
        / "codebase_post_1"
        / "feedback"
        / "round_1"
        / "matches"
        / "match_1"
        / "run_logs.txt"
    )
    run_logs_path.write_text(
        run_logs_path.read_text(encoding="utf-8")
        + "\n/root/autodl-tmp/runtime-eval/workspace/codebases/t/a1/codebase_play_1/submission/main.py\n",
        encoding="utf-8",
    )

    errors, _warnings = audit_feedback_package(tournament_name=tournament)
    assert any("contains forbidden token" in error and "run_logs.txt" in error for error in errors)


def test_feedback_package_v4_audit_fails_when_packages_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tournament = "t_feedback_v4_incomplete"
    records = [
        _mk_match(root=tmp_path, round_idx=1, match_idx=1, left_agent_id="a1", right_agent_id="a2", requested_seed=111, applied_seed=111),
        _mk_match(root=tmp_path, round_idx=1, match_idx=2, left_agent_id="a3", right_agent_id="a4", requested_seed=222, applied_seed=222),
        _mk_match(root=tmp_path, round_idx=1, match_idx=3, left_agent_id="a5", right_agent_id="a6", requested_seed=333, applied_seed=333),
    ]
    agents = [f"a{i}" for i in range(1, 7)]
    _mk_round_context(tmp_path, tournament, records, agents)
    for agent_id in ["a1", "a3", "a5"]:
        write_feedback_package_for_agent(
            tournament_name=tournament,
            round_idx=1,
            agent_id=agent_id,
            round_match_records=records,
            feedback_package_variant="codeclash_v4",
        )
    errors, _warnings = audit_feedback_package(tournament_name=tournament)
    assert any("round_1 feedback packages incomplete: 3/6" in error for error in errors)


def test_feedback_package_v4_audit_fails_full_board_claim_without_game_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tournament = "t_feedback_v4_bad_full_board"
    records = [
        _mk_match(root=tmp_path, round_idx=1, match_idx=1, left_agent_id="a1", right_agent_id="a2", requested_seed=111, applied_seed=111)
    ]
    _mk_round_context(tmp_path, tournament, records, ["a1", "a2"])
    for agent_id in ["a1", "a2"]:
        write_feedback_package_for_agent(
            tournament_name=tournament,
            round_idx=1,
            agent_id=agent_id,
            round_match_records=records,
            feedback_package_variant="codeclash_v4",
        )
    package_root = tmp_path / "workspace" / "posts" / tournament / "a1" / "codebase_post_1" / "feedback" / "round_1"
    (package_root / "matches" / "match_1" / "official_record_json" / "game_state.json").unlink()
    manifest_path = package_root / "package_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["full_board_replay"] = True
    manifest["replay_source"] = "pommerman_record_json_dir"
    _write_json(manifest_path, manifest)
    errors, _warnings = audit_feedback_package(tournament_name=tournament)
    assert any("full_board_replay=true but game_state.json is missing" in error for error in errors)


def test_run_arena_record_json_dir_is_backward_compatible_optional_argument():
    text = Path("starter_repos/pommerman_1v1/scripts/run_arena.sh").read_text(encoding="utf-8")
    assert 'OUT_JSON="${1:?' in text
    assert 'LEFT_SUBMISSION_MAIN="${2:?' in text
    assert 'RIGHT_SUBMISSION_MAIN="${3:?' in text
    assert "RECORD_JSON_DIR" in text
    assert "--record-json-dir" in text


def test_probe_normalizes_nested_game_state_json(tmp_path):
    script = Path("starter_repos/pommerman_1v1/scripts/pommerman_ffa_probe.py").read_text(encoding="utf-8")
    assert "--record-json-dir" in script
    namespace = {}
    exec(
        "from pathlib import Path\nimport shutil\n"
        + script.split("def _normalize_record_json_dir", 1)[1].split("\n\ndef _make_env", 1)[0].join(
            ["def _normalize_record_json_dir", ""]
        ),
        namespace,
    )
    record_dir = tmp_path / "official"
    _write_json(record_dir / "1" / "game_state.json", {"ok": True})
    assert namespace["_normalize_record_json_dir"](record_dir) is True
    assert (record_dir / "game_state.json").exists()


def test_probe_uses_local_pommerman_recording_api():
    script = Path("starter_repos/pommerman_1v1/scripts/pommerman_ffa_probe.py").read_text(encoding="utf-8")
    assert "env.save_json = True" not in script
    assert "setattr(env, attr, value)" not in script
    assert "record_json_dir=str(record_json_dir)" not in script
    assert "env.save_json(str(record_json_dir))" in script
    assert "utility.join_json_state(" in script
    assert 'RECORD_AGENT_LABELS = ["left", "right", "dummy2", "dummy3"]' in script


def test_v4_readme_spec_has_no_forbidden_terms():
    lower = V4_README.lower()
    for forbidden in [
        "starter_repos",
        "match_b",
        "both legs",
        "paired legs",
        "seat-swap legs",
        "center movement",
        "wood clearing",
        "powerups",
        "opponent pressure",
        "reduce stop",
        "safe aggression",
        "codebase_post_",
    ]:
        assert forbidden not in lower
    assert "../../readme.md" in lower
    assert "match evidence, not the rules specification" in lower
    assert "prefer winning over drawing, and drawing over losing" in lower
    assert "timeout draw is not a strong success signal" in lower
    assert "both submitted agents lost to a dummy/background agent" in lower
    assert "not as a successful draw" in lower
    assert "use this feedback package as evidence" in lower
    assert "start with `public_scoreboard.json`, then `matches/*/match_index.json`, then `matches/*/actions.jsonl`" in lower
    assert "board/state replay is needed" in lower
    assert "concrete strategy or behavior change" in lower
    assert "improve future tournament outcomes against opponents" in lower
    assert "robustness, consistency, or resilience" in lower
    assert "`submitted_pair_outcome`: distinguishes wins, timeout draws, dummy/background-agent wins" in lower
    assert "`draw_type`: explains why a pairwise draw occurred" in lower
    assert "current post-round codebase" in lower
    assert "read-only evidence" in lower
    assert "suggested reading order" in lower
    assert "start with `public_scoreboard.json`" in lower
    assert "use `matches/*/actions.jsonl` for compact per-step action evidence" in lower
    assert "inspect `matches/*/official_record_json/game_state.json` selectively" in lower
    assert "`state[0]` is the initial snapshot after reset" in lower
    assert "one more state snapshot than action rows" in lower

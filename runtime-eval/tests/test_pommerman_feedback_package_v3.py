import json
from pathlib import Path

from runner.core.pommerman_feedback_package import stage_feedback_packages_for_round, write_feedback_package_for_agent
from scripts.audit_pommerman_feedback_package import audit_feedback_package


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _mk_compact_rows(step_count: int, *, final_done: bool) -> str:
    rows = []
    for step in range(step_count):
        rows.append(
            {
                "schema_version": "pommerman_compact_trajectory_step_v2",
                "leg_label": None,
                "step": step,
                "actions": {"seat_0": 0, "seat_1": 1, "seat_2": 0, "seat_3": 0},
                "reward": [0, 0, 0, 0],
                "done": bool(final_done and (step == step_count - 1)),
                "alive": {"seat_0": True, "seat_1": True, "seat_2": True, "seat_3": True},
                "positions": {"seat_0": [1, 1], "seat_1": [1, 2], "seat_2": [2, 1], "seat_3": [2, 2]},
                "compact_counts": {"bomb_count": 0, "flame_count": 0, "powerup_count": 0},
            }
        )
    return "\n".join(json.dumps(r) for r in rows) + "\n"


def _mk_match(
    *,
    root: Path,
    round_idx: int,
    match_idx: int,
    left_agent_id: str,
    right_agent_id: str,
    requested_seed: int,
    applied_seed: int,
    steps: int,
    winner: str,
    reward_a,
    reward_b,
) -> None:
    md = root / "logs" / f"round_{round_idx}" / f"match_{match_idx}"
    md.mkdir(parents=True, exist_ok=True)
    _write_json(
        md / "metadata.json",
        {
            "round_idx": round_idx,
            "match_idx": match_idx,
            "match_id": f"match_{match_idx}",
            "left_agent_id": left_agent_id,
            "right_agent_id": right_agent_id,
            "requested_seed": requested_seed,
            "applied_seed": applied_seed,
            "seed_control_status": "applied",
        },
    )
    _write_json(
        md / "arena_result_match_a.json",
        {
            "steps": steps,
            "reward": reward_a,
            "left_right_winner": winner,
            "requested_seed": requested_seed,
            "applied_seed": applied_seed,
        },
    )
    (md / "trajectory_compact_match_a.jsonl").write_text(_mk_compact_rows(steps, final_done=True), encoding="utf-8")
    for n in ["build.log", "test.log", "stderr.log"]:
        (md / n).write_text(f"{n} ok\n", encoding="utf-8")


def test_feedback_package_v3_generated_and_audits_pass(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    t = "t_feedback_v3"
    round_idx = 1

    # Two matches this round; a2 only participates in match_1.
    _mk_match(
        root=tmp_path,
        round_idx=round_idx,
        match_idx=1,
        left_agent_id="a1",
        right_agent_id="a2",
        requested_seed=111,
        applied_seed=111,
        steps=3,
        winner="left",
        reward_a=[1, -1, -1, -1],
        reward_b=[1, -1, -1, -1],
    )
    _mk_match(
        root=tmp_path,
        round_idx=round_idx,
        match_idx=2,
        left_agent_id="a1",
        right_agent_id="a3",
        requested_seed=222,
        applied_seed=222,
        steps=2,
        winner="draw",
        reward_a=[0, 0, 0, 0],
        reward_b=[0, 0, 0, 0],
    )

    # Round + revision manifests needed by the audit script.
    (tmp_path / "logs" / f"round_{round_idx}").mkdir(parents=True, exist_ok=True)
    _write_json(tmp_path / "logs" / "initial_synthesis_manifest.json", {"tournament": t})
    _write_json(
        tmp_path / "logs" / f"round_{round_idx}" / "round_manifest.json",
        {
            "round_idx": round_idx,
            "matches": [
                {
                    "match_id": "match_1",
                    "match_idx": 1,
                    "left_agent_id": "a1",
                    "right_agent_id": "a2",
                    "requested_seed": 111,
                    "applied_seed": 111,
                },
                {
                    "match_id": "match_2",
                    "match_idx": 2,
                    "left_agent_id": "a1",
                    "right_agent_id": "a3",
                    "requested_seed": 222,
                    "applied_seed": 222,
                },
            ],
        },
    )
    _write_json(
        tmp_path / "logs" / f"round_{round_idx}" / "revision_manifest.json",
        {
            "agents": [
                {"agent_id": "a1", "revision_attempted": True, "revision_ok": True},
                {"agent_id": "a2", "revision_attempted": True, "revision_ok": True},
                {"agent_id": "a3", "revision_attempted": True, "revision_ok": True},
            ]
        },
    )

    match_records = [
        {
            "match_id": "match_1",
            "match_idx": 1,
            "match_dir": str(tmp_path / "logs" / "round_1" / "match_1"),
            "left_agent_id": "a1",
            "right_agent_id": "a2",
            "requested_seed": 111,
            "applied_seed": 111,
        },
        {
            "match_id": "match_2",
            "match_idx": 2,
            "match_dir": str(tmp_path / "logs" / "round_1" / "match_2"),
            "left_agent_id": "a1",
            "right_agent_id": "a3",
            "requested_seed": 222,
            "applied_seed": 222,
        },
    ]

    for agent_id in ["a1", "a2", "a3"]:
        write_feedback_package_for_agent(
            tournament_name=t,
            round_idx=round_idx,
            agent_id=agent_id,
            round_match_records=match_records,
            feedback_visibility="own_matches_plus_public_scoreboard",
        )

    # a2 should only see its own match package, but scoreboard should include both matches.
    pkg_a2 = tmp_path / "workspace" / "posts" / t / "a2" / "codebase_post_1" / "feedback" / "round_1"
    assert (pkg_a2 / "matches" / "match_1" / "result.json").exists()
    assert not (pkg_a2 / "matches" / "match_2").exists()
    sc = json.loads((pkg_a2 / "public_scoreboard.json").read_text(encoding="utf-8"))
    assert isinstance(sc, dict)
    assert len(sc.get("matches", [])) == 2

    errors, _warnings = audit_feedback_package(tournament_name=t)
    assert errors == []


def test_feedback_package_v3_round_coverage_generates_packages_for_both_sides_and_audits_pass(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    t = "t_feedback_v3_full_round"
    round_idx = 1

    # Three matches / six agents: every agent participates exactly once.
    _mk_match(
        root=tmp_path,
        round_idx=round_idx,
        match_idx=1,
        left_agent_id="a1",
        right_agent_id="a2",
        requested_seed=111,
        applied_seed=111,
        steps=3,
        winner="left",
        reward_a=[1, -1, -1, -1],
        reward_b=[1, -1, -1, -1],
    )
    _mk_match(
        root=tmp_path,
        round_idx=round_idx,
        match_idx=2,
        left_agent_id="a3",
        right_agent_id="a4",
        requested_seed=222,
        applied_seed=222,
        steps=2,
        winner="draw",
        reward_a=[0, 0, 0, 0],
        reward_b=[0, 0, 0, 0],
    )
    _mk_match(
        root=tmp_path,
        round_idx=round_idx,
        match_idx=3,
        left_agent_id="a5",
        right_agent_id="a6",
        requested_seed=333,
        applied_seed=333,
        steps=4,
        winner="right",
        reward_a=[-1, 1, -1, -1],
        reward_b=[-1, 1, -1, -1],
    )

    # Round manifest for scoreboard sizing.
    rd = tmp_path / "logs" / f"round_{round_idx}"
    rd.mkdir(parents=True, exist_ok=True)
    _write_json(
        rd / "round_manifest.json",
        {
            "round_idx": round_idx,
            "matches": [
                {
                    "match_id": "match_1",
                    "match_idx": 1,
                    "left_agent_id": "a1",
                    "right_agent_id": "a2",
                    "requested_seed": 111,
                    "applied_seed": 111,
                },
                {
                    "match_id": "match_2",
                    "match_idx": 2,
                    "left_agent_id": "a3",
                    "right_agent_id": "a4",
                    "requested_seed": 222,
                    "applied_seed": 222,
                },
                {
                    "match_id": "match_3",
                    "match_idx": 3,
                    "left_agent_id": "a5",
                    "right_agent_id": "a6",
                    "requested_seed": 333,
                    "applied_seed": 333,
                },
            ],
        },
    )

    # Tournament config controls audit expectations when revision_manifest is missing.
    cfg = tmp_path / "configs" / "tournaments"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / f"{t}.yaml").write_text(
        "\n".join(
            [
                f"name: {t}",
                "game: pommerman_1v1",
                "regime: A00",
                "require_all_agents_revised: true",
                "revision_rounds: [1]",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    # Roster source for expected package count.
    _write_json(
        tmp_path / "logs" / "initial_synthesis_manifest.json",
        {"tournament": t, "agents": [{"agent_id": f"a{i}"} for i in range(1, 7)]},
    )

    match_records = [
        {
            "match_id": "match_1",
            "match_idx": 1,
            "match_dir": str(tmp_path / "logs" / "round_1" / "match_1"),
            "left_agent_id": "a1",
            "right_agent_id": "a2",
            "requested_seed": 111,
            "applied_seed": 111,
        },
        {
            "match_id": "match_2",
            "match_idx": 2,
            "match_dir": str(tmp_path / "logs" / "round_1" / "match_2"),
            "left_agent_id": "a3",
            "right_agent_id": "a4",
            "requested_seed": 222,
            "applied_seed": 222,
        },
        {
            "match_id": "match_3",
            "match_idx": 3,
            "match_dir": str(tmp_path / "logs" / "round_1" / "match_3"),
            "left_agent_id": "a5",
            "right_agent_id": "a6",
            "requested_seed": 333,
            "applied_seed": 333,
        },
    ]

    stage_feedback_packages_for_round(
        tournament_name=t,
        round_idx=round_idx,
        agent_ids=[f"a{i}" for i in range(1, 7)],
        round_match_records=match_records,
        feedback_visibility="own_matches_plus_public_scoreboard",
    )

    # Verify all 6 packages exist and each agent only sees their own match.
    for i in range(1, 7):
        agent_id = f"a{i}"
        pkg = tmp_path / "workspace" / "posts" / t / agent_id / "codebase_post_1" / "feedback" / "round_1"
        assert pkg.exists()
        assert (pkg / "README.md").exists()
        assert (pkg / "public_scoreboard.json").exists()
        assert (pkg / "round_summary.json").exists()
        assert (pkg / "checksums.json").exists()

        matches_dir = pkg / "matches"
        present = sorted(p.name for p in matches_dir.iterdir() if p.is_dir())
        assert len(present) == 1

        result = json.loads((matches_dir / present[0] / "result.json").read_text(encoding="utf-8"))
        if agent_id in {"a1", "a3", "a5"}:
            assert result["match_a"]["agent_seat"] == "left"
            assert result["match_a"]["opponent_seat"] == "right"
        else:
            assert result["match_a"]["agent_seat"] == "right"
            assert result["match_a"]["opponent_seat"] == "left"

    errors, _warnings = audit_feedback_package(tournament_name=t)
    assert errors == []


def test_feedback_package_audit_fails_when_round_packages_incomplete(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    t = "t_feedback_v3_incomplete"
    round_idx = 1

    # Three matches / six agents, but we'll only generate 3 packages.
    _mk_match(
        root=tmp_path,
        round_idx=round_idx,
        match_idx=1,
        left_agent_id="a1",
        right_agent_id="a2",
        requested_seed=111,
        applied_seed=111,
        steps=3,
        winner="left",
        reward_a=[1, -1, -1, -1],
        reward_b=[1, -1, -1, -1],
    )
    _mk_match(
        root=tmp_path,
        round_idx=round_idx,
        match_idx=2,
        left_agent_id="a3",
        right_agent_id="a4",
        requested_seed=222,
        applied_seed=222,
        steps=2,
        winner="draw",
        reward_a=[0, 0, 0, 0],
        reward_b=[0, 0, 0, 0],
    )
    _mk_match(
        root=tmp_path,
        round_idx=round_idx,
        match_idx=3,
        left_agent_id="a5",
        right_agent_id="a6",
        requested_seed=333,
        applied_seed=333,
        steps=4,
        winner="right",
        reward_a=[-1, 1, -1, -1],
        reward_b=[-1, 1, -1, -1],
    )

    rd = tmp_path / "logs" / f"round_{round_idx}"
    rd.mkdir(parents=True, exist_ok=True)
    _write_json(
        rd / "round_manifest.json",
        {
            "round_idx": round_idx,
            "matches": [
                {"match_id": "match_1", "match_idx": 1, "left_agent_id": "a1", "right_agent_id": "a2", "requested_seed": 111, "applied_seed": 111},
                {"match_id": "match_2", "match_idx": 2, "left_agent_id": "a3", "right_agent_id": "a4", "requested_seed": 222, "applied_seed": 222},
                {"match_id": "match_3", "match_idx": 3, "left_agent_id": "a5", "right_agent_id": "a6", "requested_seed": 333, "applied_seed": 333},
            ],
        },
    )

    cfg = tmp_path / "configs" / "tournaments"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / f"{t}.yaml").write_text(
        "\n".join(
            [
                f"name: {t}",
                "game: pommerman_1v1",
                "regime: A00",
                "require_all_agents_revised: true",
                "revision_rounds: [1]",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    _write_json(
        tmp_path / "logs" / "initial_synthesis_manifest.json",
        {"tournament": t, "agents": [{"agent_id": f"a{i}"} for i in range(1, 7)]},
    )

    match_records = [
        {"match_id": "match_1", "match_idx": 1, "match_dir": str(tmp_path / "logs" / "round_1" / "match_1"), "left_agent_id": "a1", "right_agent_id": "a2", "requested_seed": 111, "applied_seed": 111},
        {"match_id": "match_2", "match_idx": 2, "match_dir": str(tmp_path / "logs" / "round_1" / "match_2"), "left_agent_id": "a3", "right_agent_id": "a4", "requested_seed": 222, "applied_seed": 222},
        {"match_id": "match_3", "match_idx": 3, "match_dir": str(tmp_path / "logs" / "round_1" / "match_3"), "left_agent_id": "a5", "right_agent_id": "a6", "requested_seed": 333, "applied_seed": 333},
    ]

    for agent_id in ["a1", "a3", "a5"]:
        write_feedback_package_for_agent(
            tournament_name=t,
            round_idx=round_idx,
            agent_id=agent_id,
            round_match_records=match_records,
            feedback_visibility="own_matches_plus_public_scoreboard",
        )

    errors, _warnings = audit_feedback_package(tournament_name=t)
    assert any("round_1 feedback packages incomplete: 3/6" in e for e in errors)

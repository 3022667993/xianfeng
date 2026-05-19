import hashlib
import json
import sys
from pathlib import Path

from scripts.audit_pommerman_initial_synthesis_3round_smoke import (
    audit_pommerman_initial_synthesis_3round_smoke,
    main as audit_initial_synthesis_3round_main,
)
from tests.test_pommerman_openclaw_adaptive_3round_smoke import _mk_fixture


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_main(codebase_dir: Path, text: str) -> None:
    p = codebase_dir / "submission" / "main.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _write_tournament_config(tmp_path: Path, filename: str, tournament_name: str) -> Path:
    cfg = tmp_path / "configs" / "tournaments" / filename
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(f"name: {tournament_name}\n", encoding="utf-8")
    return cfg


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


def test_initial_synthesis_3round_smoke_default_coached_config_main_passes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tournament_name = "pommerman_gptv16_a00_openclaw_initial_synthesis_3round_smoke"
    _mk_full_3round_initial_synthesis_fixture(tmp_path, tournament_name)
    _write_tournament_config(
        tmp_path,
        "pommerman_gptv16_a00_openclaw_initial_synthesis_3round_smoke.yaml",
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
    tournament_name = "pommerman_gptv16_a00_openclaw_initial_synthesis_3round_neutral_smoke"
    _mk_full_3round_initial_synthesis_fixture(tmp_path, tournament_name)
    cfg_path = _write_tournament_config(
        tmp_path,
        "pommerman_gptv16_a00_openclaw_initial_synthesis_3round_neutral_smoke.yaml",
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
    neutral_tournament_name = "pommerman_gptv16_a00_openclaw_initial_synthesis_3round_neutral_smoke"
    _mk_full_3round_initial_synthesis_fixture(tmp_path, neutral_tournament_name)
    neutral_cfg = _write_tournament_config(
        tmp_path,
        "pommerman_gptv16_a00_openclaw_initial_synthesis_3round_neutral_smoke.yaml",
        neutral_tournament_name,
    )
    errors, _warnings = audit_pommerman_initial_synthesis_3round_smoke(
        tournament_name="pommerman_gptv16_a00_openclaw_initial_synthesis_3round_smoke",
        tournament_config_path=neutral_cfg,
    )
    assert any("tournament_name mismatch with config" in e for e in errors)

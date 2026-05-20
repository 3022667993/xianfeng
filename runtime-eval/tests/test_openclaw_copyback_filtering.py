import json
import shutil
import sys
from pathlib import Path

from runner.core import openclaw_minimal as ocm


def _mk_base(tmp_path: Path) -> tuple[Path, Path]:
    codebase_post_dir = tmp_path / "codebase_post"
    (codebase_post_dir / "submission").mkdir(parents=True, exist_ok=True)
    (codebase_post_dir / "submission" / "main.py").write_text("AGGRESSION = 0\n", encoding="utf-8")
    (codebase_post_dir / "notes").mkdir(parents=True, exist_ok=True)
    (codebase_post_dir / "notes" / "revision_log.md").write_text("# Revision Log\n", encoding="utf-8")
    feedback_path = tmp_path / "feedback_package.json"
    feedback_path.write_text(json.dumps({"scorecard": {"left_right_winner": "draw"}}), encoding="utf-8")
    return codebase_post_dir, feedback_path


def _mk_response(model_token: str = "test-model") -> dict:
    return {
        "meta": {
            "systemPromptReport": {
                "injectedWorkspaceFiles": [],
                "tools": {"entries": [{"name": "read"}, {"name": "write"}, {"name": "edit"}, {"name": "exec"}]},
                "skills": {"promptChars": 0},
            },
            "executionTrace": {
                "winnerProvider": "relay",
                "winnerModel": model_token,
                "fallbackUsed": False,
            },
        }
    }


def _mutate_from_session_config(session_config_path: Path | None, mutator) -> None:
    assert session_config_path is not None
    config = json.loads(session_config_path.read_text(encoding="utf-8"))
    agent = next(entry for entry in config["agents"]["list"] if entry["id"] == "main")
    codebase_post_t_dir = Path(agent["workspace"])
    mutator(codebase_post_t_dir)


def _run_main_with_mutation(tmp_path: Path, monkeypatch, mutator):
    codebase_post_dir, feedback_path = _mk_base(tmp_path)

    def fake_run_openclaw_agent(
        message: str,
        *,
        agent_id: str,
        provider_model: str | None = None,
        session_id: str | None = None,
        session_state_dir: Path | None = None,
        session_config_path: Path | None = None,
    ):
        _ = session_id
        _ = session_state_dir
        _ = session_config_path
        _ = message
        _mutate_from_session_config(session_config_path, mutator)
        return _mk_response(), "", "", 0

    monkeypatch.setattr(ocm, "_run_openclaw_agent", fake_run_openclaw_agent)
    monkeypatch.setattr(
        ocm,
        "_run_submission_contract_validation",
        lambda _codebase_post_t_dir: (True, "submission contract validation passed on real Pommerman observation"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "openclaw_minimal.py",
            "--bootstrap",
            str(Path("runner/core/openclaw_minimal_bootstrap.txt").resolve()),
            "--codebase-post-dir",
            str(codebase_post_dir),
            "--feedback-path",
            str(feedback_path),
            "--side",
            "left",
            "--game",
            "pommerman_1v1",
            "--regime",
            "A00",
            "--agent-id",
            "main",
            "--provider-model",
            "relay/test-model",
        ],
    )
    ocm.main()
    audit = json.loads((codebase_post_dir / "revision_audit.json").read_text(encoding="utf-8"))
    run_dir = Path(audit["runDir"])
    if run_dir.exists():
        shutil.rmtree(run_dir)
    return codebase_post_dir, audit


def test_submission_and_pyc_changes_are_ignored_and_submission_copied(tmp_path, monkeypatch):
    def mutator(codebase_post_t_dir: Path):
        (codebase_post_t_dir / "submission" / "main.py").write_text("AGGRESSION = 1\n", encoding="utf-8")
        pyc = codebase_post_t_dir / "submission" / "__pycache__" / "main.cpython-310.pyc"
        pyc.parent.mkdir(parents=True, exist_ok=True)
        pyc.write_bytes(b"\x03\xf3\x0d\x0a")

    codebase_post_dir, audit = _run_main_with_mutation(tmp_path, monkeypatch, mutator)
    assert audit["success"] is True
    assert audit["disallowedChangedFiles"] == []
    assert "submission/main.py" in audit["changedFiles"]
    assert any(x.endswith(".pyc") for x in audit.get("ignoredChangedFiles", []))
    assert (codebase_post_dir / "submission" / "main.py").read_text(encoding="utf-8").strip() == "AGGRESSION = 1"


def test_submission_and_revision_log_changes_are_ignored_and_submission_copied(tmp_path, monkeypatch):
    def mutator(codebase_post_t_dir: Path):
        (codebase_post_t_dir / "submission" / "main.py").write_text("AGGRESSION = 1\n", encoding="utf-8")
        (codebase_post_t_dir / "notes" / "revision_log.md").write_text("changed by model\n", encoding="utf-8")

    codebase_post_dir, audit = _run_main_with_mutation(tmp_path, monkeypatch, mutator)
    assert audit["success"] is True
    assert audit["disallowedChangedFiles"] == []
    assert "submission/main.py" in audit["changedFiles"]
    assert "notes/revision_log.md" in audit.get("ignoredChangedFiles", [])
    assert (codebase_post_dir / "submission" / "main.py").read_text(encoding="utf-8").strip() == "AGGRESSION = 1"


def test_only_revision_log_change_counts_as_no_effect_submission_change(tmp_path, monkeypatch):
    def mutator(codebase_post_t_dir: Path):
        (codebase_post_t_dir / "notes" / "revision_log.md").write_text("changed by model\n", encoding="utf-8")

    codebase_post_dir, audit = _run_main_with_mutation(tmp_path, monkeypatch, mutator)
    assert audit["success"] is True
    assert audit["disallowedChangedFiles"] == []
    assert audit["changedFiles"] == []
    assert "notes/revision_log.md" in audit.get("ignoredChangedFiles", [])
    assert (codebase_post_dir / "submission" / "main.py").read_text(encoding="utf-8").strip() == "AGGRESSION = 0"


def test_scripts_change_is_disallowed_and_fails(tmp_path, monkeypatch):
    def mutator(codebase_post_t_dir: Path):
        bad = codebase_post_t_dir / "scripts" / "run_arena.sh"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text("#!/usr/bin/env bash\necho bad\n", encoding="utf-8")

    _codebase_post_dir, audit = _run_main_with_mutation(tmp_path, monkeypatch, mutator)
    assert audit["success"] is False
    assert "scripts/run_arena.sh" in audit["disallowedChangedFiles"]

import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

from runner.core import openclaw_minimal as ocm


class _Proc:
    def __init__(self, returncode=0, stdout='{"meta": {"systemPromptReport": {}}}', stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _openclaw_success_response(final_text: str | None = None):
    meta = {
        "systemPromptReport": {
            "workspaceDir": "/tmp/workspace",
            "injectedWorkspaceFiles": [],
            "tools": {"entries": [{"name": "read"}]},
            "skills": {"promptChars": 0},
        },
        "executionTrace": {
            "winnerProvider": "relay",
            "winnerModel": "test-model",
            "fallbackUsed": False,
        },
    }
    if final_text is not None:
        meta["finalAssistantVisibleText"] = final_text
    return {"meta": meta}


def test_run_openclaw_agent_includes_model_when_provider_model_supplied(monkeypatch):
    calls = []

    def fake_which(exe):
        return "/usr/bin/" + exe

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _Proc()

    monkeypatch.setattr(ocm.shutil, "which", fake_which)
    monkeypatch.setattr(ocm.subprocess, "run", fake_run)

    _resp, _out, _err, code = ocm._run_openclaw_agent(
        "msg",
        agent_id="main",
        provider_model="bailian/deepseek-v4-flash",
    )
    assert code == 0
    assert any("--model" in c for c in calls)
    assert any("bailian/deepseek-v4-flash" in c for c in calls)


def test_run_openclaw_agent_omits_model_when_provider_model_none(monkeypatch):
    calls = []

    def fake_which(exe):
        return "/usr/bin/" + exe

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _Proc()

    monkeypatch.setattr(ocm.shutil, "which", fake_which)
    monkeypatch.setattr(ocm.subprocess, "run", fake_run)

    _resp, _out, _err, code = ocm._run_openclaw_agent("msg", agent_id="main", provider_model=None)
    assert code == 0
    assert all("--model" not in c for c in calls)


def test_run_openclaw_agent_passes_unique_session_and_isolated_env(monkeypatch, tmp_path):
    calls = []
    envs = []

    def fake_which(exe):
        return "/usr/bin/" + exe

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        envs.append(kwargs.get("env", {}))
        return _Proc()

    monkeypatch.setattr(ocm.shutil, "which", fake_which)
    monkeypatch.setattr(ocm.subprocess, "run", fake_run)
    session_state_dir = tmp_path / "state_a"
    session_config_path = tmp_path / "state_a" / "openclaw.json"

    _resp, _out, _err, code = ocm._run_openclaw_agent(
        "msg",
        agent_id="main",
        provider_model="relay/qwen3.5-plus",
        session_id="session_123",
        session_state_dir=session_state_dir,
        session_config_path=session_config_path,
    )
    assert code == 0
    assert any("--session-id" in c for c in calls)
    assert any("session_123" in c for c in calls)
    assert envs
    assert all(e.get("OPENCLAW_STATE_DIR") == str(session_state_dir) for e in envs)
    assert all(e.get("OPENCLAW_CONFIG_PATH") == str(session_config_path) for e in envs)


def test_main_sets_openclaw_workspace_to_per_run_codebase(monkeypatch, tmp_path, capsys):
    codebase = tmp_path / "codebase_post"
    (codebase / "submission").mkdir(parents=True)
    (codebase / "submission" / "main.py").write_text("AGGRESSION = 0\n", encoding="utf-8")
    (codebase / "notes").mkdir()
    (codebase / "notes" / "revision_log.md").write_text("# log\n", encoding="utf-8")
    captured = {}

    def fake_run_openclaw_agent(
        message: str,
        *,
        agent_id: str,
        provider_model: str | None = None,
        session_id: str | None = None,
        session_state_dir: Path | None = None,
        session_config_path: Path | None = None,
    ):
        _ = message
        _ = provider_model
        _ = session_id
        _ = session_state_dir
        assert session_config_path is not None
        config = json.loads(session_config_path.read_text(encoding="utf-8"))
        agent = next(entry for entry in config["agents"]["list"] if entry["id"] == agent_id)
        workspace = Path(agent["workspace"])
        captured["workspace"] = workspace
        assert config["agents"]["defaults"]["workspace"] == str(workspace)
        assert config["tools"]["fs"]["workspaceOnly"] is True
        assert workspace.name == "codebase_post_t"
        (workspace / "submission" / "main.py").write_text("AGGRESSION = 1\n", encoding="utf-8")
        return (
            {
                "meta": {
                    "systemPromptReport": {
                        "workspaceDir": str(workspace),
                        "injectedWorkspaceFiles": [],
                        "tools": {"entries": [{"name": "read"}, {"name": "write"}]},
                        "skills": {"promptChars": 0},
                    },
                    "executionTrace": {
                        "winnerProvider": "relay",
                        "winnerModel": "test-model",
                        "fallbackUsed": False,
                    },
                }
            },
            "",
            "",
            0,
        )

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
            "--mode",
            "initial_synthesis",
            "--bootstrap",
            str(Path("runner/core/openclaw_minimal_bootstrap.txt").resolve()),
            "--codebase-post-dir",
            str(codebase),
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
    result = json.loads(capsys.readouterr().out)
    audit = json.loads((codebase / "revision_audit.json").read_text(encoding="utf-8"))
    assert result["success"] is True
    assert audit["openclawWorkspaceDir"] == str(captured["workspace"])
    assert audit["systemPromptReport"]["workspaceDir"] == str(captured["workspace"])
    assert (codebase / "submission" / "main.py").read_text(encoding="utf-8").strip() == "AGGRESSION = 1"


def test_extract_context_overflow_metadata_parses_tokens_and_budget():
    payload = {
        "meta": {
            "error": {"kind": "context_overflow"},
        }
    }
    stderr = (
        "[context-overflow-precheck] estimatedPromptTokens=117,533 "
        "promptBudgetBeforeReserve=108,000"
    )
    meta = ocm._extract_context_overflow_metadata(payload, stdout="", stderr=stderr)
    assert meta["context_overflow_detected"] is True
    assert meta["prompt_estimated_tokens"] == 117533
    assert meta["prompt_budget_before_reserve"] == 108000


def test_extract_context_overflow_metadata_detects_without_meta_error_kind():
    meta = ocm._extract_context_overflow_metadata(
        None,
        stdout="Context overflow: prompt too large for the model (precheck).",
        stderr="",
    )
    assert meta["context_overflow_detected"] is True


def test_revision_message_includes_feedback_and_effective_change_requirements():
    msg = ocm._make_revision_message(
        bootstrap_text="BOOT",
        run_dir=Path("/tmp/run"),
        codebase_post_t_dir=Path("/tmp/run/codebase_post_t"),
        feedback_copy_path=Path("/tmp/run/feedback_package.json"),
        feedback_package_path=Path("/tmp/run/codebase_post_t/feedback/round_1"),
        side="left",
        game="pommerman_1v1",
        regime="A00",
        retry_on_noop=True,
    )
    assert "Read feedback from" in msg
    assert "Use the feedback package at" in msg
    assert "Valid revision outcomes:" in msg
    assert "Modify: read feedback evidence, read `submission/main.py`" in msg
    assert "Intentional no-change: read feedback evidence, read or inspect `submission/main.py`" in msg
    assert "REVISION_DECISION: no_change" in msg
    assert "RATIONALE: <why keeping current code is preferable>" in msg
    assert "EVIDENCE_USED: <feedback files or evidence considered>" in msg
    assert "Previous attempt neither modified submission/main.py nor provided a valid intentional no-change decision" in msg
    assert "You must either modify submission/main.py or explicitly return `REVISION_DECISION: no_change`" in msg
    assert "Empty response or directory listing is not sufficient" in msg
    assert "Treat 800-step draw outcomes as a failure signal." in msg
    assert "what anti-draw behavior was added" in msg
    assert "what safety guard prevents suicide" in msg


def test_revision_message_renders_extra_artifact_paths():
    msg = ocm._make_revision_message(
        bootstrap_text="BOOT",
        run_dir=Path("/tmp/run"),
        codebase_post_t_dir=Path("/tmp/run/codebase_post_t"),
        feedback_copy_path=Path("/tmp/run/feedback_package.json"),
        side="left",
        game="pommerman_1v1",
        regime="A00",
        extra_artifact_paths=["/tmp/run/match/scorecard.json", "/tmp/run/match/trajectory_summary.json"],
    )
    assert "additional round artifacts provided by runner" in msg
    assert "/tmp/run/match/scorecard.json" in msg


def test_initial_synthesis_message_includes_strategy_profile():
    msg = ocm._make_initial_synthesis_message(
        bootstrap_text="BOOT",
        run_dir=Path("/tmp/run"),
        codebase_post_t_dir=Path("/tmp/run/codebase_post_t"),
        game="pommerman_1v1",
        regime="A00",
        strategy_profile_id="safe_opponent_pressure",
        strategy_profile_text="Apply pressure when safe.",
    )
    assert "assigned strategy profile id: safe_opponent_pressure" in msg
    assert "Apply pressure when safe." in msg
    assert "Do not copy a generic template unchanged" in msg
    assert "Treat 800-step draw behavior as a failure mode to avoid in design." in msg
    assert "reduce STOP usage unless unsafe" in msg


def test_neutral_revision_message_omits_coached_tactics_but_keeps_constraints():
    msg = ocm._make_revision_message(
        bootstrap_text="BOOT",
        run_dir=Path("/tmp/run"),
        codebase_post_t_dir=Path("/tmp/run/codebase_post_t"),
        feedback_copy_path=Path("/tmp/run/feedback_package.json"),
        feedback_package_path=Path("/tmp/run/codebase_post_t/feedback/round_1"),
        side="left",
        game="pommerman_1v1",
        regime="A00",
        retry_on_noop=True,
        prompt_variant="neutral",
    )
    assert "Read feedback from" not in msg
    assert "feedback/round_1" in msg
    assert "Valid revision outcomes:" in msg
    assert "Modify: read feedback evidence, read `submission/main.py`" in msg
    assert "Intentional no-change: read feedback evidence, read or inspect `submission/main.py`" in msg
    assert "REVISION_DECISION: no_change" in msg
    assert "RATIONALE: <why keeping current code is preferable>" in msg
    assert "EVIDENCE_USED: <feedback files or evidence considered>" in msg
    assert "You must either modify submission/main.py or explicitly return `REVISION_DECISION: no_change`" in msg
    assert "Empty response or directory listing is not sufficient" in msg
    assert "Editable target for the Modify outcome:" in msg
    assert "Open and edit exactly: `submission/main.py`." in msg
    assert "This path is relative to the per-run codebase workspace." in msg
    assert "This is the only submission source file whose changes will be collected by the runner." in msg
    assert "First read `submission/main.py`, then edit or rewrite it." in msg
    assert "If the edit tool fails because oldText does not match, use the write tool to overwrite `submission/main.py`" in msg
    assert "Metadata-only edits do not count as a valid revision." in msg
    assert "Empty responses, merely listing files, and incomplete turns are not valid no-change decisions." in msg
    assert "/tmp/run/codebase_post_t/submission/main.py" not in msg
    assert "Do not use an absolute path." not in msg
    assert "Do not prefix the path with `codebase_post_t/`." not in msg
    assert "Objective: improve expected future tournament outcome under the provided feedback package and constraints." in msg
    assert "feedback package, public scoreboard, match replay evidence, action logs, and run logs as evidence" in msg
    assert "Then either update `submission/main.py` with a concrete strategy or behavior change" in msg
    assert "or explicitly choose intentional no-change using the required structured decision lines" in msg
    assert "future decisive tournament outcomes against opponents" in msg
    assert "Prefer robust wins over draws, and draws over losses." in msg
    assert "robust, consistent, or resilient" in msg
    assert "timeout draw is a weak outcome when no submitted opponent is eliminated" in msg
    assert "Early self-elimination is unfavorable" in msg
    assert "dummy/background-agent win" in msg
    assert "both submitted agents lost to a dummy/background agent" in msg
    assert "opponent's self-destruction" in msg
    assert "not strong evidence of a robust strategy" in msg
    assert "`submitted_pair_outcome`" in msg
    assert "feedback package is evidence, not a hand-authored strategy script" in msg
    assert "real Pommerman observations containing NumPy arrays" in msg
    assert "do not treat NumPy arrays as booleans" in msg
    assert 'Do not assume `obs["agent_id"]` exists' in msg
    assert "Preserve `from pommerman import agents`, `make_agent()`, and `pommerman.agents.BaseAgent` inheritance." in msg
    assert "return a valid fallback action in `[0, 5]`" in msg
    assert "Previous attempt neither modified submission/main.py nor provided a valid intentional no-change decision" in msg
    assert "center when safe" not in msg
    assert "center movement" not in msg
    assert "clear wood for powerups" not in msg
    assert "wood clearing" not in msg
    assert "powerups" not in msg
    assert "pressure opponent when nearby and safe" not in msg
    assert "opponent pressure" not in msg
    assert "reduce STOP usage unless unsafe" not in msg
    assert "safe aggression" not in msg
    assert "bomb more" not in msg
    assert "go to center" not in msg
    assert "chase opponent" not in msg
    assert "attack with bombs" not in msg
    assert "rush" not in msg
    assert "corner trapping" not in msg
    assert "what anti-draw behavior was added" not in msg


def test_neutral_initial_synthesis_message_omits_coached_tactics_but_keeps_constraints():
    msg = ocm._make_initial_synthesis_message(
        bootstrap_text="BOOT",
        run_dir=Path("/tmp/run"),
        codebase_post_t_dir=Path("/tmp/run/codebase_post_t"),
        game="pommerman_1v1",
        regime="A00",
        strategy_profile_id="profile_a",
        strategy_profile_text="Profile text.",
        prompt_variant="neutral",
    )
    assert "assigned strategy profile id: profile_a" in msg
    assert "starter `submission/main.py` is intentionally minimal" in msg
    assert "only provides the required API plus a valid fallback action" in msg
    assert "make_agent()` returning an instance of a class that subclasses `pommerman.agents.BaseAgent`" in msg
    assert "Preserve `from pommerman import agents`, a valid `make_agent()` entry point, and `pommerman.agents.BaseAgent` inheritance." in msg
    assert "Replace the minimal fallback with a concrete strategy or behavior implementation" in msg
    assert "Objective: improve expected future tournament outcome while preserving valid actions" in msg
    assert "Prefer robust wins over draws, and draws over losses." in msg
    assert "concrete behavior or strategy" in msg
    assert "future decisive outcomes against opponents" in msg
    assert "timeout draw is a weak outcome when no submitted opponent is eliminated" in msg
    assert "Early self-elimination is unfavorable" in msg
    assert "dummy/background-agent win" in msg
    assert "both-submitted-lost-to-dummy outcome" in msg
    assert "opponent's self-destruction" in msg
    assert "not strong evidence of a robust strategy" in msg
    assert "preserving validity and avoiding obvious self-destruction" in msg
    assert "Editable target:" in msg
    assert "Open and edit exactly: `submission/main.py`." in msg
    assert "This path is relative to the per-run codebase workspace." in msg
    assert "This is the only submission source file whose changes will be collected by the runner." in msg
    assert "First read `submission/main.py`, then edit or rewrite it." in msg
    assert "If the edit tool fails because oldText does not match, use the write tool to overwrite `submission/main.py`" in msg
    assert "Do not finish until `submission/main.py` has actually changed." in msg
    assert "/tmp/run/codebase_post_t/submission/main.py" not in msg
    assert "Do not use an absolute path." not in msg
    assert "Do not prefix the path with `codebase_post_t/`." not in msg
    assert "real Pommerman observations containing NumPy arrays" in msg
    assert "do not treat NumPy arrays as booleans" in msg
    assert 'Do not assume `obs["agent_id"]` exists' in msg
    assert "return a valid fallback action in `[0, 5]`" in msg
    assert "You must edit submission/main.py." in msg
    assert "Do not modify scripts/run_arena.sh, scripts/build.sh, tests, configs, or metadata files." in msg
    assert "center when safe" not in msg
    assert "center movement" not in msg
    assert "clear wood for powerups" not in msg
    assert "wood clearing" not in msg
    assert "powerups" not in msg
    assert "pressure nearby opponents when safe" not in msg
    assert "opponent pressure" not in msg
    assert "reduce STOP usage unless unsafe" not in msg
    assert "safe aggression" not in msg
    assert "bomb more" not in msg
    assert "go to center" not in msg
    assert "chase opponent" not in msg
    assert "attack with bombs" not in msg
    assert "rush" not in msg
    assert "corner trapping" not in msg
    assert "what anti-draw behavior was added" not in msg


def test_initial_synthesis_message_does_not_reference_feedback_package_paths():
    msg = ocm._make_initial_synthesis_message(
        bootstrap_text="BOOT",
        run_dir=Path("/tmp/run"),
        codebase_post_t_dir=Path("/tmp/run/codebase_post_t"),
        game="pommerman_1v1",
        regime="A00",
        strategy_profile_id="profile_a",
        strategy_profile_text="Profile text.",
        prompt_variant="neutral",
    )
    assert "feedback package" not in msg.lower()
    assert "feedback/round_" not in msg
    assert "agent_feedback_" not in msg
    assert "trajectory_summary.json" not in msg


def _run_revision_main_with_final_text(monkeypatch, tmp_path, capsys, final_text: str | None, *, mutate=None):
    codebase = tmp_path / "codebase_post"
    (codebase / "submission").mkdir(parents=True)
    (codebase / "submission" / "main.py").write_text("AGGRESSION = 0\n", encoding="utf-8")
    (codebase / "notes").mkdir()
    (codebase / "notes" / "revision_log.md").write_text("# log\n", encoding="utf-8")

    def fake_run_openclaw_agent(message: str, **kwargs):
        _ = message
        if mutate is not None:
            session_config_path = kwargs.get("session_config_path")
            config = json.loads(Path(session_config_path).read_text(encoding="utf-8"))
            workspace = Path(config["agents"]["defaults"]["workspace"])
            mutate(workspace)
        return (_openclaw_success_response(final_text), "", "", 0)

    monkeypatch.setattr(ocm, "_run_openclaw_agent", fake_run_openclaw_agent)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "openclaw_minimal.py",
            "--mode",
            "revision",
            "--bootstrap",
            str(Path("runner/core/openclaw_minimal_bootstrap.txt").resolve()),
            "--codebase-post-dir",
            str(codebase),
            "--side",
            "left",
            "--game",
            "test_game",
            "--regime",
            "A00",
            "--agent-id",
            "main",
            "--provider-model",
            "relay/test-model",
        ],
    )
    ocm.main()
    result = json.loads(capsys.readouterr().out)
    audit = json.loads((codebase / "revision_audit.json").read_text(encoding="utf-8"))
    run_dir = Path(audit["runDir"])
    if run_dir.exists():
        shutil.rmtree(run_dir)
    return result, audit


def test_revision_main_accepts_valid_intentional_no_change(monkeypatch, tmp_path, capsys):
    final_text = (
        "REVISION_DECISION: no_change\n"
        "RATIONALE: The current code should be preserved for this evidence.\n"
        "EVIDENCE_USED: feedback README and public scoreboard.\n"
    )
    result, audit = _run_revision_main_with_final_text(monkeypatch, tmp_path, capsys, final_text)
    assert result["success"] is True
    assert result["changed"] is False
    assert result["revision_decision"] == "intentional_no_change"
    assert result["intentional_no_change"] is True
    assert audit["revisionDecision"] == "intentional_no_change"
    assert audit["intentionalNoChange"] is True
    assert audit["noChangeRationale"] == "The current code should be preserved for this evidence."
    assert audit["noChangeEvidenceUsed"] == "feedback README and public scoreboard."


def test_revision_main_rejects_empty_assistant_output_as_no_effect(monkeypatch, tmp_path, capsys):
    result, audit = _run_revision_main_with_final_text(monkeypatch, tmp_path, capsys, "")
    assert result["success"] is True
    assert result["changed"] is False
    assert result["revision_decision"] == "no_effect"
    assert result["intentional_no_change"] is False
    assert audit["revisionDecision"] == "no_effect"
    assert audit["intentionalNoChange"] is False


def test_revision_main_rejects_incomplete_no_change_marker(monkeypatch, tmp_path, capsys):
    final_text = "REVISION_DECISION: no_change\nEVIDENCE_USED: scoreboard\n"
    result, audit = _run_revision_main_with_final_text(monkeypatch, tmp_path, capsys, final_text)
    assert result["revision_decision"] == "no_effect"
    assert result["intentional_no_change"] is False
    assert audit["intentionalNoChange"] is False


def test_revision_main_rejects_metadata_only_change_as_intentional_no_change(monkeypatch, tmp_path, capsys):
    final_text = (
        "REVISION_DECISION: no_change\n"
        "RATIONALE: Keep current behavior.\n"
        "EVIDENCE_USED: scoreboard.\n"
    )

    def mutate(codebase: Path):
        (codebase / "notes" / "model_note.md").write_text("metadata only\n", encoding="utf-8")

    result, audit = _run_revision_main_with_final_text(monkeypatch, tmp_path, capsys, final_text, mutate=mutate)
    assert result["success"] is False
    assert result["revision_decision"] == "failed"
    assert result["intentional_no_change"] is False
    assert audit["intentionalNoChange"] is False
    assert "notes/model_note.md" in audit["disallowedChangedFiles"]


def test_submission_contract_validation_reports_real_observation_failures(monkeypatch, tmp_path):
    codebase = tmp_path / "codebase_post_t"
    (codebase / "tests").mkdir(parents=True)
    (codebase / "tests" / "smoke.sh").write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")

    def fake_run(*args, **kwargs):
        return _Proc(
            returncode=1,
            stdout="",
            stderr="ValueError: The truth value of a numpy array with more than one element is ambiguous",
        )

    monkeypatch.setattr(ocm.subprocess, "run", fake_run)

    ok, msg = ocm._run_submission_contract_validation(codebase)
    assert not ok
    assert "submission contract validation failed on real Pommerman observation" in msg
    assert "truth value of a numpy array" in msg


def test_submission_contract_validation_success_message(monkeypatch, tmp_path):
    codebase = tmp_path / "codebase_post_t"
    (codebase / "tests").mkdir(parents=True)
    (codebase / "tests" / "smoke.sh").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

    def fake_run(*args, **kwargs):
        return _Proc(returncode=0, stdout="[smoke] starter repo contract OK", stderr="")

    monkeypatch.setattr(ocm.subprocess, "run", fake_run)

    ok, msg = ocm._run_submission_contract_validation(codebase)
    assert ok
    assert msg == "submission contract validation passed on real Pommerman observation"


def test_wrong_root_submission_edit_fails_closed_with_diagnostic(monkeypatch, tmp_path, capsys):
    codebase = tmp_path / "codebase_post"
    (codebase / "submission").mkdir(parents=True)
    (codebase / "submission" / "main.py").write_text("AGGRESSION = 0\n", encoding="utf-8")
    (codebase / "notes").mkdir()
    (codebase / "notes" / "revision_log.md").write_text("# log\n", encoding="utf-8")

    wrong_root = Path("/root/autodl-tmp/runtime-eval/openclaw_workspaces/minimal/submission")
    if wrong_root.exists():
        shutil.rmtree(wrong_root)
    run_dir_to_cleanup: Path | None = None

    def fake_run_openclaw_agent(*args, **kwargs):
        wrong_root.mkdir(parents=True, exist_ok=True)
        (wrong_root / "main.py").write_text("AGGRESSION = 1\n", encoding="utf-8")
        return (
            {
                "meta": {
                    "systemPromptReport": {
                        "injectedWorkspaceFiles": [],
                        "tools": {"entries": [{"name": "read"}, {"name": "write"}]},
                        "skills": {"promptChars": 0},
                    },
                    "executionTrace": {
                        "winnerProvider": "relay",
                        "winnerModel": "test-model",
                        "fallbackUsed": False,
                    },
                }
            },
            "",
            "",
            0,
        )

    monkeypatch.setattr(ocm, "_run_openclaw_agent", fake_run_openclaw_agent)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "openclaw_minimal.py",
            "--mode",
            "initial_synthesis",
            "--bootstrap",
            str(Path("runner/core/openclaw_minimal_bootstrap.txt").resolve()),
            "--codebase-post-dir",
            str(codebase),
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
    try:
        ocm.main()
        result = json.loads(capsys.readouterr().out)
        audit = json.loads((codebase / "revision_audit.json").read_text(encoding="utf-8"))
        run_dir_to_cleanup = Path(audit["runDir"])
        diagnostic = "OpenClaw may have edited workspace-root submission/main.py instead of the per-run codebase_post_t target."
        assert result["success"] is False
        assert diagnostic in result["audit_errors"]
        assert diagnostic in result["audit_warnings"]
        assert diagnostic in audit["errors"]
        assert audit["wrongRootSubmissionChanges"] == ["main.py"]
        assert audit["changedFiles"] == []
    finally:
        if wrong_root.exists():
            shutil.rmtree(wrong_root)
        if run_dir_to_cleanup is not None and run_dir_to_cleanup.exists():
            shutil.rmtree(run_dir_to_cleanup)


def test_misplaced_runtime_eval_runs_submission_is_reported(monkeypatch, tmp_path, capsys):
    codebase = tmp_path / "codebase_post"
    (codebase / "submission").mkdir(parents=True)
    (codebase / "submission" / "main.py").write_text("AGGRESSION = 0\n", encoding="utf-8")
    (codebase / "notes").mkdir()
    (codebase / "notes" / "revision_log.md").write_text("# log\n", encoding="utf-8")
    misplaced_root = Path("/root/autodl-tmp/runtime_eval_runs")
    run_dir_to_cleanup: Path | None = None
    misplaced_dir_to_cleanup: Path | None = None

    def fake_run_openclaw_agent(
        message: str,
        *,
        agent_id: str,
        provider_model: str | None = None,
        session_id: str | None = None,
        session_state_dir: Path | None = None,
        session_config_path: Path | None = None,
    ):
        _ = message
        _ = agent_id
        _ = provider_model
        _ = session_id
        _ = session_state_dir
        nonlocal misplaced_dir_to_cleanup
        assert session_config_path is not None
        config = json.loads(session_config_path.read_text(encoding="utf-8"))
        workspace = Path(config["agents"]["defaults"]["workspace"])
        run_id = workspace.parent.name
        misplaced = misplaced_root / run_id / "codebase_post_t" / "submission"
        misplaced.mkdir(parents=True, exist_ok=True)
        misplaced_dir_to_cleanup = misplaced_root / run_id
        (misplaced / "main.py").write_text("AGGRESSION = 1\n", encoding="utf-8")
        return (
            {
                "meta": {
                    "systemPromptReport": {
                        "workspaceDir": str(workspace),
                        "injectedWorkspaceFiles": [],
                        "tools": {"entries": [{"name": "read"}, {"name": "write"}]},
                        "skills": {"promptChars": 0},
                    },
                    "executionTrace": {
                        "winnerProvider": "relay",
                        "winnerModel": "test-model",
                        "fallbackUsed": False,
                    },
                }
            },
            "",
            "",
            0,
        )

    monkeypatch.setattr(ocm, "_run_openclaw_agent", fake_run_openclaw_agent)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "openclaw_minimal.py",
            "--mode",
            "initial_synthesis",
            "--bootstrap",
            str(Path("runner/core/openclaw_minimal_bootstrap.txt").resolve()),
            "--codebase-post-dir",
            str(codebase),
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
    try:
        ocm.main()
        result = json.loads(capsys.readouterr().out)
        audit = json.loads((codebase / "revision_audit.json").read_text(encoding="utf-8"))
        run_dir_to_cleanup = Path(audit["runDir"])
        diagnostic = "OpenClaw may have edited a misplaced submission/main.py outside the per-run codebase workspace."
        assert result["success"] is False
        assert diagnostic in result["audit_errors"]
        assert diagnostic in result["audit_warnings"]
        assert any("/root/autodl-tmp/runtime_eval_runs/" in p for p in result["misplaced_submission_paths"])
        assert audit["misplacedSubmissionPaths"] == result["misplaced_submission_paths"]
        assert audit["runDirPreserved"] is True
    finally:
        if misplaced_dir_to_cleanup is not None and misplaced_dir_to_cleanup.exists():
            shutil.rmtree(misplaced_dir_to_cleanup)
        if run_dir_to_cleanup is not None and run_dir_to_cleanup.exists():
            shutil.rmtree(run_dir_to_cleanup)


def test_bootstrap_file_no_longer_contains_stale_aggression_task():
    bootstrap = Path("runner/core/openclaw_minimal_bootstrap.txt").read_text(encoding="utf-8")
    assert "toggle AGGRESSION between 0 and 1" not in bootstrap
    assert "scorecard.left_right_winner" not in bootstrap
    assert "append/update codebase_post_t/notes/revision_log.md" not in bootstrap
    assert "only submission/main.py inside the per-run codebase workspace" in bootstrap
    assert "only codebase_post_t/submission/main.py" not in bootstrap

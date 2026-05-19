from pathlib import Path
from types import SimpleNamespace

from runner.core import openclaw_minimal as ocm
from scripts.audit_pommerman_openclaw_revision_smoke import audit_openclaw_revision_smoke


class _Proc:
    def __init__(self, returncode=0, stdout='{"meta": {"systemPromptReport": {}}}', stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


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
    assert "You must modify submission/main.py" in msg
    assert "Previous attempt made no submitted-code change" in msg
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
    assert "You must modify submission/main.py" in msg
    assert "Objective: improve expected future match performance" in msg
    assert "If previous matches ended in draw" in msg
    assert "Previous attempt made no submitted-code change" in msg
    assert "center when safe" not in msg
    assert "clear wood for powerups" not in msg
    assert "pressure opponent when nearby and safe" not in msg
    assert "reduce STOP usage unless unsafe" not in msg
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
    assert "Objective: improve expected future match performance" in msg
    assert "If early outcomes are likely to be draws" in msg
    assert "You must edit submission/main.py." in msg
    assert "Do not modify scripts/run_arena.sh, scripts/build.sh, tests, configs, or metadata files." in msg
    assert "center when safe" not in msg
    assert "clear wood for powerups" not in msg
    assert "pressure nearby opponents when safe" not in msg
    assert "reduce STOP usage unless unsafe" not in msg
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


def test_bootstrap_file_no_longer_contains_stale_aggression_task():
    bootstrap = Path("runner/core/openclaw_minimal_bootstrap.txt").read_text(encoding="utf-8")
    assert "toggle AGGRESSION between 0 and 1" not in bootstrap
    assert "scorecard.left_right_winner" not in bootstrap
    assert "append/update codebase_post_t/notes/revision_log.md" not in bootstrap


def test_provider_route_mismatch_still_fails_openclaw_revision_smoke_audit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    t = "pommerman_gptv16_a00_openclaw_revision_smoke"
    for root in ["codebases", "submissions", "posts"]:
        for a in ["a1", "a2", "a3", "a4", "a5", "a6"]:
            (tmp_path / "workspace" / root / t / a).mkdir(parents=True, exist_ok=True)

    rd = tmp_path / "logs" / "round_1"
    rd.mkdir(parents=True, exist_ok=True)
    matches = []
    for idx, (l, r) in enumerate([("a1", "a2"), ("a3", "a4"), ("a5", "a6")], start=1):
        md = rd / f"match_{idx}"
        md.mkdir(parents=True, exist_ok=True)
        for n in ["metadata.json", "scorecard.json", "arena_result_match_a.json", "arena_result_match_b.json"]:
            (md / n).write_text("{}", encoding="utf-8")
        matches.append(
            {
                "match_id": f"match_{idx}",
                "match_idx": idx,
                "pair_id": "__vs__".join(sorted([l, r])),
                "left_agent_id": l,
                "right_agent_id": r,
                "requested_seed": 1000 + idx,
                "applied_seed": None,
                "seed": None,
                "seed_control_status": "requested_but_not_applied",
                "background_agents": ["dummy2", "dummy3"],
                "metadata_path": str(md / "metadata.json"),
                "scorecard_path": str(md / "scorecard.json"),
                "arena_result_match_a_path": str(md / "arena_result_match_a.json"),
                "arena_result_match_b_path": str(md / "arena_result_match_b.json"),
            }
        )
    (rd / "round_manifest.json").write_text(
        __import__("json").dumps(
            {
                "round_idx": 1,
                "matches_per_round": 3,
                "scorecard_policy": "raw_per_match_scorecard; pair-level aggregation is post-analysis",
                "matches": matches,
            }
        ),
        encoding="utf-8",
    )
    rev = {
        "agents": [
            {
                "agent_id": "a1",
                "revision_attempted": True,
                "revision_executor": "openclaw-minimal",
                "revision_status": "ok",
                "revision_ok": True,
                "openclaw_invoked": True,
                "fallback_used": False,
                "provider_route_status": "mismatch",
            },
            *[
                {
                    "agent_id": a,
                    "revision_attempted": False,
                    "revision_executor": "skipped_by_budget_guard",
                    "revision_status": "skipped_by_budget_guard",
                    "revision_ok": False,
                    "openclaw_invoked": False,
                    "fallback_used": False,
                }
                for a in ["a2", "a3", "a4", "a5", "a6"]
            ],
        ]
    }
    (rd / "revision_manifest.json").write_text(__import__("json").dumps(rev), encoding="utf-8")

    errors, _warnings = audit_openclaw_revision_smoke(t)
    assert any("provider route mismatch" in e for e in errors)


def test_provider_route_matched_passes_openclaw_revision_smoke_audit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    t = "pommerman_gptv16_a00_openclaw_revision_smoke"
    for root in ["codebases", "submissions", "posts"]:
        for a in ["a1", "a2", "a3", "a4", "a5", "a6"]:
            (tmp_path / "workspace" / root / t / a).mkdir(parents=True, exist_ok=True)

    rd = tmp_path / "logs" / "round_1"
    rd.mkdir(parents=True, exist_ok=True)
    matches = []
    for idx, (l, r) in enumerate([("a1", "a2"), ("a3", "a4"), ("a5", "a6")], start=1):
        md = rd / f"match_{idx}"
        md.mkdir(parents=True, exist_ok=True)
        for n in ["metadata.json", "scorecard.json", "arena_result_match_a.json", "arena_result_match_b.json"]:
            (md / n).write_text("{}", encoding="utf-8")
        matches.append(
            {
                "match_id": f"match_{idx}",
                "match_idx": idx,
                "pair_id": "__vs__".join(sorted([l, r])),
                "left_agent_id": l,
                "right_agent_id": r,
                "requested_seed": 1000 + idx,
                "applied_seed": None,
                "seed": None,
                "seed_control_status": "requested_but_not_applied",
                "background_agents": ["dummy2", "dummy3"],
                "metadata_path": str(md / "metadata.json"),
                "scorecard_path": str(md / "scorecard.json"),
                "arena_result_match_a_path": str(md / "arena_result_match_a.json"),
                "arena_result_match_b_path": str(md / "arena_result_match_b.json"),
            }
        )
    (rd / "round_manifest.json").write_text(
        __import__("json").dumps(
            {
                "round_idx": 1,
                "matches_per_round": 3,
                "scorecard_policy": "raw_per_match_scorecard; pair-level aggregation is post-analysis",
                "matches": matches,
            }
        ),
        encoding="utf-8",
    )
    rev = {
        "agents": [
            {
                "agent_id": "a1",
                "revision_attempted": True,
                "revision_executor": "openclaw-minimal",
                "revision_status": "ok",
                "revision_ok": True,
                "openclaw_invoked": True,
                "fallback_used": False,
                "provider_route_status": "matched",
            },
            *[
                {
                    "agent_id": a,
                    "revision_attempted": False,
                    "revision_executor": "skipped_by_budget_guard",
                    "revision_status": "skipped_by_budget_guard",
                    "revision_ok": False,
                    "openclaw_invoked": False,
                    "fallback_used": False,
                }
                for a in ["a2", "a3", "a4", "a5", "a6"]
            ],
        ]
    }
    (rd / "revision_manifest.json").write_text(__import__("json").dumps(rev), encoding="utf-8")

    errors, _warnings = audit_openclaw_revision_smoke(t)
    assert errors == []

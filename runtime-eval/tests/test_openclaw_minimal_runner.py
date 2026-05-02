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

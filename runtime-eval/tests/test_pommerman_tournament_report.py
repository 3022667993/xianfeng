import os
import json
import subprocess
import sys
from pathlib import Path

from runner.core.pommerman_tournament_report import write_tournament_report


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_tournament_report_writes_json_and_md(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    t = "t_report"

    rd = tmp_path / "logs" / "round_1"
    md = rd / "match_1"
    md.mkdir(parents=True, exist_ok=True)
    _write_json(md / "arena_result_match_a.json", {"steps": 2, "reward": [0, 0, 0, 0], "left_right_winner": "draw"})
    _write_json(md / "arena_result_match_b.json", {"steps": 2, "reward": [0, 0, 0, 0], "left_right_winner": "draw"})
    _write_json(md / "metadata.json", {"left_agent_id": "a1", "right_agent_id": "a2", "applied_seed": 123, "requested_seed": 123})

    _write_json(
        rd / "round_manifest.json",
        {
            "round_idx": 1,
            "matches": [
                {"match_id": "match_1", "match_idx": 1, "left_agent_id": "a1", "right_agent_id": "a2", "applied_seed": 123},
            ],
            "revision_prompt_variant": "neutral",
            "initial_synthesis_prompt_variant": "neutral",
            "feedback_package_variant": "codeclash_v3",
            "feedback_visibility": "own_matches_plus_public_scoreboard",
        },
    )
    _write_json(
        rd / "revision_manifest.json",
        {
            "agents": [
                {
                    "agent_id": "a1",
                    "revision_attempted": True,
                    "revision_ok": True,
                    "provider_route_status": "matched",
                    "fallback_used": False,
                    "effective_submission_changed": True,
                    "submission_main_sha256_before": "0" * 64,
                    "submission_main_sha256_after": "1" * 64,
                    "changed_files_hash_based": ["submission/main.py"],
                }
            ]
        },
    )

    report = write_tournament_report(tournament_name=t)
    assert isinstance(report, dict)
    assert (tmp_path / "logs" / "tournament_report.json").exists()
    assert (tmp_path / "logs" / "tournament_report.md").exists()

    parsed = json.loads((tmp_path / "logs" / "tournament_report.json").read_text(encoding="utf-8"))
    assert parsed["schema_version"] == "pommerman_tournament_report_v2"
    assert parsed["tournament_name"] == t
    assert isinstance(parsed.get("rounds"), list)
    assert "limitations" in parsed

    md_text = (tmp_path / "logs" / "tournament_report.md").read_text(encoding="utf-8")
    assert "## Model Roster" in md_text
    assert "## Audit Summary" in md_text


def test_tournament_report_marks_incomplete_when_round_manifest_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    t = "t_incomplete"
    (tmp_path / "logs" / "round_1").mkdir(parents=True, exist_ok=True)
    report = write_tournament_report(tournament_name=t)
    assert report["incomplete"] is True
    assert report["verdict"] == "INCOMPLETE"


def test_tournament_report_counts_feedback_packages_even_without_revision_manifest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    t = "t_feedback_packages"

    logs_root = tmp_path / "logs"
    posts_root = tmp_path / "workspace" / "posts"
    logs_root.mkdir(parents=True, exist_ok=True)
    posts_root.mkdir(parents=True, exist_ok=True)

    agent_ids = ["a1", "a2", "a3"]
    _write_json(
        logs_root / "initial_synthesis_manifest.json",
        {
            "tournament": t,
            "agents": [{"agent_id": aid, "provider_model": f"model_{aid}"} for aid in agent_ids],
        },
    )

    rd = logs_root / "round_1"
    md = rd / "match_1"
    md.mkdir(parents=True, exist_ok=True)
    _write_json(md / "arena_result_match_a.json", {"steps": 2, "reward": [0, 0, 0, 0], "left_right_winner": "draw"})
    _write_json(md / "arena_result_match_b.json", {"steps": 2, "reward": [0, 0, 0, 0], "left_right_winner": "draw"})
    _write_json(md / "metadata.json", {"left_agent_id": "a1", "right_agent_id": "a2", "applied_seed": 123, "requested_seed": 123})
    _write_json(
        rd / "round_manifest.json",
        {
            "round_idx": 1,
            "matches": [
                {"match_id": "match_1", "match_idx": 1, "left_agent_id": "a1", "right_agent_id": "a2", "applied_seed": 123},
            ],
            "revision_prompt_variant": "neutral",
            "initial_synthesis_prompt_variant": "neutral",
            "feedback_package_variant": "codeclash_v3",
            "feedback_visibility": "own_matches_plus_public_scoreboard",
        },
    )

    # Feedback packages can exist even if revision/propagation failed before writing revision_manifest.json.
    for aid in ["a1", "a3"]:
        pkg = posts_root / t / aid / "codebase_post_1" / "feedback" / "round_1"
        pkg.mkdir(parents=True, exist_ok=True)
        (pkg / "README.md").write_text("stub", encoding="utf-8")

    report = write_tournament_report(tournament_name=t, logs_root=logs_root, posts_root=posts_root)
    assert isinstance(report, dict)
    assert report.get("tournament_name") == t
    assert report.get("incomplete") is True
    assert report.get("verdict") == "INCOMPLETE"
    assert isinstance(report.get("rounds"), list)
    round1 = next((r for r in report["rounds"] if r.get("round") == 1), None)
    assert isinstance(round1, dict)
    fp = round1.get("feedback_packages")
    assert isinstance(fp, dict)
    assert fp["present"] is True
    assert fp["agents_with_package"] == 2
    assert fp["expected_agents_with_package"] == 3


def test_tournament_report_loads_stratum_from_model_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    t = "t_stratum"
    logs_root = tmp_path / "logs"
    posts_root = tmp_path / "workspace" / "posts"
    logs_root.mkdir(parents=True, exist_ok=True)
    posts_root.mkdir(parents=True, exist_ok=True)

    models_cfg = tmp_path / "models.yaml"
    models_cfg.write_text(
        "\n".join(
            [
                "models:",
                "  - agent_id: a1",
                "    provider_model: p1",
                "    stratum: light",
                "  - agent_id: a2",
                "    provider_model: p2",
                "    stratum: strong",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    _write_json(logs_root / "openclaw_model_route_validation.json", {"models_path": str(models_cfg)})
    _write_json(
        logs_root / "initial_synthesis_manifest.json",
        {"tournament": t, "agents": [{"agent_id": "a1", "provider_model": "p1"}, {"agent_id": "a2", "provider_model": "p2"}]},
    )

    report = write_tournament_report(tournament_name=t, logs_root=logs_root, posts_root=posts_root)
    roster = report.get("model_roster")
    assert isinstance(roster, list)
    roster_by_id = {r.get("agent_id"): r for r in roster if isinstance(r, dict)}
    assert roster_by_id["a1"]["stratum"] == "light"
    assert roster_by_id["a2"]["stratum"] == "strong"


def test_write_tournament_report_script_runs_without_pythonpath(tmp_path):
    # Ensure `python scripts/write_pommerman_tournament_report.py` can import `runner`
    # without requiring `PYTHONPATH=.`.
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "write_pommerman_tournament_report.py"
    assert script.exists()

    logs_root = tmp_path / "logs"
    posts_root = tmp_path / "workspace" / "posts"
    logs_root.mkdir(parents=True, exist_ok=True)
    posts_root.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    proc = subprocess.run(
        [sys.executable, str(script), "--tournament", "t_script", "--logs-root", str(logs_root), "--posts-root", str(posts_root)],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert (logs_root / "tournament_report.md").exists()
    assert (logs_root / "tournament_report.json").exists()

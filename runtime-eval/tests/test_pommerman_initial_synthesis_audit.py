import hashlib
import json
from pathlib import Path

from scripts.audit_pommerman_initial_synthesis import audit_pommerman_initial_synthesis


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_main(path: Path, text: str) -> None:
    p = path / "submission" / "main.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _mk_base(tmp_path: Path, tournament: str):
    starter = tmp_path / "starter_repos" / "pommerman_1v1" / "submission"
    starter.mkdir(parents=True, exist_ok=True)
    (starter / "main.py").write_text("AGGRESSION = 0\n", encoding="utf-8")

    agents = [f"a{i}" for i in range(1, 7)]
    init_entries = []
    prop_entries = []
    for i, aid in enumerate(agents, start=1):
        initial_base = tmp_path / "workspace" / "codebases" / tournament / aid / "codebase_initial_base_0"
        initial_post = tmp_path / "workspace" / "posts" / tournament / aid / "codebase_initial_post_0"
        play_1 = tmp_path / "workspace" / "codebases" / tournament / aid / "codebase_play_1"
        _write_main(initial_base, "AGGRESSION = 0\n")
        _write_main(initial_post, f"AGGRESSION = {i}\n")
        _write_main(play_1, f"AGGRESSION = {i}\n")
        init_entries.append(
            {
                "agent_id": aid,
                "initial_openclaw_invoked": True,
                "initial_synthesis_ok": True,
                "initial_provider_route_status": "matched",
                "initial_actual_provider": "relay",
                "initial_actual_model": f"model-{i}",
                "initial_fallback_used": False,
                "initial_strategy_profile_id": f"profile_{i}",
                "initial_strategy_profile_text": f"profile text {i}",
                "effective_initial_submission_changed": True,
                "initial_changed_files_hash_based": ["submission/main.py"],
                "starter_submission_sha256": _sha("AGGRESSION = 0\n"),
                "initial_submission_sha256": _sha(f"AGGRESSION = {i}\n"),
                "initial_disallowed_changed_files": [],
            }
        )
        prop_entries.append(
            {
                "agent_id": aid,
                "source_initial_post_path": str(initial_post),
                "target_play_path": str(play_1),
                "source_submission_sha256": _sha(f"AGGRESSION = {i}\n"),
                "target_submission_sha256": _sha(f"AGGRESSION = {i}\n"),
                "propagation_matches_post": True,
            }
        )

    logs = tmp_path / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "initial_synthesis_manifest.json").write_text(json.dumps({"agents": init_entries}), encoding="utf-8")
    r1 = logs / "round_1"
    r1.mkdir(parents=True, exist_ok=True)
    (r1 / "initial_propagation_manifest.json").write_text(json.dumps({"round_idx": 1, "agents": prop_entries}), encoding="utf-8")
    return tournament


def test_initial_synthesis_audit_passes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tournament = _mk_base(tmp_path, "pommerman_gptv16_a00_openclaw_initial_synthesis_3round_smoke")
    errors, _warnings = audit_pommerman_initial_synthesis(tournament_name=tournament)
    assert errors == []


def test_initial_synthesis_audit_fails_when_no_effective_change(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tournament = _mk_base(tmp_path, "pommerman_gptv16_a00_openclaw_initial_synthesis_3round_smoke")
    p = tmp_path / "logs" / "initial_synthesis_manifest.json"
    obj = json.loads(p.read_text(encoding="utf-8"))
    obj["agents"][0]["effective_initial_submission_changed"] = False
    obj["agents"][0]["initial_changed_files_hash_based"] = []
    obj["agents"][0]["initial_submission_sha256"] = obj["agents"][0]["starter_submission_sha256"]
    p.write_text(json.dumps(obj), encoding="utf-8")
    errors, _warnings = audit_pommerman_initial_synthesis(tournament_name=tournament)
    assert any("effective_initial_submission_changed must be true" in e for e in errors)


def test_initial_synthesis_audit_fails_when_all_hashes_identical(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tournament = _mk_base(tmp_path, "pommerman_gptv16_a00_openclaw_initial_synthesis_3round_smoke")
    p = tmp_path / "logs" / "initial_synthesis_manifest.json"
    obj = json.loads(p.read_text(encoding="utf-8"))
    same_hash = obj["agents"][0]["initial_submission_sha256"]
    for a in obj["agents"]:
        a["initial_submission_sha256"] = same_hash
    p.write_text(json.dumps(obj), encoding="utf-8")
    errors, _warnings = audit_pommerman_initial_synthesis(tournament_name=tournament)
    assert any("all initial submissions are identical" in e for e in errors)


def test_initial_synthesis_audit_warns_when_unique_hashes_below_four(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tournament = _mk_base(tmp_path, "pommerman_gptv16_a00_openclaw_initial_synthesis_3round_smoke")
    p = tmp_path / "logs" / "initial_synthesis_manifest.json"
    obj = json.loads(p.read_text(encoding="utf-8"))
    # Keep 2 unique hashes.
    keep_a = obj["agents"][0]["initial_submission_sha256"]
    keep_b = obj["agents"][1]["initial_submission_sha256"]
    for idx, a in enumerate(obj["agents"]):
        a["initial_submission_sha256"] = keep_a if idx % 2 == 0 else keep_b
    p.write_text(json.dumps(obj), encoding="utf-8")
    errors, warnings = audit_pommerman_initial_synthesis(tournament_name=tournament)
    assert errors == []
    assert any("low:" in w for w in warnings)


def test_initial_synthesis_audit_fails_when_profile_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tournament = _mk_base(tmp_path, "pommerman_gptv16_a00_openclaw_initial_synthesis_3round_smoke")
    p = tmp_path / "logs" / "initial_synthesis_manifest.json"
    obj = json.loads(p.read_text(encoding="utf-8"))
    obj["agents"][0].pop("initial_strategy_profile_id", None)
    p.write_text(json.dumps(obj), encoding="utf-8")
    errors, _warnings = audit_pommerman_initial_synthesis(tournament_name=tournament)
    assert any("initial_strategy_profile_id" in e for e in errors)


def test_initial_synthesis_audit_fails_on_propagation_mismatch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tournament = _mk_base(tmp_path, "pommerman_gptv16_a00_openclaw_initial_synthesis_3round_smoke")
    p = tmp_path / "logs" / "round_1" / "initial_propagation_manifest.json"
    obj = json.loads(p.read_text(encoding="utf-8"))
    bad_agent = obj["agents"][0]["agent_id"]
    target = Path(obj["agents"][0]["target_play_path"])
    _write_main(target, "AGGRESSION = 0\n")
    obj["agents"][0]["propagation_matches_post"] = False
    p.write_text(json.dumps(obj), encoding="utf-8")
    errors, _warnings = audit_pommerman_initial_synthesis(tournament_name=tournament)
    assert any(bad_agent in e and "hashes differ" in e for e in errors)

import hashlib
import json
from pathlib import Path

from scripts.audit_pommerman_effective_revision import audit_effective_revision


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_main(path: Path, text: str) -> None:
    p = path / "submission" / "main.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _mk_round_manifest(round_dir: Path) -> None:
    match_dir = round_dir / "match_1"
    match_dir.mkdir(parents=True, exist_ok=True)
    scorecard = match_dir / "scorecard.json"
    scorecard.write_text(json.dumps({"left_right_winner": "draw"}), encoding="utf-8")
    round_manifest = {
        "round_idx": int(round_dir.name.split("_")[1]),
        "matches_per_round": 1,
        "matches": [{"scorecard_path": str(scorecard)}],
    }
    (round_dir / "round_manifest.json").write_text(json.dumps(round_manifest), encoding="utf-8")


def _mk_tournament_cfg(*, require_effective: bool) -> None:
    cfg_path = Path("configs/tournaments/pommerman_gptv16_a00_openclaw_adaptive_3round_smoke.yaml")
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        "name: pommerman_gptv16_a00_openclaw_adaptive_3round_smoke\n"
        f"require_effective_submission_change: {'true' if require_effective else 'false'}\n",
        encoding="utf-8",
    )


def _mk_rev_entry(
    *,
    tournament: str,
    round_idx: int,
    agent_id: str,
    before_txt: str,
    after_txt: str,
    changed_files: list[str] | None = None,
    changed_files_hash_based: list[str] | None = None,
    diff_targets_submission: bool = False,
) -> dict:
    play = Path("workspace/codebases") / tournament / agent_id / f"codebase_play_{round_idx}"
    post = Path("workspace/posts") / tournament / agent_id / f"codebase_post_{round_idx}"
    _write_main(play, before_txt)
    _write_main(post, after_txt)

    diff_path = Path("logs") / f"round_{round_idx}" / f"{agent_id}.diff.patch"
    diff_path.parent.mkdir(parents=True, exist_ok=True)
    if diff_targets_submission:
        before_abs = (play / "submission" / "main.py").resolve()
        after_abs = (post / "submission" / "main.py").resolve()
        diff_path.write_text(f"--- {before_abs}\n+++ {after_abs}\n", encoding="utf-8")
    else:
        diff_path.write_text("notes only\n", encoding="utf-8")

    before_hash = _sha(before_txt)
    after_hash = _sha(after_txt)
    effective = before_hash != after_hash
    return {
        "agent_id": agent_id,
        "revision_attempted": True,
        "revision_ok": True,
        "changed_files": [] if changed_files is None else changed_files,
        "codebase_play_path": str(play),
        "codebase_post_path": str(post),
        "diff_path": str(diff_path),
        "submission_main_sha256_before": before_hash,
        "submission_main_sha256_after": after_hash,
        "effective_submission_changed": effective,
        "changed_files_hash_based": (
            ["submission/main.py"] if (effective and changed_files_hash_based is None) else (changed_files_hash_based or [])
        ),
    }


def _mk_rev_manifest(round_dir: Path, entries: list[dict]) -> None:
    (round_dir / "revision_manifest.json").write_text(json.dumps({"agents": entries}), encoding="utf-8")


def _mk_prop_manifest(round_dir: Path, *, tournament: str, source_round: int, target_round: int, agent_id: str) -> None:
    source = Path("workspace/posts") / tournament / agent_id / f"codebase_post_{source_round}"
    target = Path("workspace/codebases") / tournament / agent_id / f"codebase_play_{target_round}"
    _write_main(target, (source / "submission" / "main.py").read_text(encoding="utf-8"))
    source_hash = _sha((source / "submission" / "main.py").read_text(encoding="utf-8"))
    target_hash = _sha((target / "submission" / "main.py").read_text(encoding="utf-8"))
    payload = {
        "round_idx": target_round,
        "agents": [
            {
                "agent_id": agent_id,
                "source_post_path": str(source),
                "target_play_path": str(target),
                "source_submission_sha256": source_hash,
                "target_submission_sha256": target_hash,
                "propagation_matches_post": source_hash == target_hash,
            }
        ],
    }
    (round_dir / "propagation_manifest.json").write_text(json.dumps(payload), encoding="utf-8")


def test_effective_revision_audit_fails_for_metadata_only_false_claim(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _mk_tournament_cfg(require_effective=False)
    round1 = Path("logs/round_1")
    _mk_round_manifest(round1)
    entry = _mk_rev_entry(
        tournament="t",
        round_idx=1,
        agent_id="a1",
        before_txt="AGGRESSION = 0\n",
        after_txt="AGGRESSION = 0\n",
        changed_files=["submission/main.py"],
        changed_files_hash_based=[],
        diff_targets_submission=False,
    )
    _mk_rev_manifest(round1, [entry])
    errors, _warnings = audit_effective_revision()
    assert any("changed_files includes submission/main.py but effective_submission_changed=false" in e for e in errors)


def test_effective_revision_audit_passes_when_submission_hash_changes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _mk_tournament_cfg(require_effective=False)
    round1 = Path("logs/round_1")
    _mk_round_manifest(round1)
    entry = _mk_rev_entry(
        tournament="t",
        round_idx=1,
        agent_id="a1",
        before_txt="AGGRESSION = 0\n",
        after_txt="AGGRESSION = 1\n",
        changed_files=["submission/main.py"],
        changed_files_hash_based=["submission/main.py"],
        diff_targets_submission=True,
    )
    _mk_rev_manifest(round1, [entry])
    round2 = Path("logs/round_2")
    _mk_round_manifest(round2)
    _mk_prop_manifest(round2, tournament="t", source_round=1, target_round=2, agent_id="a1")
    errors, _warnings = audit_effective_revision()
    assert errors == []


def test_effective_revision_audit_fails_on_propagation_hash_mismatch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _mk_tournament_cfg(require_effective=False)
    round1 = Path("logs/round_1")
    round2 = Path("logs/round_2")
    _mk_round_manifest(round1)
    _mk_round_manifest(round2)
    entry = _mk_rev_entry(
        tournament="t",
        round_idx=1,
        agent_id="a1",
        before_txt="AGGRESSION = 0\n",
        after_txt="AGGRESSION = 1\n",
    )
    _mk_rev_manifest(round1, [entry])
    _mk_prop_manifest(round2, tournament="t", source_round=1, target_round=2, agent_id="a1")
    target = Path("workspace/codebases") / "t" / "a1" / "codebase_play_2" / "submission" / "main.py"
    target.write_text("AGGRESSION = 0\n", encoding="utf-8")
    errors, _warnings = audit_effective_revision()
    assert any("propagation hash mismatch" in e for e in errors)


def test_effective_revision_audit_fails_all_noop_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _mk_tournament_cfg(require_effective=False)
    round1 = Path("logs/round_1")
    _mk_round_manifest(round1)
    entry = _mk_rev_entry(
        tournament="t",
        round_idx=1,
        agent_id="a1",
        before_txt="AGGRESSION = 0\n",
        after_txt="AGGRESSION = 0\n",
    )
    _mk_rev_manifest(round1, [entry])
    errors, _warnings = audit_effective_revision()
    assert any("all OpenClaw revisions were no-op for submitted code" in e for e in errors)


def test_effective_revision_audit_allows_all_noop_with_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _mk_tournament_cfg(require_effective=False)
    round1 = Path("logs/round_1")
    _mk_round_manifest(round1)
    entry = _mk_rev_entry(
        tournament="t",
        round_idx=1,
        agent_id="a1",
        before_txt="AGGRESSION = 0\n",
        after_txt="AGGRESSION = 0\n",
    )
    _mk_rev_manifest(round1, [entry])
    errors, _warnings = audit_effective_revision(allow_all_noop=True)
    assert errors == []


def test_effective_revision_audit_requires_change_when_tournament_requires_it(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _mk_tournament_cfg(require_effective=True)
    round1 = Path("logs/round_1")
    _mk_round_manifest(round1)
    entry = _mk_rev_entry(
        tournament="t",
        round_idx=1,
        agent_id="a1",
        before_txt="AGGRESSION = 0\n",
        after_txt="AGGRESSION = 0\n",
    )
    _mk_rev_manifest(round1, [entry])
    errors, _warnings = audit_effective_revision()
    assert any("require_effective_submission_change=true" in e for e in errors)

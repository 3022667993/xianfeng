from __future__ import annotations

import json
import hashlib
from pathlib import Path

import yaml


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _audit_a00() -> list[str]:
    errs: list[str] = []
    cfg = yaml.safe_load(Path("configs/regimes/A00.yaml").read_text(encoding="utf-8"))
    runtime = cfg.get("runtime_controls", {}) if isinstance(cfg, dict) else {}
    req = {
        "conversational_carryover": False,
        "file_memory": False,
        "visibility": "summary-only",
        "skills_enabled": False,
        "memory_plugin_enabled": False,
        "session_memory_hook": False,
        "pre_compaction_memory_flush": False,
        "startup_memory_prelude": False,
        "fixed_bootstrap": True,
        "fixed_tool_surface": True,
    }
    for k, v in req.items():
        got = cfg.get(k)
        if got is None:
            got = runtime.get(k)
        if got != v:
            errs.append(f"A00 mismatch {k}")
    return errs


def _check_seed_applied(payload: dict, label: str, errors: list[str]) -> None:
    if payload.get("seed_control_status") != "applied":
        errors.append(f"{label}: seed_control_status must be applied")
    req = payload.get("requested_seed")
    if req is None:
        errors.append(f"{label}: requested_seed missing")
    if payload.get("applied_seed") != req:
        errors.append(f"{label}: applied_seed must equal requested_seed")
    if payload.get("seed") != req:
        errors.append(f"{label}: seed must equal requested_seed")
    if payload.get("seed_control_method_applied") != "env.seed(...)":
        errors.append(f"{label}: seed_control_method_applied must be env.seed(...)")
    methods = payload.get("seed_control_methods_attempted")
    if not isinstance(methods, list) or "env.seed(...)" not in methods:
        errors.append(f"{label}: seed_control_methods_attempted must include env.seed(...)")
    if "seed_control_env_seed_return" not in payload:
        errors.append(f"{label}: seed_control_env_seed_return missing")


def _audit_round_manifest(path: Path, expected_round_idx: int) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    seen_agents: list[str] = []
    if not path.exists():
        return [f"missing {path}"], seen_agents
    rm = _load_json(path)
    if rm.get("round_idx") != expected_round_idx:
        errors.append(f"round_{expected_round_idx}: round_idx mismatch")
    if rm.get("matches_per_round") != 3:
        errors.append(f"round_{expected_round_idx}: matches_per_round must be 3")
    if rm.get("scorecard_policy") != "raw_per_match_scorecard; pair-level aggregation is post-analysis":
        errors.append(f"round_{expected_round_idx}: scorecard policy mismatch")
    matches = rm.get("matches")
    if not isinstance(matches, list) or len(matches) != 3:
        errors.append(f"round_{expected_round_idx}: exactly 3 matches required")
        return errors, seen_agents
    for m in matches:
        left = m.get("left_agent_id")
        right = m.get("right_agent_id")
        seen_agents.extend([left, right])
        if m.get("background_agents") != ["dummy2", "dummy3"]:
            errors.append(f"round_{expected_round_idx}: background agents mismatch")
        if m.get("pair_id") is None:
            errors.append(f"round_{expected_round_idx}: pair_id missing")
        for f in ["metadata_path", "scorecard_path", "arena_result_match_a_path"]:
            p = m.get(f)
            if not isinstance(p, str) or not Path(p).exists():
                errors.append(f"round_{expected_round_idx}: missing artifact {f}")
        _check_seed_applied(m, f"round_{expected_round_idx}/{m.get('match_id')}", errors)
    if len(set(seen_agents)) != 6 or any(seen_agents.count(a) != 1 for a in set(seen_agents)):
        errors.append(f"round_{expected_round_idx}: must be perfect matching over 6 unique agents")
    return errors, seen_agents


def _audit_revision_manifest(path: Path, label: str) -> list[str]:
    errors: list[str] = []
    if not path.exists():
        return [f"missing {path}"]
    rev = _load_json(path)
    require_effective = bool(rev.get("require_effective_submission_change", False))
    agents = rev.get("agents")
    if not isinstance(agents, list) or len(agents) != 6:
        return [f"{label}: revision_manifest must include exactly 6 entries"]
    for a in agents:
        if a.get("revision_attempted") is not True:
            errors.append(f"{label}: revision_attempted=true required")
        if a.get("openclaw_invoked") is not True:
            errors.append(f"{label}: openclaw_invoked=true required")
        if a.get("revision_ok") is not True:
            errors.append(f"{label}: revision_ok=true required")
        if a.get("provider_route_status") != "matched":
            errors.append(f"{label}: provider_route_status=matched required")
        if a.get("fallback_used") is not False:
            errors.append(f"{label}: fallback_used=false required")
        if a.get("revision_executor") in {"dryrun-noop", "rule-minimal"}:
            errors.append(f"{label}: revision_executor cannot be dryrun-noop/rule-minimal")
        if "effective_submission_changed" not in a:
            errors.append(f"{label}: effective_submission_changed required")
        if "changed_files_hash_based" not in a:
            errors.append(f"{label}: changed_files_hash_based required")
        if a.get("changed_files_inconsistent_with_hash") is True:
            errors.append(f"{label}: changed_files inconsistent with submission hash")
        changed_files = a.get("changed_files")
        if (
            isinstance(changed_files, list)
            and "submission/main.py" in changed_files
            and a.get("effective_submission_changed") is False
        ):
            errors.append(f"{label}: changed_files claims submission/main.py but submission hash unchanged")
        hash_based = a.get("changed_files_hash_based")
        if (
            isinstance(hash_based, list)
            and "submission/main.py" in hash_based
            and a.get("effective_submission_changed") is False
        ):
            errors.append(f"{label}: changed_files_hash_based contradicts effective_submission_changed=false")
        if require_effective and a.get("effective_submission_changed") is not True:
            errors.append(f"{label}: require_effective_submission_change=true but effective_submission_changed=false")
    return errors


def _audit_propagation_manifest(
    path: Path,
    *,
    tournament_name: str,
    source_round: int,
    target_round: int,
    expected_agents: set[str],
) -> list[str]:
    errors: list[str] = []
    if not path.exists():
        return [f"missing {path}"]
    payload = _load_json(path)
    entries = payload.get("agents")
    if not isinstance(entries, list) or len(entries) != 6:
        return [f"{path}: propagation_manifest must include exactly 6 agents"]
    by_agent = {e.get("agent_id"): e for e in entries if isinstance(e, dict)}
    if set(by_agent.keys()) != expected_agents:
        errors.append(f"{path}: propagation agents mismatch")
    for agent_id in expected_agents:
        rec = by_agent.get(agent_id)
        if not isinstance(rec, dict):
            errors.append(f"{path}: missing propagation record for {agent_id}")
            continue
        if rec.get("propagated") is not True or rec.get("propagation_ok") is not True:
            errors.append(f"{path}: {agent_id} propagated/propagation_ok must be true")
        if rec.get("source_revision_ok") is not True:
            errors.append(f"{path}: {agent_id} source_revision_ok must be true")
        if rec.get("source_provider_route_status") != "matched":
            errors.append(f"{path}: {agent_id} source_provider_route_status must be matched")
        if rec.get("source_round") != source_round:
            errors.append(f"{path}: {agent_id} source_round mismatch")
        if rec.get("target_round") != target_round:
            errors.append(f"{path}: {agent_id} target_round mismatch")
        source_post_path = Path(str(rec.get("source_post_path")))
        target_play_path = Path(str(rec.get("target_play_path")))
        expected_source = Path("workspace/posts") / tournament_name / agent_id / f"codebase_post_{source_round}"
        expected_target = Path("workspace/codebases") / tournament_name / agent_id / f"codebase_play_{target_round}"
        if source_post_path != expected_source:
            errors.append(f"{path}: {agent_id} source_post_path mismatch")
        if target_play_path != expected_target:
            errors.append(f"{path}: {agent_id} target_play_path mismatch")
        source_submission_sha256 = rec.get("source_submission_sha256")
        target_submission_sha256 = rec.get("target_submission_sha256")
        if source_submission_sha256 is None or target_submission_sha256 is None:
            errors.append(f"{path}: {agent_id} source/target submission sha256 required")
        if rec.get("propagation_matches_post") is not True:
            errors.append(f"{path}: {agent_id} propagation_matches_post must be true")
        source_submission_path = source_post_path / "submission" / "main.py"
        target_submission_path = target_play_path / "submission" / "main.py"
        if not source_submission_path.exists():
            errors.append(f"{path}: {agent_id} source submission missing: {source_submission_path}")
        if not target_submission_path.exists():
            errors.append(f"{path}: {agent_id} target submission missing: {target_submission_path}")
        actual_source_hash = _sha256_file(source_submission_path)
        actual_target_hash = _sha256_file(target_submission_path)
        if source_submission_sha256 != actual_source_hash:
            errors.append(f"{path}: {agent_id} source_submission_sha256 mismatch")
        if target_submission_sha256 != actual_target_hash:
            errors.append(f"{path}: {agent_id} target_submission_sha256 mismatch")
        if source_submission_sha256 != target_submission_sha256:
            errors.append(f"{path}: {agent_id} source/target submission sha256 differ")
        if actual_source_hash != actual_target_hash:
            errors.append(f"{path}: {agent_id} propagated submission/main.py hash mismatch")
    return errors


def audit_openclaw_adaptive_3round_smoke(
    tournament_name: str = "pommerman_gptv16_a00_openclaw_adaptive_3round_smoke",
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    initial_synthesis_expected = tournament_name == "pommerman_gptv16_a00_openclaw_initial_synthesis_3round_smoke"

    round_agent_sets: list[set[str]] = []
    total_matches = 0
    for ridx in [1, 2, 3]:
        rm_path = Path(f"logs/round_{ridx}/round_manifest.json")
        e, seen = _audit_round_manifest(rm_path, ridx)
        errors.extend(e)
        round_agent_sets.append(set(seen))
        total_matches += 3

        round_dir = Path(f"logs/round_{ridx}")
        for match_dir in sorted(p for p in round_dir.glob("match_*") if p.is_dir()):
            for req in [
                "metadata.json",
                "scorecard.json",
                "arena_result_match_a.json",
                "trajectory_summary.json",
                "trajectory_compact_match_a.jsonl",
                "trajectory_events.json",
            ]:
                if not (match_dir / req).exists():
                    errors.append(f"{match_dir}: missing {req}")
            md = _load_json(match_dir / "metadata.json") if (match_dir / "metadata.json").exists() else {}
            left = md.get("left_agent_id")
            right = md.get("right_agent_id")
            if isinstance(left, str) and isinstance(right, str):
                for aid in [left, right]:
                    if not (match_dir / f"agent_feedback_{aid}.json").exists():
                        errors.append(f"{match_dir}: missing agent_feedback_{aid}.json")
                    if not (match_dir / f"agent_feedback_{aid}.md").exists():
                        errors.append(f"{match_dir}: missing agent_feedback_{aid}.md")
            for payload_name in [
                "metadata.json",
                "scorecard.json",
                "arena_result_match_a.json",
                "trajectory_summary.json",
                "trajectory_events.json",
            ]:
                p = match_dir / payload_name
                if p.exists():
                    _check_seed_applied(_load_json(p), str(p), errors)

    if total_matches != 9:
        errors.append("total matches must be 9")
    all_agents = set.union(*round_agent_sets) if round_agent_sets else set()
    if len(all_agents) != 6:
        errors.append("must observe exactly 6 unique agents")

    if initial_synthesis_expected:
        ip_path = Path("logs/round_1/initial_propagation_manifest.json")
        if not ip_path.exists():
            errors.append("missing logs/round_1/initial_propagation_manifest.json")
        else:
            ip = _load_json(ip_path)
            entries = ip.get("agents")
            if not isinstance(entries, list) or len(entries) != 6:
                errors.append("initial_propagation_manifest must include exactly 6 entries")
            else:
                by_agent = {x.get("agent_id"): x for x in entries if isinstance(x, dict)}
                for agent_id in all_agents:
                    rec = by_agent.get(agent_id)
                    if not isinstance(rec, dict):
                        errors.append(f"initial propagation missing agent {agent_id}")
                        continue
                    source = Path(str(rec.get("source_initial_post_path")))
                    target = Path(str(rec.get("target_play_path")))
                    source_hash = _sha256_file(source / "submission/main.py")
                    target_hash = _sha256_file(target / "submission/main.py")
                    if source_hash != target_hash:
                        errors.append(f"initial propagation hash mismatch for {agent_id}")
                    if rec.get("propagation_matches_post") is not True:
                        errors.append(f"initial propagation propagation_matches_post must be true for {agent_id}")

    errors.extend(_audit_revision_manifest(Path("logs/round_1/revision_manifest.json"), "round_1"))
    errors.extend(_audit_revision_manifest(Path("logs/round_2/revision_manifest.json"), "round_2"))

    expected_agents = all_agents if all_agents else {f"a{i}" for i in range(1, 7)}
    errors.extend(
        _audit_propagation_manifest(
            Path("logs/round_2/propagation_manifest.json"),
            tournament_name=tournament_name,
            source_round=1,
            target_round=2,
            expected_agents=expected_agents,
        )
    )
    errors.extend(
        _audit_propagation_manifest(
            Path("logs/round_3/propagation_manifest.json"),
            tournament_name=tournament_name,
            source_round=2,
            target_round=3,
            expected_agents=expected_agents,
        )
    )

    for root in ["codebases", "submissions", "posts"]:
        troot = Path("workspace") / root / tournament_name
        for side in ["left", "right"]:
            if (troot / side).exists():
                errors.append(f"persistent {side}/ dir must not exist")

    for ridx in [1, 2, 3]:
        if Path(f"logs/round_{ridx}/pair_scorecard.json").exists():
            errors.append("paired aggregate scorecard must not exist")

    return errors, warnings


def main() -> int:
    errors = _audit_a00()
    e2, w2 = audit_openclaw_adaptive_3round_smoke()
    errors.extend(e2)
    for w in w2:
        print(f"WARN {w}")
    if errors:
        print("openclaw_adaptive_3round_smoke_audit=FAIL")
        for e in errors:
            print(f"ERROR {e}")
        return 1
    print("openclaw_adaptive_3round_smoke_audit=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

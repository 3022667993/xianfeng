from __future__ import annotations

import json
import hashlib
from pathlib import Path


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


def audit_pommerman_initial_synthesis(
    tournament_name: str = "pommerman_gptv16_a00_openclaw_initial_synthesis_3round_smoke",
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    starter_hash = _sha256_file(Path("starter_repos/pommerman_1v1/submission/main.py"))
    if starter_hash is None:
        errors.append("missing starter_repos/pommerman_1v1/submission/main.py")
        return errors, warnings

    manifest_path = Path("logs/initial_synthesis_manifest.json")
    if not manifest_path.exists():
        errors.append("missing logs/initial_synthesis_manifest.json")
        return errors, warnings
    payload = _load_json(manifest_path)
    agents = payload.get("agents")
    if not isinstance(agents, list) or len(agents) != 6:
        errors.append("initial_synthesis_manifest must include exactly 6 agent entries")
        return errors, warnings

    initial_hashes: list[str] = []
    agent_ids: list[str] = []
    by_agent: dict[str, dict] = {}
    for entry in agents:
        if not isinstance(entry, dict):
            errors.append("initial_synthesis_manifest entries must be objects")
            continue
        agent_id = entry.get("agent_id")
        if not isinstance(agent_id, str):
            errors.append("initial_synthesis entry missing agent_id")
            continue
        agent_ids.append(agent_id)
        by_agent[agent_id] = entry
        label = f"initial:{agent_id}"
        if entry.get("initial_openclaw_invoked") is not True:
            errors.append(f"{label}: initial_openclaw_invoked must be true")
        if entry.get("initial_synthesis_ok") is not True:
            errors.append(f"{label}: initial_synthesis_ok must be true")
        if entry.get("initial_provider_route_status") != "matched":
            errors.append(f"{label}: initial_provider_route_status must be matched")
        if not isinstance(entry.get("initial_actual_provider"), str) or not str(entry.get("initial_actual_provider")).strip():
            errors.append(f"{label}: initial_actual_provider must be non-empty")
        if not isinstance(entry.get("initial_actual_model"), str) or not str(entry.get("initial_actual_model")).strip():
            errors.append(f"{label}: initial_actual_model must be non-empty")
        if entry.get("initial_fallback_used") is not False:
            errors.append(f"{label}: initial_fallback_used must be false")
        if not isinstance(entry.get("initial_strategy_profile_id"), str) or not str(entry.get("initial_strategy_profile_id")).strip():
            errors.append(f"{label}: initial_strategy_profile_id must be present")
        if not isinstance(entry.get("initial_strategy_profile_text"), str) or not str(entry.get("initial_strategy_profile_text")).strip():
            errors.append(f"{label}: initial_strategy_profile_text must be present")
        if entry.get("effective_initial_submission_changed") is not True:
            errors.append(f"{label}: effective_initial_submission_changed must be true")
        changed = entry.get("initial_changed_files_hash_based")
        if not isinstance(changed, list) or "submission/main.py" not in changed:
            errors.append(f"{label}: initial_changed_files_hash_based must include submission/main.py")
        starter_sha = entry.get("starter_submission_sha256")
        initial_sha = entry.get("initial_submission_sha256")
        if starter_sha != starter_hash:
            errors.append(f"{label}: starter_submission_sha256 mismatch")
        if starter_sha == initial_sha:
            errors.append(f"{label}: starter_submission_sha256 equals initial_submission_sha256")
        disallowed = entry.get("initial_disallowed_changed_files")
        if isinstance(disallowed, list) and disallowed:
            errors.append(f"{label}: disallowed changed files present")
        if isinstance(initial_sha, str):
            initial_hashes.append(initial_sha)

    if len(set(agent_ids)) != 6:
        errors.append("initial_synthesis_manifest agent ids must be unique and complete")

    prop_path = Path("logs/round_1/initial_propagation_manifest.json")
    if not prop_path.exists():
        errors.append("missing logs/round_1/initial_propagation_manifest.json")
        return errors, warnings
    prop = _load_json(prop_path)
    entries = prop.get("agents")
    if not isinstance(entries, list) or len(entries) != 6:
        errors.append("initial_propagation_manifest must include exactly 6 entries")
        return errors, warnings

    prop_ids = set()
    for rec in entries:
        if not isinstance(rec, dict):
            errors.append("initial_propagation entries must be objects")
            continue
        agent_id = rec.get("agent_id")
        if not isinstance(agent_id, str):
            errors.append("initial_propagation entry missing agent_id")
            continue
        prop_ids.add(agent_id)
        label = f"initial-prop:{agent_id}"
        source = Path(str(rec.get("source_initial_post_path")))
        target = Path(str(rec.get("target_play_path")))
        source_hash = _sha256_file(source / "submission/main.py")
        target_hash = _sha256_file(target / "submission/main.py")
        if source_hash != target_hash:
            errors.append(f"{label}: source initial post and play_1 submission hashes differ")
        if rec.get("propagation_matches_post") is not True:
            errors.append(f"{label}: propagation_matches_post must be true")
        if target_hash == starter_hash:
            errors.append(f"{label}: round_1 play_1 hash still equals starter hash")
        src_sha = rec.get("source_submission_sha256")
        tgt_sha = rec.get("target_submission_sha256")
        if src_sha != source_hash:
            errors.append(f"{label}: source_submission_sha256 mismatch")
        if tgt_sha != target_hash:
            errors.append(f"{label}: target_submission_sha256 mismatch")

    if prop_ids != set(agent_ids):
        errors.append("initial_propagation agents must match initial_synthesis agents")

    unique_initial = len(set(initial_hashes))
    if unique_initial <= 1:
        errors.append("all initial submissions are identical")
    if unique_initial < 2:
        errors.append("unique_initial_submission_hash_count must be >= 2")
    elif unique_initial < 4:
        warnings.append(f"unique initial submission hashes low: {unique_initial} (<4)")
    else:
        warnings.append(f"unique initial submission hashes={unique_initial}")

    return errors, warnings


def main() -> int:
    errors, warnings = audit_pommerman_initial_synthesis()
    for w in warnings:
        print(f"WARN {w}")
    if errors:
        print("pommerman_initial_synthesis_audit=FAIL")
        for e in errors:
            print(f"ERROR {e}")
        return 1
    print("pommerman_initial_synthesis_audit=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

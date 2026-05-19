from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
from pathlib import Path

from runner.adapters.registry import get_adapter
from runner.core.artifacts import ensure_round_dir, write_json
from runner.core.config import load_yaml, require_keys, resolve_tournament_counts
from runner.core.fsops import copy_tree
from runner.core.pommerman_results import classify_pommerman_result
from runner.core.revision import apply_minimal_initial_synthesis, apply_minimal_revision, apply_noop_revision, write_diff_patch
from runner.core.schedule import build_double_round_robin
from runner.core.pommerman_feedback import write_feedback_artifact_mirrors, write_process_feedback


REQUIRED_DIRS = [
    "configs",
    "docs",
    "runner",
    "scripts",
    "starter_repos",
    "logs",
    "outputs",
    "tests",
    "workspace",
]


def ensure_dirs() -> None:
    missing = [d for d in REQUIRED_DIRS if not Path(d).exists()]
    if missing:
        raise FileNotFoundError(f"Missing required directories: {missing}")


def _safe_progress_value(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _smoke_requested_seed(tournament: dict) -> int:
    seed = tournament.get("seed")
    if seed is None:
        # Stable fallback for the Pommerman+A00 smoke artifact.
        return 1001
    return int(seed)


def _write_round_seed_provenance(
    round_dir: Path,
    requested_seed: int,
    applied_seed: int | None,
    *,
    seed_control_status: str | None = None,
    seed_control_error: str | None = None,
    seed_control_methods_attempted: list[str] | None = None,
    seed_control_method_applied: str | None = None,
    seed_control_env_seed_return: object | None = None,
) -> None:
    existing_payloads: list[dict[str, object]] = []
    for name in ("arena_result_match_a.json", "scorecard.json"):
        path = round_dir / name
        if path.exists():
            existing_payloads.append(json.loads(path.read_text(encoding="utf-8")))

    if seed_control_status is None:
        if requested_seed is None:
            if isinstance(applied_seed, int):
                seed_control_status = "applied"
            elif existing_payloads:
                observed = [
                    p.get("seed_control_status")
                    for p in existing_payloads
                    if isinstance(p.get("seed_control_status"), str)
                ]
                seed_control_status = observed[0] if observed else "not_requested"
            else:
                seed_control_status = "not_requested"
        else:
            if isinstance(applied_seed, int):
                seed_control_status = "applied"
            elif existing_payloads:
                observed = [
                    p.get("seed_control_status")
                    for p in existing_payloads
                    if isinstance(p.get("seed_control_status"), str)
                ]
                if "applied" in observed:
                    seed_control_status = "applied"
                else:
                    preferred = [s for s in observed if s in {"requested_but_not_applied", "unsupported_by_environment"}]
                    seed_control_status = preferred[0] if preferred else "requested_but_not_applied"
            else:
                seed_control_status = "requested_but_not_applied"

    if applied_seed is None:
        for payload in existing_payloads:
            candidate = payload.get("applied_seed")
            if isinstance(candidate, int):
                applied_seed = candidate
                break
    if seed_control_status == "applied" and applied_seed != requested_seed:
        seed_control_status = "requested_but_not_applied"
        applied_seed = None
    if seed_control_status in {"requested_but_not_applied", "unsupported_by_environment", "not_requested"}:
        applied_seed = None
    seed = applied_seed if seed_control_status == "applied" else None
    for name in (
        "arena_result_match_a.json",
        "scorecard.json",
        "metadata.json",
        "round_manifest.json",
        "trajectory_summary.json",
        "trajectory_events.json",
    ):
        path = round_dir / name
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        existing_status = payload.get("seed_control_status")
        existing_error = payload.get("seed_control_error")
        existing_attempted = payload.get("seed_control_methods_attempted")
        existing_method_applied = payload.get("seed_control_method_applied")
        existing_env_seed_return = payload.get("seed_control_env_seed_return")
        payload["requested_seed"] = requested_seed
        payload["applied_seed"] = applied_seed
        payload["seed"] = seed
        payload["seed_control_status"] = seed_control_status
        payload["seed_control_error"] = (
            seed_control_error
            if seed_control_error is not None
            else (existing_error if isinstance(existing_error, str) else None)
        )
        if isinstance(seed_control_methods_attempted, list):
            payload["seed_control_methods_attempted"] = seed_control_methods_attempted
        elif isinstance(existing_attempted, list):
            payload["seed_control_methods_attempted"] = existing_attempted
        else:
            payload["seed_control_methods_attempted"] = []
        payload["seed_control_method_applied"] = (
            seed_control_method_applied
            if seed_control_method_applied is not None
            else (existing_method_applied if isinstance(existing_method_applied, str) else None)
        )
        payload["seed_control_env_seed_return"] = (
            seed_control_env_seed_return
            if seed_control_env_seed_return is not None
            else existing_env_seed_return
        )
        if payload["seed_control_status"] in {"requested_but_not_applied", "unsupported_by_environment"}:
            if not isinstance(payload.get("seed_control_error"), str) or not str(payload["seed_control_error"]).strip():
                payload["seed_control_error"] = "requested seed could not be applied by environment seed/reset APIs"
            attempted = payload.get("seed_control_methods_attempted")
            if not isinstance(attempted, list) or not attempted:
                payload["seed_control_methods_attempted"] = ["env.reset(seed=...)", "env.seed(...)"]
        if seed_control_status is None and isinstance(existing_status, str):
            payload["seed_control_status"] = existing_status
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_seed_provenance_from_match_dir(
    match_dir: Path,
) -> tuple[int | None, str, str | None, list[str], str | None, object | None]:
    scorecard = match_dir / "scorecard.json"
    if not scorecard.exists():
        return None, "requested_but_not_applied", "scorecard_missing_for_seed_provenance", [], None, None
    try:
        payload = json.loads(scorecard.read_text(encoding="utf-8"))
    except Exception:
        return None, "requested_but_not_applied", "scorecard_seed_parse_failed", [], None, None
    applied_seed = payload.get("applied_seed")
    status = payload.get("seed_control_status", "requested_but_not_applied")
    err = payload.get("seed_control_error")
    attempted = payload.get("seed_control_methods_attempted")
    method = payload.get("seed_control_method_applied")
    env_seed_return = payload.get("seed_control_env_seed_return")
    methods = attempted if isinstance(attempted, list) else []
    error = err if isinstance(err, str) else None
    if status in {"requested_but_not_applied", "unsupported_by_environment"}:
        if not methods:
            methods = ["env.reset(seed=...)", "env.seed(...)"]
        if not isinstance(error, str) or not error.strip():
            error = "requested seed could not be applied by environment seed/reset APIs"
    return (
        applied_seed,
        status,
        error,
        methods,
        method if isinstance(method, str) else None,
        env_seed_return,
    )


def _execution_smoke_base_seed(tournament: dict) -> int:
    seed = tournament.get("seed")
    if seed is None:
        seed = tournament.get("base_seed")
    if seed is None:
        # Stable fallback for the execution-smoke schedule.
        return 1001
    return int(seed)


def _execution_smoke_round_robin_round(entries: list[dict]) -> list[tuple[dict, dict]]:
    if len(entries) < 2:
        raise ValueError("execution_smoke requires at least 2 models")
    if len(entries) % 2 == 1:
        from runner.core.config import ODD_MODEL_COUNT_ERROR

        raise ValueError(ODD_MODEL_COUNT_ERROR)
    order = list(entries)
    half = len(order) // 2
    left_half = order[:half]
    right_half = list(reversed(order[half:]))
    return list(zip(left_half, right_half))


def _execution_smoke_pair_seed(pair_id: str, base_seed: int) -> int:
    material = f"{pair_id}|{base_seed}"
    return int(hashlib.sha256(material.encode("utf-8")).hexdigest()[:8], 16) & 0x7FFFFFFF


def _execution_smoke_cleanup(tournament_name: str) -> None:
    for root in [
        Path("workspace/codebases") / tournament_name,
        Path("workspace/submissions") / tournament_name,
        Path("workspace/posts") / tournament_name,
    ]:
        if root.exists():
            shutil.rmtree(root)
    round_dir = Path("logs") / "round_1"
    if round_dir.exists():
        shutil.rmtree(round_dir)


def _execution_smoke_model_entries(roster_models: list[dict]) -> list[dict]:
    entries: list[dict] = []
    for idx, entry in enumerate(roster_models, start=1):
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("id")
        if not isinstance(model_id, str) or not model_id.strip():
            model_id = f"model_{idx}"
        agent_id = entry.get("agent_id")
        if not isinstance(agent_id, str) or not agent_id.strip():
            agent_id = model_id
        entries.append(
            {
                "id": model_id,
                "agent_id": agent_id,
                "provider_model": entry.get("provider_model"),
                "executor": entry.get("executor"),
            }
        )
    return entries


def _cleanup_tournament_state(tournament_name: str) -> None:
    for root in [
        Path("workspace/codebases") / tournament_name,
        Path("workspace/submissions") / tournament_name,
        Path("workspace/posts") / tournament_name,
    ]:
        if root.exists():
            shutil.rmtree(root)


def _stable_pair_seed(pair_id: str, base_seed: int) -> int:
    material = f"{pair_id}|{base_seed}"
    return int(hashlib.sha256(material.encode("utf-8")).hexdigest()[:8], 16) & 0x7FFFFFFF


def _sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_diff_targets(diff_path: Path, before_dir: Path, after_dir: Path) -> list[str]:
    if not diff_path.exists():
        return []
    try:
        text = diff_path.read_text(encoding="utf-8")
    except Exception:
        return []
    targets: list[str] = []
    seen: set[str] = set()
    before_dir_resolved = before_dir.resolve()
    after_dir_resolved = after_dir.resolve()
    for line in text.splitlines():
        if not (line.startswith("--- ") or line.startswith("+++ ")):
            continue
        raw = line[4:].strip()
        if raw == "/dev/null":
            continue
        rel: str | None = None
        if raw.startswith("/dev/null:"):
            rel = raw.split(":", 1)[1]
        else:
            try:
                p = Path(raw).resolve()
                if before_dir_resolved in p.parents:
                    rel = str(p.relative_to(before_dir_resolved))
                elif after_dir_resolved in p.parents:
                    rel = str(p.relative_to(after_dir_resolved))
            except Exception:
                rel = None
        if rel is None:
            continue
        rel_norm = rel.replace("\\", "/")
        if rel_norm in seen:
            continue
        seen.add(rel_norm)
        targets.append(rel_norm)
    return targets


def _collect_submission_change_fields(
    *,
    codebase: Path,
    post: Path,
    diff_path: Path,
    changed_files_reported_by_openclaw: list[str],
) -> dict:
    before_hash = _sha256_file(codebase / "submission" / "main.py")
    after_hash = _sha256_file(post / "submission" / "main.py")
    effective_submission_changed = before_hash != after_hash
    changed_files_hash_based = ["submission/main.py"] if effective_submission_changed else []
    changed_files_inconsistent_with_hash = ("submission/main.py" in changed_files_reported_by_openclaw) and (
        not effective_submission_changed
    )
    diff_targets = _extract_diff_targets(diff_path, codebase, post)
    diff_bytes = diff_path.stat().st_size if diff_path.exists() else 0
    return {
        "submission_main_sha256_before": before_hash,
        "submission_main_sha256_after": after_hash,
        "effective_submission_changed": effective_submission_changed,
        "changed_files_hash_based": changed_files_hash_based,
        "diff_bytes": diff_bytes,
        "diff_targets": diff_targets,
        "changed_files_reported_by_openclaw": changed_files_reported_by_openclaw,
        "changed_files_inconsistent_with_hash": changed_files_inconsistent_with_hash,
    }


def _extract_openclaw_route_provenance(audit_payload: dict | None) -> tuple[str, str | None, str | None, bool]:
    ad = audit_payload if isinstance(audit_payload, dict) else {}
    provider_route_status = ad.get("providerRouteStatus", "unknown")
    if not isinstance(provider_route_status, str) or not provider_route_status:
        provider_route_status = "unknown"
    actual_provider = ad.get("actualProvider")
    if not isinstance(actual_provider, str) or not actual_provider.strip():
        actual_provider = None
    actual_model = ad.get("actualModel")
    if not isinstance(actual_model, str) or not actual_model.strip():
        actual_model = None

    fallback_used = False
    fb = ad.get("fallbackUsed")
    if isinstance(fb, bool):
        fallback_used = fb
    else:
        oa = ad.get("openclawAudit")
        if isinstance(oa, dict):
            trace = oa.get("executionTrace")
            if isinstance(trace, dict) and isinstance(trace.get("fallbackUsed"), bool):
                fallback_used = bool(trace.get("fallbackUsed"))
    return provider_route_status, actual_provider, actual_model, fallback_used


def _route_provenance_verified(
    *,
    provider_route_status: str,
    actual_provider: str | None,
    actual_model: str | None,
    fallback_used: bool,
) -> bool:
    if provider_route_status != "matched":
        return False
    if not isinstance(actual_provider, str) or not actual_provider.strip():
        return False
    if not isinstance(actual_model, str) or not actual_model.strip():
        return False
    if fallback_used:
        return False
    return True


def _roster_entries(roster_models: list[dict]) -> list[dict]:
    entries: list[dict] = []
    for idx, entry in enumerate(roster_models, start=1):
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("id")
        if not isinstance(model_id, str) or not model_id.strip():
            model_id = f"model_{idx}"
        agent_id = entry.get("agent_id")
        if not isinstance(agent_id, str) or not agent_id.strip():
            agent_id = model_id
        entries.append(
            {
                "id": model_id,
                "agent_id": agent_id,
                "provider_model": entry.get("provider_model"),
                "executor": entry.get("executor"),
                "stratum": entry.get("stratum"),
            }
        )
    return entries


def _initial_strategy_profiles() -> list[tuple[str, str]]:
    return [
        (
            "valid_action_survival",
            "Preserve valid actions, defensive parsing, and survival-oriented behavior while making purposeful decisions.",
        ),
        (
            "mobility_preservation",
            "Prioritize movement choices that preserve future options and avoid avoidable self-destruction.",
        ),
        (
            "escape_route_awareness",
            "Prioritize actions that maintain escape routes and avoid becoming trapped by hazards.",
        ),
        (
            "measured_bomb_usage",
            "Use available actions proactively only when basic escape and validity safeguards remain intact.",
        ),
        (
            "space_control_balance",
            "Balance survival with purposeful board-position changes without relying on hidden state.",
        ),
        (
            "robust_observation_handling",
            "Handle partial observations defensively while making non-passive valid action choices.",
        ),
    ]


def _assign_initial_strategy_profiles(roster_entries: list[dict]) -> dict[str, tuple[str, str]]:
    profiles = _initial_strategy_profiles()
    assignments: dict[str, tuple[str, str]] = {}
    for idx, entry in enumerate(roster_entries):
        agent_id = entry.get("agent_id") if isinstance(entry, dict) else None
        if not isinstance(agent_id, str) or not agent_id:
            continue
        assignments[agent_id] = profiles[idx % len(profiles)]
    return assignments


def _get_initial_strategy_profile(agent_id: str, profile_assignments: dict[str, tuple[str, str]] | None = None) -> tuple[str, str]:
    if profile_assignments and agent_id in profile_assignments:
        return profile_assignments[agent_id]
    profiles = _initial_strategy_profiles()
    idx = int(hashlib.sha256(agent_id.encode("utf-8")).hexdigest()[:8], 16) % len(profiles)
    return profiles[idx]


def _run_execution_smoke_tournament(
    *,
    adapter,
    game_cfg: dict,
    tournament: dict,
    regime: dict,
    roster_models: list[dict],
    starter_repo: Path,
    valid: bool,
    validate_msg: str,
    smoke_only: bool,
) -> None:
    tournament_name = tournament["name"]
    _execution_smoke_cleanup(tournament_name)

    round_dir = Path("logs") / "round_1"
    round_dir.mkdir(parents=True, exist_ok=True)

    roster_entries = _execution_smoke_model_entries(roster_models)
    round_pairs = _execution_smoke_round_robin_round(roster_entries)
    base_seed = _execution_smoke_base_seed(tournament)

    round_manifest_matches: list[dict] = []

    for match_slot, (left_meta, right_meta) in enumerate(round_pairs, start=1):
        match_dir = round_dir / f"match_{match_slot}"
        match_dir.mkdir(parents=True, exist_ok=True)

        left_id = left_meta["id"]
        right_id = right_meta["id"]
        left_agent_id = left_meta.get("agent_id") or left_id
        right_agent_id = right_meta.get("agent_id") or right_id
        left_provider_model = left_meta.get("provider_model")
        right_provider_model = right_meta.get("provider_model")
        left_executor = left_meta.get("executor")
        right_executor = right_meta.get("executor")

        left_codebase = Path("workspace/codebases") / tournament_name / left_agent_id / "codebase_play_1"
        right_codebase = Path("workspace/codebases") / tournament_name / right_agent_id / "codebase_play_1"
        left_submission = Path("workspace/submissions") / tournament_name / left_agent_id / "submission_1"
        right_submission = Path("workspace/submissions") / tournament_name / right_agent_id / "submission_1"
        left_post = Path("workspace/posts") / tournament_name / left_agent_id / "codebase_post_1"
        right_post = Path("workspace/posts") / tournament_name / right_agent_id / "codebase_post_1"

        copy_tree(starter_repo, left_codebase)
        copy_tree(starter_repo, right_codebase)

        left_export_ok, left_export_msg = adapter.export_submission(left_codebase, left_submission)
        right_export_ok, right_export_msg = adapter.export_submission(right_codebase, right_submission)

        if valid and left_export_ok and right_export_ok:
            match_result = adapter.run_match(left_codebase, right_codebase, match_dir, game_cfg)
        else:
            match_result = {
                "winner": "draw",
                "result": "validation_or_export_failed",
                "runtime_diagnostics": {
                    "compile_ok": False,
                    "runtime_ok": False,
                    "invalid_actions": 1,
                    "timeout": False,
                    "stderr_excerpt": validate_msg,
                    "validate_submission_ok": valid,
                    "validate_submission_msg": validate_msg,
                    "left_export_ok": left_export_ok,
                    "left_export_msg": left_export_msg,
                    "right_export_ok": right_export_ok,
                    "right_export_msg": right_export_msg,
                },
            }

        left_rev_ok, left_rev_msg = apply_minimal_revision(
            left_codebase,
            left_post,
            1,
            "left",
            game=tournament["game"],
            regime=regime["name"],
            model_id=left_id,
            executor=left_executor,
            openclaw_agent_id=left_meta.get("agent_id"),
            provider_model=left_provider_model,
        )
        right_rev_ok, right_rev_msg = apply_minimal_revision(
            right_codebase,
            right_post,
            1,
            "right",
            game=tournament["game"],
            regime=regime["name"],
            model_id=right_id,
            executor=right_executor,
            openclaw_agent_id=right_meta.get("agent_id"),
            provider_model=right_provider_model,
        )

        pair_id = "__vs__".join(sorted([left_id, right_id]))
        requested_seed = _execution_smoke_pair_seed(pair_id, base_seed)
        _write_round_seed_provenance(match_dir, requested_seed=requested_seed, applied_seed=None)
        (
            applied_seed,
            seed_control_status,
            seed_control_error,
            seed_methods_attempted,
            seed_method_applied,
            seed_env_seed_return,
        ) = _read_seed_provenance_from_match_dir(match_dir)

        metadata_payload = {
            "round_idx": 1,
            "match_idx": match_slot,
            "match_id": f"match_{match_slot}",
            "game": tournament["game"],
            "regime": regime["name"],
            "tournament": tournament_name,
            "execution_smoke": True,
            "smoke_only": smoke_only,
            "left_model_id": left_id,
            "left_agent_id": left_agent_id,
            "left_provider_model": left_provider_model,
            "left_executor": left_executor,
            "right_model_id": right_id,
            "right_agent_id": right_agent_id,
            "right_provider_model": right_provider_model,
            "right_executor": right_executor,
            "pair_id": pair_id,
            "seat_assignment": {
                "left": left_agent_id,
                "right": right_agent_id,
                "background_agents": ["dummy2", "dummy3"],
            },
            "background_agents": ["dummy2", "dummy3"],
            "requested_seed": requested_seed,
            "applied_seed": applied_seed,
            "seed": applied_seed if seed_control_status == "applied" else None,
            "seed_control_status": seed_control_status,
            "seed_control_error": seed_control_error,
            "seed_control_methods_attempted": seed_methods_attempted,
            "seed_control_method_applied": seed_method_applied,
            "seed_control_env_seed_return": seed_env_seed_return,
            "starter_repo": str(starter_repo),
            "validate_submission_ok": valid,
            "validate_submission_msg": validate_msg,
            "left_export_ok": left_export_ok,
            "left_export_msg": left_export_msg,
            "right_export_ok": right_export_ok,
            "right_export_msg": right_export_msg,
            "left_revision_ok": left_rev_ok,
            "left_revision_msg": left_rev_msg,
            "right_revision_ok": right_rev_ok,
            "right_revision_msg": right_rev_msg,
            "left_codebase_path": str(left_codebase),
            "right_codebase_path": str(right_codebase),
            "left_submission_path": str(left_submission),
            "right_submission_path": str(right_submission),
            "left_post_path": str(left_post),
            "right_post_path": str(right_post),
            "metadata_path": str(match_dir / "metadata.json"),
            "scorecard_path": str(match_dir / "scorecard.json"),
            "arena_result_match_a_path": str(match_dir / "arena_result_match_a.json"),
            "status": "execution-smoke-complete",
            "winner": match_result["winner"],
            "result": match_result["result"],
        }

        write_json(match_dir / "metadata.json", metadata_payload)
        write_process_feedback(match_dir, round_idx=1, match_idx=match_slot)

        round_manifest_matches.append(
            {
                "match_id": f"match_{match_slot}",
                "match_idx": match_slot,
                "left_agent_id": left_agent_id,
                "right_agent_id": right_agent_id,
                "left_submission_path": str(left_submission),
                "right_submission_path": str(right_submission),
                "requested_seed": requested_seed,
                "applied_seed": applied_seed,
                "seed": applied_seed if seed_control_status == "applied" else None,
                "seed_control_status": seed_control_status,
                "seed_control_error": seed_control_error,
                "seed_control_methods_attempted": seed_methods_attempted,
                "seed_control_method_applied": seed_method_applied,
                "seed_control_env_seed_return": seed_env_seed_return,
                "seat_assignment": {
                    "left": left_agent_id,
                    "right": right_agent_id,
                    "background_agents": ["dummy2", "dummy3"],
                },
                "background_agents": ["dummy2", "dummy3"],
                "metadata_path": str(match_dir / "metadata.json"),
                "scorecard_path": str(match_dir / "scorecard.json"),
                "arena_result_match_a_path": str(match_dir / "arena_result_match_a.json"),
                "pair_id": pair_id,
                "schedule_mode": "double_round_robin",
                "match_legs": "single",
            }
        )

    round_manifest_payload = {
        "round_idx": 1,
        "matches_per_round": len(round_manifest_matches),
        "matches": round_manifest_matches,
        "execution_smoke": True,
        "background_agents": ["dummy2", "dummy3"],
        "scorecard_policy": "raw_per_match_scorecard; pair-level aggregation is post-analysis",
    }
    write_json(round_dir / "round_manifest.json", round_manifest_payload)


def _run_adaptive_dryrun_tournament(
    *,
    adapter,
    game_cfg: dict,
    tournament: dict,
    regime: dict,
    roster_models: list[dict],
    starter_repo: Path,
    valid: bool,
    validate_msg: str,
    smoke_only: bool,
) -> None:
    tournament_name = tournament["name"]
    _cleanup_tournament_state(tournament_name)
    base_seed = _execution_smoke_base_seed(tournament)
    entries = _roster_entries(roster_models)
    agent_ids = [e["agent_id"] for e in entries]
    model_by_agent = {e["agent_id"]: e for e in entries}
    schedule = build_double_round_robin(agent_ids, num_rounds=int(tournament.get("num_rounds", 0) or 0))

    latest_post_by_agent: dict[str, Path] = {}
    for round_info in schedule["rounds"]:
        round_idx = int(round_info["round_idx"])
        round_dir = Path("logs") / f"round_{round_idx}"
        round_dir.mkdir(parents=True, exist_ok=True)
        round_manifest_matches: list[dict] = []

        for match in round_info["matches"]:
            match_idx = int(match["match_idx"])
            match_dir = round_dir / f"match_{match_idx}"
            match_dir.mkdir(parents=True, exist_ok=True)

            left_agent_id = str(match["left_agent"])
            right_agent_id = str(match["right_agent"])
            left_meta = model_by_agent[left_agent_id]
            right_meta = model_by_agent[right_agent_id]

            left_id = left_meta["id"]
            right_id = right_meta["id"]
            left_codebase = (
                Path("workspace/codebases") / tournament_name / left_agent_id / f"codebase_play_{round_idx}"
            )
            right_codebase = (
                Path("workspace/codebases") / tournament_name / right_agent_id / f"codebase_play_{round_idx}"
            )
            left_submission = (
                Path("workspace/submissions") / tournament_name / left_agent_id / f"submission_{round_idx}"
            )
            right_submission = (
                Path("workspace/submissions") / tournament_name / right_agent_id / f"submission_{round_idx}"
            )
            left_post = Path("workspace/posts") / tournament_name / left_agent_id / f"codebase_post_{round_idx}"
            right_post = Path("workspace/posts") / tournament_name / right_agent_id / f"codebase_post_{round_idx}"

            left_source = latest_post_by_agent.get(left_agent_id, starter_repo)
            right_source = latest_post_by_agent.get(right_agent_id, starter_repo)
            copy_tree(left_source, left_codebase)
            copy_tree(right_source, right_codebase)

            left_export_ok, left_export_msg = adapter.export_submission(left_codebase, left_submission)
            right_export_ok, right_export_msg = adapter.export_submission(right_codebase, right_submission)
            if valid and left_export_ok and right_export_ok:
                match_result = adapter.run_match(left_codebase, right_codebase, match_dir, game_cfg)
            else:
                match_result = {
                    "winner": "draw",
                    "result": "validation_or_export_failed",
                    "runtime_diagnostics": {
                        "compile_ok": False,
                        "runtime_ok": False,
                        "invalid_actions": 1,
                        "timeout": False,
                        "stderr_excerpt": validate_msg,
                        "validate_submission_ok": valid,
                        "validate_submission_msg": validate_msg,
                        "left_export_ok": left_export_ok,
                        "left_export_msg": left_export_msg,
                        "right_export_ok": right_export_ok,
                        "right_export_msg": right_export_msg,
                    },
                }

            left_rev_ok, left_rev_msg = apply_noop_revision(left_codebase, left_post, round_idx, "left")
            right_rev_ok, right_rev_msg = apply_noop_revision(right_codebase, right_post, round_idx, "right")

            pair_id = str(match["pair_id"])
            requested_seed = _stable_pair_seed(pair_id, base_seed)
            _write_round_seed_provenance(match_dir, requested_seed=requested_seed, applied_seed=None)
            (
                applied_seed,
                seed_control_status,
                seed_control_error,
                seed_methods_attempted,
                seed_method_applied,
                seed_env_seed_return,
            ) = _read_seed_provenance_from_match_dir(match_dir)

            metadata_payload = {
                "round_idx": round_idx,
                "match_idx": match_idx,
                "match_id": f"match_{match_idx}",
                "game": tournament["game"],
                "regime": regime["name"],
                "tournament": tournament_name,
                "adaptive_dryrun": True,
                "low_cost_revision": True,
                "revision_executor": "dryrun-noop",
                "smoke_only": smoke_only,
                "left_model_id": left_id,
                "left_agent_id": left_agent_id,
                "right_model_id": right_id,
                "right_agent_id": right_agent_id,
                "pair_id": pair_id,
                "cycle": int(match["cycle"]),
                "seat_assignment": {
                    "left": left_agent_id,
                    "right": right_agent_id,
                    "background_agents": ["dummy2", "dummy3"],
                },
                "background_agents": ["dummy2", "dummy3"],
                "requested_seed": requested_seed,
                "applied_seed": applied_seed,
                "seed": applied_seed if seed_control_status == "applied" else None,
                "seed_control_status": seed_control_status,
                "seed_control_error": seed_control_error,
                "seed_control_methods_attempted": seed_methods_attempted,
                "seed_control_method_applied": seed_method_applied,
                "seed_control_env_seed_return": seed_env_seed_return,
                "scorecard_policy": "raw_per_match_scorecard; pair-level aggregation is post-analysis",
                "left_source_path": str(left_source),
                "right_source_path": str(right_source),
                "left_export_ok": left_export_ok,
                "left_export_msg": left_export_msg,
                "right_export_ok": right_export_ok,
                "right_export_msg": right_export_msg,
                "left_revision_ok": left_rev_ok,
                "left_revision_msg": left_rev_msg,
                "right_revision_ok": right_rev_ok,
                "right_revision_msg": right_rev_msg,
                "left_codebase_path": str(left_codebase),
                "right_codebase_path": str(right_codebase),
                "left_submission_path": str(left_submission),
                "right_submission_path": str(right_submission),
                "left_post_path": str(left_post),
                "right_post_path": str(right_post),
                "metadata_path": str(match_dir / "metadata.json"),
                "scorecard_path": str(match_dir / "scorecard.json"),
                "arena_result_match_a_path": str(match_dir / "arena_result_match_a.json"),
                "schedule_mode": "double_round_robin",
                "match_legs": "single",
                "winner": match_result["winner"],
                "result": match_result["result"],
            }
            write_json(match_dir / "metadata.json", metadata_payload)
            write_process_feedback(match_dir, round_idx=round_idx, match_idx=match_idx)

            round_manifest_matches.append(
                {
                    "match_id": f"match_{match_idx}",
                    "match_idx": match_idx,
                    "pair_id": pair_id,
                    "left_agent_id": left_agent_id,
                    "right_agent_id": right_agent_id,
                    "left_submission_path": str(left_submission),
                    "right_submission_path": str(right_submission),
                    "seat_assignment": metadata_payload["seat_assignment"],
                    "background_agents": ["dummy2", "dummy3"],
                    "requested_seed": requested_seed,
                    "applied_seed": applied_seed,
                    "seed": applied_seed if seed_control_status == "applied" else None,
                    "seed_control_status": seed_control_status,
                    "seed_control_error": seed_control_error,
                    "seed_control_methods_attempted": seed_methods_attempted,
                    "seed_control_method_applied": seed_method_applied,
                    "seed_control_env_seed_return": seed_env_seed_return,
                    "metadata_path": str(match_dir / "metadata.json"),
                    "scorecard_path": str(match_dir / "scorecard.json"),
                    "arena_result_match_a_path": str(match_dir / "arena_result_match_a.json"),
                    "schedule_mode": "double_round_robin",
                    "match_legs": "single",
                }
            )
            latest_post_by_agent[left_agent_id] = left_post
            latest_post_by_agent[right_agent_id] = right_post

        write_json(
            round_dir / "round_manifest.json",
            {
                "round_idx": round_idx,
                "matches_per_round": len(round_manifest_matches),
                "cycle": int(round_info["cycle"]),
                "adaptive_dryrun": True,
                "low_cost_revision": True,
                "revision_executor": "dryrun-noop",
                "background_agents": ["dummy2", "dummy3"],
                "scorecard_policy": "raw_per_match_scorecard; pair-level aggregation is post-analysis",
                "matches": round_manifest_matches,
            },
        )


def _run_openclaw_adaptive_smoke_tournament(
    *,
    adapter,
    game_cfg: dict,
    tournament: dict,
    regime: dict,
    roster_models: list[dict],
    starter_repo: Path,
    valid: bool,
    validate_msg: str,
    smoke_only: bool,
) -> None:
    tournament_name = tournament["name"]
    _cleanup_tournament_state(tournament_name)
    num_rounds = int(tournament.get("num_rounds", 0) or 0)
    if num_rounds < 2:
        raise ValueError("openclaw_adaptive_smoke requires num_rounds >= 2")
    revision_rounds_raw = tournament.get("revision_rounds", [1])
    if not isinstance(revision_rounds_raw, list):
        raise ValueError("openclaw_adaptive_smoke requires revision_rounds as a list")
    revision_rounds = sorted({int(x) for x in revision_rounds_raw if int(x) >= 1})
    if not revision_rounds:
        raise ValueError("openclaw_adaptive_smoke requires at least one revision round")
    for r in revision_rounds:
        if r >= num_rounds:
            raise ValueError("each revision_round must be strictly less than num_rounds")

    for ridx in range(1, num_rounds + 1):
        rd = Path(f"logs/round_{ridx}")
        if rd.exists():
            shutil.rmtree(rd)
        rd.mkdir(parents=True, exist_ok=True)

    entries = _roster_entries(roster_models)
    agent_ids = [e["agent_id"] for e in entries]
    model_by_agent = {e["agent_id"]: e for e in entries}
    profile_assignments = _assign_initial_strategy_profiles(entries)
    schedule = build_double_round_robin(agent_ids, num_rounds=num_rounds)
    rounds = schedule["rounds"][:num_rounds]
    base_seed = _execution_smoke_base_seed(tournament)
    openclaw_runner_agent_id = str(tournament.get("openclaw_runner_agent_id", "main"))
    require_effective_submission_change = bool(tournament.get("require_effective_submission_change", False))
    revision_retry_on_noop = int(tournament.get("revision_retry_on_noop", 0) or 0)
    initial_synthesis = bool(tournament.get("initial_synthesis", False))
    real_openclaw_initial_synthesis = bool(tournament.get("real_openclaw_initial_synthesis", False))
    initial_synthesis_executor = str(tournament.get("initial_synthesis_executor", "openclaw-minimal"))
    require_all_agents_initial_synthesized = bool(tournament.get("require_all_agents_initial_synthesized", False))
    require_effective_initial_submission_change = bool(tournament.get("require_effective_initial_submission_change", False))
    initial_synthesis_retry_on_noop = int(tournament.get("initial_synthesis_retry_on_noop", 0) or 0)
    initial_synthesis_retry_on_route_unknown = int(tournament.get("initial_synthesis_retry_on_route_unknown", 0) or 0)
    initial_synthesis_retry_on_timeout = int(tournament.get("initial_synthesis_retry_on_timeout", 0) or 0)
    revision_retry_on_route_unknown = int(tournament.get("revision_retry_on_route_unknown", 0) or 0)
    revision_retry_on_timeout = int(tournament.get("revision_retry_on_timeout", 0) or 0)
    initial_synthesis_prompt_variant = str(tournament.get("initial_synthesis_prompt_variant", "anti_draw_coached"))
    revision_prompt_variant = str(tournament.get("revision_prompt_variant", "anti_draw_coached"))
    valid_prompt_variants = {"anti_draw_coached", "neutral"}
    if initial_synthesis_prompt_variant not in valid_prompt_variants:
        raise ValueError(
            f"unsupported initial_synthesis_prompt_variant={initial_synthesis_prompt_variant}; "
            "expected one of ['anti_draw_coached', 'neutral']"
        )
    if revision_prompt_variant not in valid_prompt_variants:
        raise ValueError(
            f"unsupported revision_prompt_variant={revision_prompt_variant}; "
            "expected one of ['anti_draw_coached', 'neutral']"
        )

    feedback_package_variant = str(tournament.get("feedback_package_variant", "") or "").strip()
    feedback_visibility = str(tournament.get("feedback_visibility", "own_matches_plus_public_scoreboard") or "").strip()
    if not feedback_visibility:
        feedback_visibility = "own_matches_plus_public_scoreboard"
    if feedback_package_variant and feedback_package_variant not in {"codeclash_v3", "codeclash_v4"}:
        raise ValueError(
            f"unsupported feedback_package_variant={feedback_package_variant}; expected 'codeclash_v3', 'codeclash_v4', or unset"
        )
    if feedback_package_variant in {"codeclash_v3", "codeclash_v4"} and feedback_visibility != "own_matches_plus_public_scoreboard":
        raise ValueError(
            f"unsupported feedback_visibility={feedback_visibility}; expected 'own_matches_plus_public_scoreboard'"
        )

    latest_post_by_agent: dict[str, Path] = {}
    revision_manifests_by_round: dict[int, dict[str, dict]] = {}

    if initial_synthesis:
        if not real_openclaw_initial_synthesis:
            raise ValueError("initial_synthesis=true requires real_openclaw_initial_synthesis=true")
        logs_root = Path("logs")
        logs_root.mkdir(parents=True, exist_ok=True)
        initial_manifest_entries: list[dict] = []
        initial_round_one_propagation_entries: list[dict] = []
        starter_submission_path = starter_repo / "submission" / "main.py"
        starter_submission_sha256 = _sha256_file(starter_submission_path)
        failed_initial_entries: list[dict] = []

        for agent_id in agent_ids:
            meta = model_by_agent[agent_id]
            provider_model = meta.get("provider_model")
            executor = initial_synthesis_executor or meta.get("executor")
            initial_base = Path("workspace/codebases") / tournament_name / agent_id / "codebase_initial_base_0"
            initial_post = Path("workspace/posts") / tournament_name / agent_id / "codebase_initial_post_0"
            play_1 = Path("workspace/codebases") / tournament_name / agent_id / "codebase_play_1"
            initial_diff_path = Path("logs") / f"initial_synthesis_{agent_id}.diff.patch"
            copy_tree(starter_repo, initial_base)
            strategy_profile_id, strategy_profile_text = _get_initial_strategy_profile(agent_id, profile_assignments)
            route_retry_budget = max(
                initial_synthesis_retry_on_route_unknown,
                initial_synthesis_retry_on_noop,
                initial_synthesis_retry_on_timeout,
            )
            attempt_count = 0
            ok = False
            msg = "initial synthesis failed"
            requested_provider_model = provider_model
            actual_provider = None
            actual_model = None
            provider_route_status = "unknown"
            fallback_used = False
            changed_files_reported_by_openclaw: list[str] = []
            ignored_changed_files: list[str] = []
            disallowed_changed_files: list[str] = []
            audit_errors: list[str] = []
            openclaw_timeout_seconds = None
            starter_hash = _sha256_file(initial_base / "submission" / "main.py")
            initial_hash = _sha256_file(initial_post / "submission" / "main.py")
            effective_initial_changed = False
            initial_changed_files_hash_based: list[str] = []
            failure_reason = None
            initial_synthesis_ok = False

            for attempt in range(route_retry_budget + 1):
                attempt_count = attempt + 1
                ok, msg = apply_minimal_initial_synthesis(
                    initial_base,
                    initial_post,
                    game=tournament["game"],
                    regime=regime["name"],
                    model_id=meta["id"],
                    executor=executor,
                    openclaw_agent_id=openclaw_runner_agent_id,
                    provider_model=provider_model,
                    require_effective_submission_change=require_effective_initial_submission_change,
                    initial_synthesis_retry_on_noop=initial_synthesis_retry_on_noop,
                    initial_synthesis_retry_on_timeout=initial_synthesis_retry_on_timeout,
                    strategy_profile_id=strategy_profile_id,
                    strategy_profile_text=strategy_profile_text,
                    prompt_variant=initial_synthesis_prompt_variant,
                )
                write_diff_patch(initial_base, initial_post, initial_diff_path)
                initial_audit_json = initial_post / "revision_audit.json"
                requested_provider_model = provider_model
                actual_provider = None
                actual_model = None
                provider_route_status = "unknown"
                fallback_used = False
                changed_files_reported_by_openclaw = []
                ignored_changed_files = []
                disallowed_changed_files = []
                audit_errors = []
                openclaw_timeout_seconds = None
                audit_payload: dict | None = None
                if initial_audit_json.exists():
                    try:
                        audit_payload = json.loads(initial_audit_json.read_text(encoding="utf-8"))
                        requested_provider_model = audit_payload.get("requestedProviderModel", requested_provider_model)
                        changed_files_reported_by_openclaw = audit_payload.get("changedFiles", []) or []
                        ignored_changed_files = audit_payload.get("ignoredChangedFiles", []) or []
                        disallowed_changed_files = audit_payload.get("disallowedChangedFiles", []) or []
                        audit_errors = audit_payload.get("errors", []) or []
                        openclaw_timeout_seconds = audit_payload.get("openclawTimeoutSeconds")
                    except Exception as exc:
                        audit_errors = [f"failed_to_read_revision_audit:{exc!r}"]
                provider_route_status, actual_provider, actual_model, fallback_used = _extract_openclaw_route_provenance(
                    audit_payload
                )
                route_provenance_verified = _route_provenance_verified(
                    provider_route_status=provider_route_status,
                    actual_provider=actual_provider,
                    actual_model=actual_model,
                    fallback_used=fallback_used,
                )

                starter_hash = _sha256_file(initial_base / "submission" / "main.py")
                initial_hash = _sha256_file(initial_post / "submission" / "main.py")
                effective_initial_changed = starter_hash != initial_hash
                initial_changed_files_hash_based = ["submission/main.py"] if effective_initial_changed else []
                initial_synthesis_ok = bool(ok) and route_provenance_verified
                if any(isinstance(err, str) and "openclaw context overflow" in err.lower() for err in audit_errors):
                    initial_synthesis_ok = False
                    failure_reason = "openclaw context overflow"
                elif require_effective_initial_submission_change and not effective_initial_changed:
                    initial_synthesis_ok = False
                    failure_reason = "OpenClaw initial synthesis made no effective submission/main.py change"
                elif any(isinstance(err, str) and "openclaw timeout" in err for err in audit_errors):
                    initial_synthesis_ok = False
                    failure_reason = "openclaw timeout"
                elif not bool(ok):
                    failure_reason = msg
                elif not route_provenance_verified and effective_initial_changed:
                    failure_reason = "OpenClaw route provenance missing despite code change"
                elif not route_provenance_verified:
                    failure_reason = "OpenClaw route provenance missing"
                else:
                    failure_reason = None
                if route_provenance_verified is False and fallback_used:
                    failure_reason = "OpenClaw fallback used during initial synthesis"
                is_timeout = failure_reason == "openclaw timeout" or "timeout" in str(msg).lower()
                is_context_overflow = (
                    failure_reason == "openclaw context overflow"
                    or "context overflow" in str(msg).lower()
                )

                if initial_synthesis_ok:
                    break
                if is_timeout and attempt < initial_synthesis_retry_on_timeout:
                    continue
                if is_context_overflow and attempt < route_retry_budget:
                    continue
                if (
                    (not route_provenance_verified)
                    and attempt < route_retry_budget
                ):
                    continue
                break

            initial_entry = {
                "agent_id": agent_id,
                "model_id": meta["id"],
                "provider_model": provider_model,
                "executor": executor,
                "starter_submission_sha256": starter_hash if starter_hash is not None else starter_submission_sha256,
                "initial_submission_sha256": initial_hash,
                "effective_initial_submission_changed": effective_initial_changed,
                "initial_changed_files_hash_based": initial_changed_files_hash_based,
                "initial_provider_route_status": provider_route_status,
                "initial_requested_provider_model": requested_provider_model,
                "initial_actual_provider": actual_provider,
                "initial_actual_model": actual_model,
                "initial_fallback_used": fallback_used,
                "initial_strategy_profile_id": strategy_profile_id,
                "initial_strategy_profile_text": strategy_profile_text,
                "initial_synthesis_prompt_variant": initial_synthesis_prompt_variant,
                "initial_openclaw_invoked": True,
                "initial_synthesis_ok": initial_synthesis_ok,
                "initial_failure_reason": failure_reason,
                "initial_diff_path": str(initial_diff_path),
                "initial_diff_bytes": initial_diff_path.stat().st_size if initial_diff_path.exists() else 0,
                "initial_openclaw_timeout_seconds": openclaw_timeout_seconds,
                "initial_ignored_changed_files": ignored_changed_files,
                "initial_disallowed_changed_files": disallowed_changed_files,
                "initial_changed_files_reported_by_openclaw": changed_files_reported_by_openclaw,
                "initial_audit_errors": audit_errors,
                "initial_attempt_count": attempt_count,
                "codebase_initial_base_path": str(initial_base),
                "codebase_initial_post_path": str(initial_post),
                "codebase_play_1_path": str(play_1),
            }
            initial_manifest_entries.append(initial_entry)

            if not initial_synthesis_ok:
                failed_initial_entries.append(initial_entry)
                source_submission_sha256 = _sha256_file(initial_post / "submission" / "main.py")
                initial_round_one_propagation_entries.append(
                    {
                        "agent_id": agent_id,
                        "source_initial_post_path": str(initial_post),
                        "target_play_path": str(play_1),
                        "source_round": 0,
                        "target_round": 1,
                        "source_submission_sha256": source_submission_sha256,
                        "target_submission_sha256": None,
                        "propagation_matches_post": False,
                        "propagated": False,
                        "propagation_ok": False,
                    }
                )
                continue

            copy_tree(initial_post, play_1)
            source_submission_sha256 = _sha256_file(initial_post / "submission" / "main.py")
            target_submission_sha256 = _sha256_file(play_1 / "submission" / "main.py")
            initial_round_one_propagation_entries.append(
                {
                    "agent_id": agent_id,
                    "source_initial_post_path": str(initial_post),
                    "target_play_path": str(play_1),
                    "source_round": 0,
                    "target_round": 1,
                    "source_submission_sha256": source_submission_sha256,
                    "target_submission_sha256": target_submission_sha256,
                    "propagation_matches_post": source_submission_sha256 == target_submission_sha256,
                    "propagated": True,
                    "propagation_ok": source_submission_sha256 == target_submission_sha256,
                }
            )

        write_json(
            Path("logs/initial_synthesis_manifest.json"),
            {
                "tournament": tournament_name,
                "initial_synthesis": True,
                "real_openclaw_initial_synthesis": real_openclaw_initial_synthesis,
                "require_all_agents_initial_synthesized": require_all_agents_initial_synthesized,
                "require_effective_initial_submission_change": require_effective_initial_submission_change,
                "initial_synthesis_retry_on_noop": initial_synthesis_retry_on_noop,
                "initial_synthesis_retry_on_route_unknown": initial_synthesis_retry_on_route_unknown,
                "agents": initial_manifest_entries,
            },
        )
        write_json(
            Path("logs/round_1/initial_propagation_manifest.json"),
            {
                "round_idx": 1,
                "agents": initial_round_one_propagation_entries,
            },
        )
        if require_all_agents_initial_synthesized and failed_initial_entries:
            reasons = "; ".join(
                f"{x['agent_id']}:{x.get('initial_failure_reason') or 'initial synthesis failed'}"
                for x in failed_initial_entries
            )
            raise RuntimeError(f"initial synthesis failed for required agents: {reasons}")
        for rec in initial_round_one_propagation_entries:
            if not bool(rec.get("propagation_matches_post", False)):
                raise RuntimeError(f"initial propagation hash mismatch for agent {rec.get('agent_id')}")
        latest_post_by_agent = {
            agent_id: Path("workspace/posts") / tournament_name / agent_id / "codebase_initial_post_0"
            for agent_id in agent_ids
            if (Path("workspace/posts") / tournament_name / agent_id / "codebase_initial_post_0").exists()
        }

    for round_pos, round_info in enumerate(rounds, start=1):
        round_idx = int(round_info["round_idx"])
        round_dir = Path(f"logs/round_{round_idx}")
        round_matches: list[dict] = []
        feedback_package_path = round_dir / "feedback_package.json"
        feedback_payload_written = False

        for match in round_info["matches"]:
            match_idx = int(match["match_idx"])
            match_dir = round_dir / f"match_{match_idx}"
            match_dir.mkdir(parents=True, exist_ok=True)

            left_agent_id = str(match["left_agent"])
            right_agent_id = str(match["right_agent"])
            left_meta = model_by_agent[left_agent_id]
            right_meta = model_by_agent[right_agent_id]
            pair_id = str(match["pair_id"])

            left_play = Path("workspace/codebases") / tournament_name / left_agent_id / f"codebase_play_{round_idx}"
            right_play = Path("workspace/codebases") / tournament_name / right_agent_id / f"codebase_play_{round_idx}"
            left_submission = Path("workspace/submissions") / tournament_name / left_agent_id / f"submission_{round_idx}"
            right_submission = Path("workspace/submissions") / tournament_name / right_agent_id / f"submission_{round_idx}"
            left_post = Path("workspace/posts") / tournament_name / left_agent_id / f"codebase_post_{round_idx}"
            right_post = Path("workspace/posts") / tournament_name / right_agent_id / f"codebase_post_{round_idx}"

            left_source = latest_post_by_agent.get(left_agent_id, starter_repo)
            right_source = latest_post_by_agent.get(right_agent_id, starter_repo)
            copy_tree(left_source, left_play)
            copy_tree(right_source, right_play)

            left_export_ok, left_export_msg = adapter.export_submission(left_play, left_submission)
            right_export_ok, right_export_msg = adapter.export_submission(right_play, right_submission)
            requested_seed = _stable_pair_seed(pair_id, base_seed)
            match_cfg = dict(game_cfg)
            match_cfg["requested_seed"] = requested_seed
            match_cfg["seed"] = requested_seed
            if valid and left_export_ok and right_export_ok:
                adapter.run_match(left_play, right_play, match_dir, match_cfg)
            else:
                invalid_result = {
                    "left_right_winner": "draw",
                    "steps": 0,
                    "done": False,
                    "reward": [0, 0, 0, 0],
                    "info": {"winners": []},
                    "arena_fallback_or_invalid": True,
                    "requested_seed": None,
                    "applied_seed": None,
                    "seed": None,
                    "seed_control_status": "requested_but_not_applied",
                }
                invalid_result.update(classify_pommerman_result(invalid_result))
                write_json(
                    match_dir / "scorecard.json",
                    invalid_result,
                )
                write_json(
                    match_dir / "arena_result_match_a.json",
                    invalid_result,
                )
            scorecard = {"left_right_winner": "draw"}
            sc_path = match_dir / "scorecard.json"
            if sc_path.exists():
                try:
                    sc_data = json.loads(sc_path.read_text(encoding="utf-8"))
                    scorecard["left_right_winner"] = sc_data.get("left_right_winner", "draw")
                except Exception:
                    pass
            if not feedback_payload_written:
                write_json(
                    feedback_package_path,
                    {
                        "meta": {"round_idx": round_idx, "match_id": f"{tournament_name}_round_{round_idx}_match_{match_idx}"},
                        "scorecard": scorecard,
                    },
                )
                feedback_payload_written = True

            _write_round_seed_provenance(match_dir, requested_seed=requested_seed, applied_seed=None)
            (
                applied_seed,
                seed_control_status,
                seed_control_error,
                seed_methods_attempted,
                seed_method_applied,
                seed_env_seed_return,
            ) = _read_seed_provenance_from_match_dir(match_dir)
            md_payload = {
                "round_idx": round_idx,
                "match_idx": match_idx,
                "match_id": f"match_{match_idx}",
                "openclaw_adaptive_smoke": True,
                "real_openclaw_revision": True,
                "low_budget_revision": True,
                "revision_executor": "openclaw-minimal",
                "left_agent_id": left_agent_id,
                "right_agent_id": right_agent_id,
                "pair_id": pair_id,
                "seat_assignment": {"left": left_agent_id, "right": right_agent_id, "background_agents": ["dummy2", "dummy3"]},
                "background_agents": ["dummy2", "dummy3"],
                "requested_seed": requested_seed,
                "applied_seed": applied_seed,
                "seed": applied_seed if seed_control_status == "applied" else None,
                "seed_control_status": seed_control_status,
                "seed_control_error": seed_control_error,
                "seed_control_methods_attempted": seed_methods_attempted,
                "seed_control_method_applied": seed_method_applied,
                "seed_control_env_seed_return": seed_env_seed_return,
                "scorecard_policy": "raw_per_match_scorecard; pair-level aggregation is post-analysis",
                "left_submission_path": str(left_submission),
                "right_submission_path": str(right_submission),
                "left_source_path": str(left_source),
                "right_source_path": str(right_source),
                "left_export_ok": left_export_ok,
                "left_export_msg": left_export_msg,
                "right_export_ok": right_export_ok,
                "right_export_msg": right_export_msg,
                "metadata_path": str(match_dir / "metadata.json"),
                "scorecard_path": str(sc_path),
                "arena_result_match_a_path": str(match_dir / "arena_result_match_a.json"),
                "official_record_json_match_a_path": str(match_dir / "official_record_json_match_a" / "game_state.json"),
                "schedule_mode": "double_round_robin",
                "match_legs": "single",
            }
            write_json(match_dir / "metadata.json", md_payload)
            write_process_feedback(match_dir, round_idx=round_idx, match_idx=match_idx)
            round_matches.append(
                {
                    "match_id": f"match_{match_idx}",
                    "match_idx": match_idx,
                    "pair_id": pair_id,
                    "left_agent_id": left_agent_id,
                    "right_agent_id": right_agent_id,
                    "left_submission_path": str(left_submission),
                    "right_submission_path": str(right_submission),
                    "seat_assignment": md_payload["seat_assignment"],
                    "background_agents": ["dummy2", "dummy3"],
                    "requested_seed": requested_seed,
                    "applied_seed": applied_seed,
                    "seed": applied_seed if seed_control_status == "applied" else None,
                    "seed_control_status": seed_control_status,
                    "seed_control_error": seed_control_error,
                    "seed_control_methods_attempted": seed_methods_attempted,
                    "seed_control_method_applied": seed_method_applied,
                    "seed_control_env_seed_return": seed_env_seed_return,
                    "metadata_path": str(match_dir / "metadata.json"),
                    "scorecard_path": str(sc_path),
                    "arena_result_match_a_path": str(match_dir / "arena_result_match_a.json"),
                    "official_record_json_match_a_path": str(match_dir / "official_record_json_match_a" / "game_state.json"),
                    "schedule_mode": "double_round_robin",
                    "match_legs": "single",
                }
            )

            # Keep post directories created for all rounds.
            if round_idx not in revision_rounds:
                apply_noop_revision(left_play, left_post, round_idx, "left")
                apply_noop_revision(right_play, right_post, round_idx, "right")
                latest_post_by_agent[left_agent_id] = left_post
                latest_post_by_agent[right_agent_id] = right_post

        write_json(
            round_dir / "round_manifest.json",
            {
                "round_idx": round_idx,
                "matches_per_round": len(round_matches),
                "cycle": int(round_info["cycle"]),
                "openclaw_adaptive_smoke": True,
                "real_openclaw_revision": True,
                "low_budget_revision": True,
                "revision_executor": "openclaw-minimal",
                "require_effective_submission_change": require_effective_submission_change,
                "revision_retry_on_noop": revision_retry_on_noop,
                "revision_retry_on_route_unknown": revision_retry_on_route_unknown,
                "revision_retry_on_timeout": revision_retry_on_timeout,
                "revision_prompt_variant": revision_prompt_variant,
                "feedback_package_variant": feedback_package_variant or None,
                "feedback_visibility": feedback_visibility or None,
                "initial_synthesis": initial_synthesis,
                "real_openclaw_initial_synthesis": real_openclaw_initial_synthesis,
                "initial_synthesis_executor": initial_synthesis_executor if initial_synthesis else None,
                "initial_synthesis_retry_on_timeout": initial_synthesis_retry_on_timeout if initial_synthesis else 0,
                "initial_synthesis_prompt_variant": initial_synthesis_prompt_variant if initial_synthesis else None,
                "scorecard_policy": "raw_per_match_scorecard; pair-level aggregation is post-analysis",
                "background_agents": ["dummy2", "dummy3"],
                "matches": round_matches,
            },
        )

        for match in round_info["matches"]:
            m_idx = int(match["match_idx"])
            mdir = round_dir / f"match_{m_idx}"
            write_feedback_artifact_mirrors(mdir, tournament_name, round_idx)

        if round_idx in revision_rounds:
            round_match_records_for_feedback: list[dict] = []
            for m in round_matches:
                try:
                    match_idx = int(m.get("match_idx", 0) or 0)
                except Exception:
                    match_idx = 0
                if match_idx <= 0:
                    continue
                round_match_records_for_feedback.append(
                    {
                        "match_id": str(m.get("match_id") or f"match_{match_idx}"),
                        "match_idx": match_idx,
                        "match_dir": str(round_dir / f"match_{match_idx}"),
                        "left_agent_id": str(m.get("left_agent_id") or ""),
                        "right_agent_id": str(m.get("right_agent_id") or ""),
                        "requested_seed": m.get("requested_seed"),
                        "applied_seed": m.get("applied_seed"),
                    }
                )

            # Feedback packages must exist for both participants of every match. Generate
            # all packages for the round *before* invoking OpenClaw so partial revision
            # failures cannot leave the tournament with incomplete feedback coverage.
            if feedback_package_variant in {"codeclash_v3", "codeclash_v4"} and round_match_records_for_feedback:
                try:
                    from runner.core.pommerman_feedback_package import stage_feedback_packages_for_round

                    stage_feedback_packages_for_round(
                        tournament_name=tournament_name,
                        round_idx=round_idx,
                        agent_ids=agent_ids,
                        round_match_records=round_match_records_for_feedback,
                        feedback_visibility=feedback_visibility or "own_matches_plus_public_scoreboard",
                        feedback_package_variant=feedback_package_variant,
                    )
                except Exception:
                    # Fail-open: feedback packages are audited separately and should not
                    # block revisions in smoke runs.
                    pass

            revision_manifest_for_round: dict[str, dict] = {}
            for agent_id in agent_ids:
                meta = model_by_agent[agent_id]
                provider_model = meta.get("provider_model")
                executor = meta.get("executor")
                codebase = Path("workspace/codebases") / tournament_name / agent_id / f"codebase_play_{round_idx}"
                post = Path("workspace/posts") / tournament_name / agent_id / f"codebase_post_{round_idx}"
                submission = Path("workspace/submissions") / tournament_name / agent_id / f"submission_{round_idx}"
                diff_path = round_dir / f"{agent_id}.diff.patch"
                feedback_artifact_paths: list[str] = []
                for match in round_info["matches"]:
                    if agent_id not in {str(match["left_agent"]), str(match["right_agent"])}:
                        continue
                    m_idx = int(match["match_idx"])
                    match_dir = round_dir / f"match_{m_idx}"
                    feedback_artifact_paths.extend(
                        [
                            str(match_dir / "scorecard.json"),
                            str(match_dir / "trajectory_summary.json"),
                            str(match_dir / "trajectory_events.json"),
                            str(match_dir / "arena_result_match_a.json"),
                            str(match_dir / f"agent_feedback_{agent_id}.md"),
                        ]
                    )
                route_retry_budget = max(revision_retry_on_route_unknown, revision_retry_on_noop, revision_retry_on_timeout)
                rev_ok = False
                rev_msg = "openclaw revision failed"
                requested_provider_model = provider_model
                actual_provider = None
                actual_model = None
                provider_route_status = "unknown"
                fallback_used = False
                default_missing_placeholders: list[str] = []
                audit_warnings: list[str] = []
                audit_errors: list[str] = []
                changed_files_reported_by_openclaw: list[str] = []
                revision_change_fields: dict = {}
                effective_change = False
                route_provenance_verified = False
                attempt_count = 0
                failure_reason = None
                openclaw_timeout_seconds = None

                for attempt in range(route_retry_budget + 1):
                    attempt_count = attempt + 1
                    rev_ok, rev_msg = apply_minimal_revision(
                        codebase,
                        post,
                        round_idx + 1,
                        "left",
                        game=tournament["game"],
                        regime=regime["name"],
                        model_id=meta["id"],
                        executor=executor,
                        openclaw_agent_id=openclaw_runner_agent_id,
                        provider_model=provider_model,
                        require_effective_submission_change=require_effective_submission_change,
                        revision_retry_on_noop=revision_retry_on_noop,
                        revision_retry_on_timeout=revision_retry_on_timeout,
                        feedback_artifact_paths=feedback_artifact_paths,
                        feedback_package_variant=feedback_package_variant,
                        feedback_visibility=feedback_visibility,
                        round_match_records=round_match_records_for_feedback,
                        prompt_variant=revision_prompt_variant,
                        skip_copy_tree=True,
                    )
                    write_diff_patch(codebase, post, diff_path)
                    audit_json = post / "revision_audit.json"
                    requested_provider_model = provider_model
                    actual_provider = None
                    actual_model = None
                    provider_route_status = "unknown"
                    default_missing_placeholders = []
                    audit_warnings = []
                    audit_errors = []
                    changed_files_reported_by_openclaw = []
                    openclaw_timeout_seconds = None
                    audit_payload: dict | None = None
                    if audit_json.exists():
                        try:
                            audit_payload = json.loads(audit_json.read_text(encoding="utf-8"))
                            requested_provider_model = audit_payload.get("requestedProviderModel", requested_provider_model)
                            default_missing_placeholders = audit_payload.get("openclawDefaultMissingPlaceholders", []) or []
                            changed_files_reported_by_openclaw = audit_payload.get("changedFiles", []) or []
                            audit_errors = audit_payload.get("errors", []) or []
                            openclaw_timeout_seconds = audit_payload.get("openclawTimeoutSeconds")
                        except Exception as exc:
                            audit_errors = [f"failed_to_read_revision_audit:{exc!r}"]
                    provider_route_status, actual_provider, actual_model, fallback_used = _extract_openclaw_route_provenance(
                        audit_payload
                    )
                    route_provenance_verified = _route_provenance_verified(
                        provider_route_status=provider_route_status,
                        actual_provider=actual_provider,
                        actual_model=actual_model,
                        fallback_used=fallback_used,
                    )
                    if provider_route_status == "unknown":
                        audit_warnings.append("provider_route_unknown")
                    revision_change_fields = _collect_submission_change_fields(
                        codebase=codebase,
                        post=post,
                        diff_path=diff_path,
                        changed_files_reported_by_openclaw=changed_files_reported_by_openclaw,
                    )
                    effective_change = bool(revision_change_fields["effective_submission_changed"])
                    timeout_occurred = bool(
                        any(isinstance(err, str) and "openclaw timeout" in err for err in audit_errors)
                        or ("timeout" in str(rev_msg).lower())
                    )
                    if timeout_occurred:
                        failure_reason = "openclaw timeout"
                        if attempt < revision_retry_on_timeout:
                            continue
                        rev_ok = False
                        rev_msg = failure_reason
                        break
                    context_overflow_occurred = bool(
                        any(isinstance(err, str) and "openclaw context overflow" in err.lower() for err in audit_errors)
                        or ("context overflow" in str(rev_msg).lower())
                    )
                    if context_overflow_occurred:
                        failure_reason = "openclaw context overflow"
                        if attempt < route_retry_budget:
                            continue
                        rev_ok = False
                        rev_msg = failure_reason
                        break
                    if rev_ok and effective_change and not route_provenance_verified:
                        failure_reason = "OpenClaw route provenance missing despite code change"
                        if attempt < route_retry_budget:
                            continue
                        rev_ok = False
                        rev_msg = failure_reason
                    if rev_ok and not route_provenance_verified and fallback_used:
                        failure_reason = "OpenClaw fallback used during revision"
                        if attempt < route_retry_budget:
                            continue
                        rev_ok = False
                        rev_msg = failure_reason
                    break

                revision_status = "ok" if rev_ok else "failed"
                if failure_reason is None:
                    failure_reason = None if rev_ok else rev_msg
                no_effect_msg = "OpenClaw revision made no effective submission/main.py change"
                if require_effective_submission_change and ((rev_ok and not effective_change) or (not rev_ok and rev_msg == no_effect_msg)):
                    revision_status = "no_effect"
                    rev_ok = False
                    failure_reason = no_effect_msg
                revision_manifest_for_round[agent_id] = {
                    "agent_id": agent_id,
                    "provider_model": provider_model,
                    "executor": executor,
                    "revision_attempted": True,
                    "revision_executor": "openclaw-minimal",
                    "revision_status": revision_status,
                    "revision_ok": bool(rev_ok),
                    "codebase_play_path": str(codebase),
                    "submission_path": str(submission),
                    "codebase_post_path": str(post),
                    "changed_files": list(revision_change_fields["changed_files_hash_based"]),
                    "diff_path": str(diff_path),
                    "revision_log_path": str(post / "notes" / "revision_log.md"),
                    "failure_reason": failure_reason,
                    "budget_guard_reason": None,
                    "openclaw_invoked": True,
                    "fallback_used": fallback_used,
                    "requested_provider_model": requested_provider_model,
                    "actual_provider": actual_provider,
                    "actual_model": actual_model,
                    "provider_route_status": provider_route_status,
                    "openclaw_timeout_seconds": openclaw_timeout_seconds,
                    "revision_prompt_variant": revision_prompt_variant,
                    "openclaw_default_missing_placeholders": default_missing_placeholders,
                    "audit_warnings": audit_warnings,
                    "audit_errors": audit_errors,
                    "revision_attempt_count": attempt_count,
                    **revision_change_fields,
                }
                latest_post_by_agent[agent_id] = post

            write_json(
                round_dir / "revision_manifest.json",
                {
                    "require_effective_submission_change": require_effective_submission_change,
                    "revision_retry_on_noop": revision_retry_on_noop,
                    "revision_retry_on_route_unknown": revision_retry_on_route_unknown,
                    "agents": [revision_manifest_for_round[a] for a in agent_ids],
                },
            )
            failed_selected = [x for x in revision_manifest_for_round.values() if not x["revision_ok"]]
            if failed_selected:
                reasons = "; ".join(f"{x['agent_id']}:{x['failure_reason']}" for x in failed_selected)
                raise RuntimeError(f"openclaw adaptive smoke failed round_{round_idx} revisions: {reasons}")
            revision_manifests_by_round[round_idx] = revision_manifest_for_round

            # Propagate revised posts to next round.
            next_round = round_idx + 1
            if next_round <= num_rounds:
                propagation_entries: list[dict] = []
                for agent_id in agent_ids:
                    source_post = Path("workspace/posts") / tournament_name / agent_id / f"codebase_post_{round_idx}"
                    target_play = Path("workspace/codebases") / tournament_name / agent_id / f"codebase_play_{next_round}"
                    copy_tree(source_post, target_play)
                    source_submission_sha256 = _sha256_file(source_post / "submission" / "main.py")
                    target_submission_sha256 = _sha256_file(target_play / "submission" / "main.py")
                    propagation_matches_post = source_submission_sha256 == target_submission_sha256
                    propagated_files = sorted(
                        str(p.relative_to(target_play)).replace("\\", "/")
                        for p in target_play.rglob("*")
                        if p.is_file()
                    )
                    propagation_entries.append(
                        {
                            "agent_id": agent_id,
                            "source_post_path": str(source_post),
                            "target_play_path": str(target_play),
                            "propagated": True,
                            "propagation_ok": True,
                            "source_revision_ok": bool(revision_manifest_for_round[agent_id]["revision_ok"]),
                            "source_provider_route_status": revision_manifest_for_round[agent_id]["provider_route_status"],
                            "source_round": round_idx,
                            "target_round": next_round,
                            "source_submission_sha256": source_submission_sha256,
                            "target_submission_sha256": target_submission_sha256,
                            "propagated_submission_sha256": target_submission_sha256,
                            "propagation_matches_post": propagation_matches_post,
                            "file_count": len(propagated_files),
                            "files": propagated_files,
                        }
                    )
                write_json(Path(f"logs/round_{next_round}/propagation_manifest.json"), {"round_idx": next_round, "agents": propagation_entries})

def emit_progress(event: str, *, started_at: float, **fields) -> None:
    now = time.time()
    record = {
        "event": event,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "elapsed_seconds": round(now - started_at, 3),
    }
    for key, value in fields.items():
        if value is not None:
            record[key] = _safe_progress_value(value)

    compact = f"[progress] {event} " + " ".join(
        f"{k}={record[k]}"
        for k in [
            "tournament_name",
            "regime",
            "tournament_index",
            "round",
            "match_index",
            "pair_id",
            "completed_matches",
            "total_matches",
            "completed_audits",
            "expected_audits",
        ]
        if k in record
    )
    print(compact.strip(), flush=True)

    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    progress_jsonl = logs_dir / "progress.jsonl"
    progress_latest = logs_dir / "progress_latest.json"
    with progress_jsonl.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    progress_latest.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--regime", required=True)
    parser.add_argument("--tournament", required=True)
    parser.add_argument("--models", required=False)
    parser.add_argument("--schedule-only", action="store_true")
    args = parser.parse_args()
    started_at = time.time()

    ensure_dirs()

    regime = load_yaml(args.regime)
    tournament = load_yaml(args.tournament)
    models_cfg = load_yaml(args.models) if args.models else {}
    smoke_only = args.models is None
    roster_models = models_cfg.get("models", []) if isinstance(models_cfg, dict) else []
    if args.models is not None:
        tournament = resolve_tournament_counts(tournament, roster_models)
    else:
        tournament = resolve_tournament_counts(tournament, None)

    require_keys(regime, ["name", "description"], "regime config")
    require_keys(
        tournament,
        ["name", "game", "num_models", "num_rounds", "matches_per_round"],
        "tournament config",
    )

    game_config_path = Path("configs/games") / f"{tournament['game']}.yaml"
    if not game_config_path.exists():
        raise FileNotFoundError(f"Missing game config: {game_config_path}")

    game_cfg = load_yaml(game_config_path)
    require_keys(
        game_cfg,
        ["name", "adapter", "starter_repo", "submission_entry", "wrappers"],
        "game config",
    )

    adapter = get_adapter(game_cfg["adapter"])
    starter_repo = Path(game_cfg["starter_repo"])
    execution_smoke = bool(tournament.get("execution_smoke", False))
    adaptive_dryrun = bool(tournament.get("adaptive_dryrun", False))
    openclaw_adaptive_smoke = bool(tournament.get("openclaw_adaptive_smoke", False))

    left_model = roster_models[0] if isinstance(roster_models, list) and len(roster_models) > 0 else None
    right_model = roster_models[1] if isinstance(roster_models, list) and len(roster_models) > 1 else None
    left_model_id = left_model.get("id") if isinstance(left_model, dict) else None
    left_agent_id = left_model.get("agent_id") if isinstance(left_model, dict) else None
    left_provider_model = left_model.get("provider_model") if isinstance(left_model, dict) else None
    left_executor = left_model.get("executor") if isinstance(left_model, dict) else None
    right_model_id = right_model.get("id") if isinstance(right_model, dict) else None
    right_agent_id = right_model.get("agent_id") if isinstance(right_model, dict) else None
    right_provider_model = right_model.get("provider_model") if isinstance(right_model, dict) else None
    right_executor = right_model.get("executor") if isinstance(right_model, dict) else None

    print("=== Smoke Runner v6 ===")
    print("Regime:", regime["name"])
    print("Tournament:", tournament["name"])
    print("Game:", tournament["game"])
    print("Adapter:", game_cfg["adapter"])
    print("Starter repo:", starter_repo)

    valid, validate_msg = adapter.validate_submission(starter_repo)
    print("Validation:", valid, "-", validate_msg)

    tournament_name = tournament["name"]
    independent_tournaments = int(tournament.get("independent_tournaments", 1) or 1)
    total_rounds = int(tournament["num_rounds"])
    matches_per_round = int(tournament["matches_per_round"])
    total_matches = independent_tournaments * total_rounds * matches_per_round
    completed_matches = 0
    completed_audits = 0
    expected_audits = independent_tournaments * int(tournament["num_models"]) * max(0, total_rounds - 1)
    base_seed = int(tournament.get("base_seed", tournament.get("seed", 20260428)))

    use_generic_roster = (
        args.models is not None
        and isinstance(roster_models, list)
        and len(roster_models) >= 2
        and len(roster_models) % 2 == 0
        and tournament.get("num_models") == len(roster_models)
    )
    if args.models is not None:
        for idx, entry in enumerate(roster_models, start=1):
            if not isinstance(entry, dict):
                raise ValueError(f"Model entry #{idx} must be a mapping")
            model_id = entry.get("id") or f"model_{idx}"
            executor = entry.get("executor")
            if not executor:
                raise ValueError(f"Model '{model_id}' missing required executor")
            if executor != "openclaw-minimal":
                raise ValueError(
                    f"Model '{model_id}' has unsupported executor '{executor}'; expected 'openclaw-minimal'"
                )
    if execution_smoke:
        if args.models is None:
            raise ValueError("execution_smoke requires --models")
        if int(tournament.get("num_rounds", 0)) != 1:
            raise ValueError("execution_smoke requires num_rounds=1")
        _run_execution_smoke_tournament(
            adapter=adapter,
            game_cfg=game_cfg,
            tournament=tournament,
            regime=regime,
            roster_models=roster_models,
            starter_repo=starter_repo,
            valid=valid,
            validate_msg=validate_msg,
            smoke_only=smoke_only,
        )
        print("Created execution-smoke round_1 match artifacts and round_manifest.json")
        print("Smoke skeleton v6 OK.")
        return
    if openclaw_adaptive_smoke:
        if args.models is None:
            raise ValueError("openclaw_adaptive_smoke requires --models")
        rounds_for_adaptive_smoke = int(tournament.get("num_rounds", 0))
        if rounds_for_adaptive_smoke < 2:
            raise ValueError("openclaw_adaptive_smoke requires num_rounds >= 2")
        _run_openclaw_adaptive_smoke_tournament(
            adapter=adapter,
            game_cfg=game_cfg,
            tournament=tournament,
            regime=regime,
            roster_models=roster_models,
            starter_repo=starter_repo,
            valid=valid,
            validate_msg=validate_msg,
            smoke_only=smoke_only,
        )
        try:
            from runner.core.pommerman_tournament_report import write_tournament_report

            write_tournament_report(tournament_name=tournament_name)
        except Exception as exc:
            print(f"WARN failed to write logs/tournament_report.md/json: {exc!r}")
        print(f"Created openclaw-adaptive-{rounds_for_adaptive_smoke}round-smoke manifests and propagation evidence")
        print("Smoke skeleton v6 OK.")
        return
    if adaptive_dryrun:
        if args.models is None:
            raise ValueError("adaptive_dryrun requires --models")
        _run_adaptive_dryrun_tournament(
            adapter=adapter,
            game_cfg=game_cfg,
            tournament=tournament,
            regime=regime,
            roster_models=roster_models,
            starter_repo=starter_repo,
            valid=valid,
            validate_msg=validate_msg,
            smoke_only=smoke_only,
        )
        print("Created adaptive-dryrun round manifests and per-agent propagation artifacts")
        print("Smoke skeleton v6 OK.")
        return

    if use_generic_roster:
        roster_entries = []
        for idx, entry in enumerate(roster_models):
            if not isinstance(entry, dict):
                continue
            model_id = entry.get("id")
            if not isinstance(model_id, str) or not model_id.strip():
                model_id = f"model_{idx + 1}"
            roster_entries.append(
                {
                    "id": model_id,
                    "agent_id": entry.get("agent_id"),
                    "provider_model": entry.get("provider_model"),
                    "executor": entry.get("executor"),
                }
            )

        def stable_pair_seed(*, tournament_index: int, pair_id: str) -> int:
            material = f"{tournament_name}|{regime['name']}|{tournament_index}|{pair_id}|{base_seed}"
            return int(hashlib.sha256(material.encode("utf-8")).hexdigest()[:8], 16) & 0x7FFFFFFF

        schedule = build_double_round_robin([entry["id"] for entry in roster_entries], num_rounds=int(tournament["num_rounds"]))
        schedule_rounds = schedule["rounds"]
        pairing_manifest_entries: list[dict] = []
        emit_progress(
            "schedule_built",
            started_at=started_at,
            tournament_name=tournament_name,
            regime=regime["name"],
            independent_tournaments=independent_tournaments,
            total_rounds=total_rounds,
            matches_per_round=matches_per_round,
            completed_matches=completed_matches,
            total_matches=total_matches,
            completed_audits=completed_audits,
            expected_audits=expected_audits,
        )

        for tournament_index in range(1, independent_tournaments + 1):
            emit_progress(
                "tournament_start",
                started_at=started_at,
                tournament_name=tournament_name,
                regime=regime["name"],
                tournament_index=tournament_index,
                independent_tournaments=independent_tournaments,
                total_rounds=total_rounds,
                matches_per_round=matches_per_round,
                completed_matches=completed_matches,
                total_matches=total_matches,
                completed_audits=completed_audits,
                expected_audits=expected_audits,
            )
            latest_post_by_model_id: dict[str, Path] = {}
            for round_idx in range(1, tournament["num_rounds"] + 1):
                round_dir = ensure_round_dir(round_idx)
                if not schedule_rounds:
                    continue
                round_payload = schedule_rounds[round_idx - 1]
                round_pairs = list(round_payload.get("matches", []))

                round_feedback_payload: dict | None = None
                round_metadata_payload: dict | None = None
                emit_progress(
                    "round_start",
                    started_at=started_at,
                    tournament_name=tournament_name,
                    regime=regime["name"],
                    tournament_index=tournament_index,
                    independent_tournaments=independent_tournaments,
                    round=round_idx,
                    total_rounds=total_rounds,
                    matches_per_round=matches_per_round,
                    completed_matches=completed_matches,
                    total_matches=total_matches,
                    completed_audits=completed_audits,
                    expected_audits=expected_audits,
                )

                for match_slot, scheduled_match in enumerate(round_pairs, start=1):
                    match_index = (tournament_index - 1) * tournament["matches_per_round"] + match_slot
                    match_dir = round_dir / f"t{tournament_index}_match_{match_slot}"
                    match_dir.mkdir(parents=True, exist_ok=True)

                    left_id = str(scheduled_match["left_agent"])
                    right_id = str(scheduled_match["right_agent"])
                    left_meta = next(x for x in roster_entries if x["id"] == left_id)
                    right_meta = next(x for x in roster_entries if x["id"] == right_id)
                    left_agent_id = left_meta.get("agent_id")
                    right_agent_id = right_meta.get("agent_id")
                    left_provider_model = left_meta.get("provider_model")
                    right_provider_model = right_meta.get("provider_model")
                    left_executor = left_meta.get("executor")
                    right_executor = right_meta.get("executor")
                    pair_id = str(scheduled_match["pair_id"])
                    pair_seed = stable_pair_seed(tournament_index=tournament_index, pair_id=pair_id)
                    emit_progress(
                        "match_start",
                        started_at=started_at,
                        tournament_name=tournament_name,
                        regime=regime["name"],
                        tournament_index=tournament_index,
                        independent_tournaments=independent_tournaments,
                        round=round_idx,
                        total_rounds=total_rounds,
                        match_index=match_index,
                        matches_per_round=matches_per_round,
                        pair_id=pair_id,
                        left_model_id=left_id,
                        right_model_id=right_id,
                        left_agent_id=left_agent_id,
                        right_agent_id=right_agent_id,
                        left_provider_model=left_provider_model,
                        right_provider_model=right_provider_model,
                        encounter_index=scheduled_match.get("encounter_index"),
                        seed=pair_seed,
                        completed_matches=completed_matches,
                        total_matches=total_matches,
                        completed_audits=completed_audits,
                        expected_audits=expected_audits,
                    )

                    pairing_manifest_entries.append(
                        {
                            "tournament_index": tournament_index,
                            "round": round_idx,
                            "match_index": match_index,
                            "pair_id": pair_id,
                            "left_model_id": left_id,
                            "right_model_id": right_id,
                            "left_agent_id": left_agent_id,
                            "right_agent_id": right_agent_id,
                            "left_provider_model": left_provider_model,
                            "right_provider_model": right_provider_model,
                            "schedule_mode": "double_round_robin",
                            "match_legs": "single",
                            "encounter_index": scheduled_match.get("encounter_index"),
                            "reverse_of_round": scheduled_match.get("reverse_of_round"),
                            "reverse_of_match": scheduled_match.get("reverse_of_match"),
                            "seed": pair_seed,
                        }
                    )

                    if args.schedule_only:
                        completed_matches += 1
                        emit_progress(
                            "match_done",
                            started_at=started_at,
                            tournament_name=tournament_name,
                            regime=regime["name"],
                            tournament_index=tournament_index,
                            independent_tournaments=independent_tournaments,
                            round=round_idx,
                            total_rounds=total_rounds,
                            match_index=match_index,
                            matches_per_round=matches_per_round,
                            pair_id=pair_id,
                            left_model_id=left_id,
                            right_model_id=right_id,
                            left_agent_id=left_agent_id,
                            right_agent_id=right_agent_id,
                            left_provider_model=left_provider_model,
                            right_provider_model=right_provider_model,
                            encounter_index=scheduled_match.get("encounter_index"),
                            seed=pair_seed,
                            completed_matches=completed_matches,
                            total_matches=total_matches,
                            completed_audits=completed_audits,
                            expected_audits=expected_audits,
                        )
                        continue

                    left_codebase = (
                        Path("workspace/codebases")
                        / tournament_name
                        / left_id
                        / f"codebase_play_t{tournament_index}_r{round_idx}_m{match_slot}_vs_{right_id}"
                    )
                    right_codebase = (
                        Path("workspace/codebases")
                        / tournament_name
                        / right_id
                        / f"codebase_play_t{tournament_index}_r{round_idx}_m{match_slot}_vs_{left_id}"
                    )
                    left_submission = (
                        Path("workspace/submissions")
                        / tournament_name
                        / left_id
                        / f"submission_t{tournament_index}_r{round_idx}_m{match_slot}_vs_{right_id}"
                    )
                    right_submission = (
                        Path("workspace/submissions")
                        / tournament_name
                        / right_id
                        / f"submission_t{tournament_index}_r{round_idx}_m{match_slot}_vs_{left_id}"
                    )
                    left_post = (
                        Path("workspace/posts")
                        / tournament_name
                        / left_id
                        / f"codebase_post_t{tournament_index}_r{round_idx}_m{match_slot}_vs_{right_id}"
                    )
                    right_post = (
                        Path("workspace/posts")
                        / tournament_name
                        / right_id
                        / f"codebase_post_t{tournament_index}_r{round_idx}_m{match_slot}_vs_{left_id}"
                    )

                    left_source = latest_post_by_model_id.get(left_id, starter_repo)
                    right_source = latest_post_by_model_id.get(right_id, starter_repo)

                    copy_tree(left_source, left_codebase)
                    copy_tree(right_source, right_codebase)

                    left_export_ok, left_export_msg = adapter.export_submission(left_codebase, left_submission)
                    right_export_ok, right_export_msg = adapter.export_submission(right_codebase, right_submission)

                    if valid and left_export_ok and right_export_ok:
                        emit_progress(
                            "arena_start",
                            started_at=started_at,
                            tournament_name=tournament_name,
                            regime=regime["name"],
                            tournament_index=tournament_index,
                            independent_tournaments=independent_tournaments,
                            round=round_idx,
                            total_rounds=total_rounds,
                            match_index=match_index,
                            matches_per_round=matches_per_round,
                            pair_id=pair_id,
                            left_model_id=left_id,
                            right_model_id=right_id,
                            left_agent_id=left_agent_id,
                            right_agent_id=right_agent_id,
                            left_provider_model=left_provider_model,
                            right_provider_model=right_provider_model,
                            encounter_index=scheduled_match.get("encounter_index"),
                            seed=pair_seed,
                            completed_matches=completed_matches,
                            total_matches=total_matches,
                            completed_audits=completed_audits,
                            expected_audits=expected_audits,
                        )
                        match_result = adapter.run_match(
                            left_codebase,
                            right_codebase,
                            match_dir,
                            game_cfg,
                        )
                        emit_progress(
                            "arena_done",
                            started_at=started_at,
                            tournament_name=tournament_name,
                            regime=regime["name"],
                            tournament_index=tournament_index,
                            independent_tournaments=independent_tournaments,
                            round=round_idx,
                            total_rounds=total_rounds,
                            match_index=match_index,
                            matches_per_round=matches_per_round,
                            pair_id=pair_id,
                            left_model_id=left_id,
                            right_model_id=right_id,
                            left_agent_id=left_agent_id,
                            right_agent_id=right_agent_id,
                            left_provider_model=left_provider_model,
                            right_provider_model=right_provider_model,
                            encounter_index=scheduled_match.get("encounter_index"),
                            seed=pair_seed,
                            completed_matches=completed_matches,
                            total_matches=total_matches,
                            completed_audits=completed_audits,
                            expected_audits=expected_audits,
                        )
                    else:
                        match_result = {
                            "winner": "draw",
                            "result": "validation_or_export_failed",
                            "runtime_diagnostics": {
                                "compile_ok": False,
                                "runtime_ok": False,
                                "invalid_actions": 1,
                                "timeout": False,
                                "stderr_excerpt": validate_msg,
                                "validate_submission_ok": valid,
                                "validate_submission_msg": validate_msg,
                                "left_export_ok": left_export_ok,
                                "left_export_msg": left_export_msg,
                                "right_export_ok": right_export_ok,
                                "right_export_msg": right_export_msg,
                            },
                        }

                    emit_progress(
                        "left_revision_start",
                        started_at=started_at,
                        tournament_name=tournament_name,
                        regime=regime["name"],
                        tournament_index=tournament_index,
                        independent_tournaments=independent_tournaments,
                        round=round_idx,
                        total_rounds=total_rounds,
                        match_index=match_index,
                        matches_per_round=matches_per_round,
                        pair_id=pair_id,
                        left_model_id=left_id,
                        right_model_id=right_id,
                        left_agent_id=left_agent_id,
                        right_agent_id=right_agent_id,
                        left_provider_model=left_provider_model,
                        right_provider_model=right_provider_model,
                        seed=pair_seed,
                        completed_matches=completed_matches,
                        total_matches=total_matches,
                        completed_audits=completed_audits,
                        expected_audits=expected_audits,
                    )
                    left_rev_ok, left_rev_msg = apply_minimal_revision(
                        left_codebase,
                        left_post,
                        round_idx,
                        "left",
                        game=tournament["game"],
                        regime=regime["name"],
                        model_id=left_id,
                        executor=left_executor,
                        openclaw_agent_id=left_agent_id,
                        provider_model=left_provider_model,
                    )
                    if round_idx > 1:
                        completed_audits += 1
                    emit_progress(
                        "left_revision_done",
                        started_at=started_at,
                        tournament_name=tournament_name,
                        regime=regime["name"],
                        tournament_index=tournament_index,
                        independent_tournaments=independent_tournaments,
                        round=round_idx,
                        total_rounds=total_rounds,
                        match_index=match_index,
                        matches_per_round=matches_per_round,
                        pair_id=pair_id,
                        left_model_id=left_id,
                        right_model_id=right_id,
                        left_agent_id=left_agent_id,
                        right_agent_id=right_agent_id,
                        left_provider_model=left_provider_model,
                        right_provider_model=right_provider_model,
                        seed=pair_seed,
                        completed_matches=completed_matches,
                        total_matches=total_matches,
                        completed_audits=completed_audits,
                        expected_audits=expected_audits,
                    )
                    emit_progress(
                        "right_revision_start",
                        started_at=started_at,
                        tournament_name=tournament_name,
                        regime=regime["name"],
                        tournament_index=tournament_index,
                        independent_tournaments=independent_tournaments,
                        round=round_idx,
                        total_rounds=total_rounds,
                        match_index=match_index,
                        matches_per_round=matches_per_round,
                        pair_id=pair_id,
                        left_model_id=left_id,
                        right_model_id=right_id,
                        left_agent_id=left_agent_id,
                        right_agent_id=right_agent_id,
                        left_provider_model=left_provider_model,
                        right_provider_model=right_provider_model,
                        seed=pair_seed,
                        completed_matches=completed_matches,
                        total_matches=total_matches,
                        completed_audits=completed_audits,
                        expected_audits=expected_audits,
                    )
                    right_rev_ok, right_rev_msg = apply_minimal_revision(
                        right_codebase,
                        right_post,
                        round_idx,
                        "right",
                        game=tournament["game"],
                        regime=regime["name"],
                        model_id=right_id,
                        executor=right_executor,
                        openclaw_agent_id=right_agent_id,
                        provider_model=right_provider_model,
                    )
                    if round_idx > 1:
                        completed_audits += 1
                    emit_progress(
                        "right_revision_done",
                        started_at=started_at,
                        tournament_name=tournament_name,
                        regime=regime["name"],
                        tournament_index=tournament_index,
                        independent_tournaments=independent_tournaments,
                        round=round_idx,
                        total_rounds=total_rounds,
                        match_index=match_index,
                        matches_per_round=matches_per_round,
                        pair_id=pair_id,
                        left_model_id=left_id,
                        right_model_id=right_id,
                        left_agent_id=left_agent_id,
                        right_agent_id=right_agent_id,
                        left_provider_model=left_provider_model,
                        right_provider_model=right_provider_model,
                        seed=pair_seed,
                        completed_matches=completed_matches,
                        total_matches=total_matches,
                        completed_audits=completed_audits,
                        expected_audits=expected_audits,
                    )

                    write_diff_patch(left_codebase, left_post, match_dir / "left.diff.patch")
                    write_diff_patch(right_codebase, right_post, match_dir / "right.diff.patch")

                    scorecard_payload = {
                        "left_score": 0,
                        "right_score": 0,
                    }
                    scorecard_path = match_dir / "scorecard.json"
                    if scorecard_path.exists():
                        scorecard_data = json.loads(scorecard_path.read_text())
                        scorecard_payload["left_score"] = scorecard_data["left_score"]
                        scorecard_payload["right_score"] = scorecard_data["right_score"]
                        if "left_right_winner" in scorecard_data:
                            scorecard_payload["left_right_winner"] = scorecard_data["left_right_winner"]

                    feedback_payload = {
                        "meta": {
                            "game": tournament["game"],
                            "protocol": "adaptive",
                            "round_idx": round_idx,
                            "match_id": f"{tournament['name']}_t{tournament_index}_round_{round_idx}_match_{match_slot}",
                            "match_slot": match_slot,
                            "tournament_index": tournament_index,
                            "regime": regime["name"],
                            "repo_version": "smoke-placeholder",
                            "adapter": game_cfg["adapter"],
                            "left_model_id": left_id,
                            "left_agent_id": left_agent_id,
                            "left_provider_model": left_provider_model,
                            "left_executor": left_executor,
                            "right_model_id": right_id,
                            "right_agent_id": right_agent_id,
                            "right_provider_model": right_provider_model,
                            "right_executor": right_executor,
                            "pair_id": pair_id,
                            "schedule_mode": "double_round_robin",
                            "match_legs": "single",
                            "encounter_index": scheduled_match.get("encounter_index"),
                            "seed": pair_seed,
                            "smoke_only": smoke_only,
                        },
                        "outcome": {
                            "winner": match_result["winner"],
                            "result": match_result["result"],
                        },
                        "scorecard": scorecard_payload,
                        "runtime_diagnostics": {
                            **match_result["runtime_diagnostics"],
                            "left_export_ok": left_export_ok,
                            "left_export_msg": left_export_msg,
                            "right_export_ok": right_export_ok,
                            "right_export_msg": right_export_msg,
                            "left_revision_ok": left_rev_ok,
                            "left_revision_msg": left_rev_msg,
                            "right_revision_ok": right_rev_ok,
                            "right_revision_msg": right_rev_msg,
                        },
                        "artifacts": {
                            "scorecard_path": str(match_dir / "scorecard.json"),
                            "stderr_path": str(match_dir / "stderr.log"),
                            "build_log_path": str(match_dir / "build.log"),
                            "test_log_path": str(match_dir / "test.log"),
                            "left_codebase_path": str(left_codebase),
                            "right_codebase_path": str(right_codebase),
                            "left_submission_path": str(left_submission),
                            "right_submission_path": str(right_submission),
                            "left_post_path": str(left_post),
                            "right_post_path": str(right_post),
                            "left_diff_path": str(match_dir / "left.diff.patch"),
                            "right_diff_path": str(match_dir / "right.diff.patch"),
                        },
                    }

                    metadata_payload = {
                        "round_idx": round_idx,
                        "match_slot": match_slot,
                        "tournament_index": tournament_index,
                        "regime": regime["name"],
                        "game": tournament["game"],
                        "adapter": game_cfg["adapter"],
                        "left_model_id": left_id,
                        "left_agent_id": left_agent_id,
                        "left_provider_model": left_provider_model,
                        "left_executor": left_executor,
                        "right_model_id": right_id,
                        "right_agent_id": right_agent_id,
                        "right_provider_model": right_provider_model,
                        "right_executor": right_executor,
                        "pair_id": pair_id,
                        "schedule_mode": "double_round_robin",
                        "match_legs": "single",
                        "encounter_index": scheduled_match.get("encounter_index"),
                        "seed": pair_seed,
                        "smoke_only": smoke_only,
                        "starter_repo": str(starter_repo),
                        "validate_submission_ok": valid,
                        "validate_submission_msg": validate_msg,
                        "left_export_ok": left_export_ok,
                        "left_export_msg": left_export_msg,
                        "right_export_ok": right_export_ok,
                        "right_export_msg": right_export_msg,
                        "left_revision_ok": left_rev_ok,
                        "left_revision_msg": left_rev_msg,
                        "right_revision_ok": right_rev_ok,
                        "right_revision_msg": right_rev_msg,
                        "left_codebase_path": str(left_codebase),
                        "right_codebase_path": str(right_codebase),
                        "left_submission_path": str(left_submission),
                        "right_submission_path": str(right_submission),
                        "left_post_path": str(left_post),
                        "right_post_path": str(right_post),
                        "status": "created-post-and-propagation-ready",
                        "winner": match_result["winner"],
                        "result": match_result["result"],
                    }

                    write_json(match_dir / "feedback_package.json", feedback_payload)
                    write_json(match_dir / "metadata.json", metadata_payload)
                    completed_matches += 1
                    emit_progress(
                        "match_done",
                        started_at=started_at,
                        tournament_name=tournament_name,
                        regime=regime["name"],
                        tournament_index=tournament_index,
                        independent_tournaments=independent_tournaments,
                        round=round_idx,
                        total_rounds=total_rounds,
                        match_index=match_index,
                        matches_per_round=matches_per_round,
                        pair_id=pair_id,
                        left_model_id=left_id,
                        right_model_id=right_id,
                        left_agent_id=left_agent_id,
                        right_agent_id=right_agent_id,
                        left_provider_model=left_provider_model,
                        right_provider_model=right_provider_model,
                        encounter_index=scheduled_match.get("encounter_index"),
                        seed=pair_seed,
                        completed_matches=completed_matches,
                        total_matches=total_matches,
                        completed_audits=completed_audits,
                        expected_audits=expected_audits,
                    )
                    round_feedback_payload = feedback_payload
                    round_metadata_payload = metadata_payload

                    latest_post_by_model_id[left_id] = left_post
                    latest_post_by_model_id[right_id] = right_post

                if round_feedback_payload is not None:
                    write_json(round_dir / f"t{tournament_index}_feedback_package.json", round_feedback_payload)
                if round_metadata_payload is not None:
                    write_json(round_dir / f"t{tournament_index}_metadata.json", round_metadata_payload)
                emit_progress(
                    "round_done",
                    started_at=started_at,
                    tournament_name=tournament_name,
                    regime=regime["name"],
                    tournament_index=tournament_index,
                    independent_tournaments=independent_tournaments,
                    round=round_idx,
                    total_rounds=total_rounds,
                    matches_per_round=matches_per_round,
                    completed_matches=completed_matches,
                    total_matches=total_matches,
                    completed_audits=completed_audits,
                    expected_audits=expected_audits,
                )

            emit_progress(
                "tournament_done",
                started_at=started_at,
                tournament_name=tournament_name,
                regime=regime["name"],
                tournament_index=tournament_index,
                independent_tournaments=independent_tournaments,
                total_rounds=total_rounds,
                matches_per_round=matches_per_round,
                completed_matches=completed_matches,
                total_matches=total_matches,
                completed_audits=completed_audits,
                expected_audits=expected_audits,
            )

        pairing_manifest_payload = {
            "tournament_name": tournament_name,
            "game": tournament["game"],
            "regime": regime["name"],
            "num_models": tournament["num_models"],
            "num_rounds": tournament["num_rounds"],
            "matches_per_round": tournament["matches_per_round"],
            "independent_tournaments": independent_tournaments,
            "models": [
                {
                    "id": model["id"],
                    "agent_id": model.get("agent_id"),
                    "provider_model": model.get("provider_model"),
                    "executor": model.get("executor"),
                }
                for model in roster_entries
            ],
            "matches": pairing_manifest_entries,
        }

        posts_manifest_path = Path("workspace/posts") / tournament_name / "pairing_manifest.json"
        posts_manifest_path.parent.mkdir(parents=True, exist_ok=True)
        logs_manifest_path = Path("logs") / "pairing_manifest.json"
        write_json(posts_manifest_path, pairing_manifest_payload)
        write_json(logs_manifest_path, pairing_manifest_payload)
        emit_progress(
            "run_done",
            started_at=started_at,
            tournament_name=tournament_name,
            regime=regime["name"],
            independent_tournaments=independent_tournaments,
            total_rounds=total_rounds,
            matches_per_round=matches_per_round,
            completed_matches=completed_matches,
            total_matches=total_matches,
            completed_audits=completed_audits,
            expected_audits=expected_audits,
        )

        if args.schedule_only:
            print("Built schedule and pairing manifest only (no arena or revisions).")
        else:
            print("Created roster round-robin codebase_play_t + submission_t + codebase_post_t artifacts in workspace/")
        print("Smoke skeleton v6 OK.")
        return

    prev_left_post = None
    prev_right_post = None
    requested_seed = _smoke_requested_seed(tournament)
    applied_seed: int | None = None

    for round_idx in range(1, tournament["num_rounds"] + 1):
        round_dir = ensure_round_dir(round_idx)

        left_codebase = Path("workspace/codebases") / tournament_name / "left" / f"codebase_play_{round_idx}"
        right_codebase = Path("workspace/codebases") / tournament_name / "right" / f"codebase_play_{round_idx}"
        left_submission = Path("workspace/submissions") / tournament_name / "left" / f"submission_{round_idx}"
        right_submission = Path("workspace/submissions") / tournament_name / "right" / f"submission_{round_idx}"
        left_post = Path("workspace/posts") / tournament_name / "left" / f"codebase_post_{round_idx}"
        right_post = Path("workspace/posts") / tournament_name / "right" / f"codebase_post_{round_idx}"

        left_source = starter_repo if round_idx == 1 else prev_left_post
        right_source = starter_repo if round_idx == 1 else prev_right_post

        copy_tree(left_source, left_codebase)
        copy_tree(right_source, right_codebase)

        left_export_ok, left_export_msg = adapter.export_submission(left_codebase, left_submission)
        right_export_ok, right_export_msg = adapter.export_submission(right_codebase, right_submission)

        if valid and left_export_ok and right_export_ok:
            match_result = adapter.run_match(
                left_codebase,
                right_codebase,
                round_dir,
                game_cfg,
            )
            _write_round_seed_provenance(round_dir, requested_seed=requested_seed, applied_seed=applied_seed)
        else:
            match_result = {
                "winner": "draw",
                "result": "validation_or_export_failed",
                "runtime_diagnostics": {
                    "compile_ok": False,
                    "runtime_ok": False,
                    "invalid_actions": 1,
                    "timeout": False,
                    "stderr_excerpt": validate_msg,
                    "validate_submission_ok": valid,
                    "validate_submission_msg": validate_msg,
                    "left_export_ok": left_export_ok,
                    "left_export_msg": left_export_msg,
                    "right_export_ok": right_export_ok,
                    "right_export_msg": right_export_msg,
                },
            }

        left_rev_ok, left_rev_msg = apply_minimal_revision(
            left_codebase,
            left_post,
            round_idx,
            "left",
            game=tournament["game"],
            regime=regime["name"],
            model_id=left_model_id,
            executor=left_executor,
            openclaw_agent_id=left_agent_id,
            provider_model=left_provider_model,
        )
        right_rev_ok, right_rev_msg = apply_minimal_revision(
            right_codebase,
            right_post,
            round_idx,
            "right",
            game=tournament["game"],
            regime=regime["name"],
            model_id=right_model_id,
            executor=right_executor,
            openclaw_agent_id=right_agent_id,
            provider_model=right_provider_model,
        )

        write_diff_patch(left_codebase, left_post, round_dir / "left.diff.patch")
        write_diff_patch(right_codebase, right_post, round_dir / "right.diff.patch")

        scorecard_payload = {
            "left_score": 0,
            "right_score": 0,
        }
        scorecard_path = round_dir / "scorecard.json"
        if scorecard_path.exists():
            scorecard_data = json.loads(scorecard_path.read_text())
            scorecard_payload["left_score"] = scorecard_data["left_score"]
            scorecard_payload["right_score"] = scorecard_data["right_score"]
            if "left_right_winner" in scorecard_data:
                scorecard_payload["left_right_winner"] = scorecard_data["left_right_winner"]

        feedback_payload = {
            "meta": {
                "game": tournament["game"],
                "protocol": "adaptive",
                "round_idx": round_idx,
                "match_id": f"{tournament['name']}_round_{round_idx}_match_1",
                "regime": regime["name"],
                "repo_version": "smoke-placeholder",
                "adapter": game_cfg["adapter"],
                "left_model_id": left_model_id,
                "left_agent_id": left_agent_id,
                "left_provider_model": left_provider_model,
                "left_executor": left_executor,
                "right_model_id": right_model_id,
                "right_agent_id": right_agent_id,
                "right_provider_model": right_provider_model,
                "right_executor": right_executor,
                "requested_seed": requested_seed,
                "applied_seed": applied_seed,
                "seed": applied_seed,
                "seed_control_status": "applied" if applied_seed is not None else "requested_but_not_applied",
                "smoke_only": smoke_only,
            },
            "outcome": {
                "winner": match_result["winner"],
                "result": match_result["result"],
            },
            "scorecard": scorecard_payload,
            "runtime_diagnostics": {
                **match_result["runtime_diagnostics"],
                "left_export_ok": left_export_ok,
                "left_export_msg": left_export_msg,
                "right_export_ok": right_export_ok,
                "right_export_msg": right_export_msg,
                "left_revision_ok": left_rev_ok,
                "left_revision_msg": left_rev_msg,
                "right_revision_ok": right_rev_ok,
                "right_revision_msg": right_rev_msg,
            },
            "artifacts": {
                "scorecard_path": str(round_dir / "scorecard.json"),
                "stderr_path": str(round_dir / "stderr.log"),
                "build_log_path": str(round_dir / "build.log"),
                "test_log_path": str(round_dir / "test.log"),
                "left_codebase_path": str(left_codebase),
                "right_codebase_path": str(right_codebase),
                "left_submission_path": str(left_submission),
                "right_submission_path": str(right_submission),
                "left_post_path": str(left_post),
                "right_post_path": str(right_post),
                "left_diff_path": str(round_dir / "left.diff.patch"),
                "right_diff_path": str(round_dir / "right.diff.patch"),
            },
        }

        metadata_payload = {
            "round_idx": round_idx,
            "regime": regime["name"],
            "game": tournament["game"],
            "adapter": game_cfg["adapter"],
            "left_model_id": left_model_id,
            "left_agent_id": left_agent_id,
            "left_provider_model": left_provider_model,
            "left_executor": left_executor,
            "right_model_id": right_model_id,
            "right_agent_id": right_agent_id,
            "right_provider_model": right_provider_model,
            "right_executor": right_executor,
            "requested_seed": requested_seed,
            "applied_seed": applied_seed,
            "seed": applied_seed,
            "seed_control_status": "applied" if applied_seed is not None else "requested_but_not_applied",
            "smoke_only": smoke_only,
            "starter_repo": str(starter_repo),
            "validate_submission_ok": valid,
            "validate_submission_msg": validate_msg,
            "left_export_ok": left_export_ok,
            "left_export_msg": left_export_msg,
            "right_export_ok": right_export_ok,
            "right_export_msg": right_export_msg,
            "left_revision_ok": left_rev_ok,
            "left_revision_msg": left_rev_msg,
            "right_revision_ok": right_rev_ok,
            "right_revision_msg": right_rev_msg,
            "left_codebase_path": str(left_codebase),
            "right_codebase_path": str(right_codebase),
            "left_submission_path": str(left_submission),
            "right_submission_path": str(right_submission),
            "left_post_path": str(left_post),
            "right_post_path": str(right_post),
            "status": "created-post-and-propagation-ready",
            "winner": match_result["winner"],
            "result": match_result["result"],
        }

        write_json(round_dir / "feedback_package.json", feedback_payload)
        write_json(round_dir / "metadata.json", metadata_payload)

        prev_left_post = left_post
        prev_right_post = right_post

    print("Created codebase_play_t + submission_t + codebase_post_t artifacts in workspace/")
    print("Smoke skeleton v6 OK.")


if __name__ == "__main__":
    main()

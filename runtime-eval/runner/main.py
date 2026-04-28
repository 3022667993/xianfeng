from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from runner.adapters.registry import get_adapter
from runner.core.artifacts import ensure_round_dir, write_json
from runner.core.config import load_yaml, require_keys
from runner.core.fsops import copy_tree
from runner.core.revision import apply_minimal_revision, write_diff_patch


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

    roster_models = models_cfg.get("models", []) if isinstance(models_cfg, dict) else []
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

        def round_robin_rounds(entries: list[dict]) -> list[list[tuple[dict, dict]]]:
            if len(entries) % 2 != 0:
                return []
            order = list(entries)
            rounds: list[list[tuple[dict, dict]]] = []
            for _ in range(len(order) - 1):
                half = len(order) // 2
                left_half = order[:half]
                right_half = list(reversed(order[half:]))
                rounds.append(list(zip(left_half, right_half)))
                order = [order[0], order[-1], *order[1:-1]]
            return rounds

        def build_double_round_robin(entries: list[dict]) -> list[list[tuple[dict, dict, int]]]:
            single_rr = round_robin_rounds(entries)
            first_leg = [[(left, right, 1) for (left, right) in r] for r in single_rr]
            second_leg = [[(right, left, 2) for (left, right) in r] for r in single_rr]
            return [*first_leg, *second_leg]

        def stable_pair_seed(*, tournament_index: int, pair_id: str) -> int:
            material = f"{tournament_name}|{regime['name']}|{tournament_index}|{pair_id}|{base_seed}"
            # Deterministic 31-bit seed so both seat-swap legs in the same tournament reuse it.
            return int(hashlib.sha256(material.encode("utf-8")).hexdigest()[:8], 16) & 0x7FFFFFFF

        schedule_rounds = build_double_round_robin(roster_entries)
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
                scheduled_pairs = schedule_rounds[(round_idx - 1) % len(schedule_rounds)]
                round_pairs = scheduled_pairs[: tournament["matches_per_round"]]

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

                for match_slot, (left_meta, right_meta, seat_swap_leg) in enumerate(round_pairs, start=1):
                    match_index = (tournament_index - 1) * tournament["matches_per_round"] + match_slot
                    match_dir = round_dir / f"t{tournament_index}_match_{match_slot}"
                    match_dir.mkdir(parents=True, exist_ok=True)

                    left_id = left_meta["id"]
                    right_id = right_meta["id"]
                    left_agent_id = left_meta.get("agent_id")
                    right_agent_id = right_meta.get("agent_id")
                    left_provider_model = left_meta.get("provider_model")
                    right_provider_model = right_meta.get("provider_model")
                    left_executor = left_meta.get("executor")
                    right_executor = right_meta.get("executor")
                    pair_id = "__vs__".join(sorted([left_id, right_id]))
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
                        seat_swap_leg=seat_swap_leg,
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
                            "seat_swap_leg": seat_swap_leg,
                            "swapped_with_round": None,
                            "swapped_with_match_index": None,
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
                            seat_swap_leg=seat_swap_leg,
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
                            seat_swap_leg=seat_swap_leg,
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
                            seat_swap_leg=seat_swap_leg,
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
                        seat_swap_leg=seat_swap_leg,
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
                        seat_swap_leg=seat_swap_leg,
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
                        seat_swap_leg=seat_swap_leg,
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
                        seat_swap_leg=seat_swap_leg,
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
                            "seat_swap_leg": seat_swap_leg,
                            "seed": pair_seed,
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
                        "seat_swap_leg": seat_swap_leg,
                        "seed": pair_seed,
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
                        seat_swap_leg=seat_swap_leg,
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

        # Backfill swapped leg pointers by pair_id and seat_swap_leg.
        index_by_pair_leg: dict[tuple[int, str, int], int] = {}
        for idx, entry in enumerate(pairing_manifest_entries):
            index_by_pair_leg[(entry["tournament_index"], entry["pair_id"], entry["seat_swap_leg"])] = idx
        for entry in pairing_manifest_entries:
            other_leg = 2 if entry["seat_swap_leg"] == 1 else 1
            other_idx = index_by_pair_leg.get((entry["tournament_index"], entry["pair_id"], other_leg))
            if other_idx is None:
                continue
            other = pairing_manifest_entries[other_idx]
            entry["swapped_with_round"] = other["round"]
            entry["swapped_with_match_index"] = other["match_index"]

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

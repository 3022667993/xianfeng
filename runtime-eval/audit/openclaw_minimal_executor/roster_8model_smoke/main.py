from __future__ import annotations

import argparse
import json
from itertools import combinations
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--regime", required=True)
    parser.add_argument("--tournament", required=True)
    parser.add_argument("--models", required=False)
    args = parser.parse_args()

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

        schedule_rounds = round_robin_rounds(roster_entries)
        latest_post_by_model_id: dict[str, Path] = {}

        for round_idx in range(1, tournament["num_rounds"] + 1):
            round_dir = ensure_round_dir(round_idx)
            if not schedule_rounds:
                continue
            scheduled_pairs = schedule_rounds[(round_idx - 1) % len(schedule_rounds)]
            round_pairs = scheduled_pairs[: tournament["matches_per_round"]]

            round_feedback_payload: dict | None = None
            round_metadata_payload: dict | None = None

            for match_slot, (left_meta, right_meta) in enumerate(round_pairs, start=1):
                match_dir = round_dir / f"match_{match_slot}"
                match_dir.mkdir(parents=True, exist_ok=True)

                left_id = left_meta["id"]
                right_id = right_meta["id"]
                left_agent_id = left_meta.get("agent_id")
                right_agent_id = right_meta.get("agent_id")
                left_provider_model = left_meta.get("provider_model")
                right_provider_model = right_meta.get("provider_model")
                left_executor = left_meta.get("executor")
                right_executor = right_meta.get("executor")

                left_codebase = (
                    Path("workspace/codebases")
                    / tournament_name
                    / left_id
                    / f"codebase_play_r{round_idx}_m{match_slot}_vs_{right_id}"
                )
                right_codebase = (
                    Path("workspace/codebases")
                    / tournament_name
                    / right_id
                    / f"codebase_play_r{round_idx}_m{match_slot}_vs_{left_id}"
                )
                left_submission = (
                    Path("workspace/submissions")
                    / tournament_name
                    / left_id
                    / f"submission_r{round_idx}_m{match_slot}_vs_{right_id}"
                )
                right_submission = (
                    Path("workspace/submissions")
                    / tournament_name
                    / right_id
                    / f"submission_r{round_idx}_m{match_slot}_vs_{left_id}"
                )
                left_post = (
                    Path("workspace/posts")
                    / tournament_name
                    / left_id
                    / f"codebase_post_r{round_idx}_m{match_slot}_vs_{right_id}"
                )
                right_post = (
                    Path("workspace/posts")
                    / tournament_name
                    / right_id
                    / f"codebase_post_r{round_idx}_m{match_slot}_vs_{left_id}"
                )

                left_source = latest_post_by_model_id.get(left_id, starter_repo)
                right_source = latest_post_by_model_id.get(right_id, starter_repo)

                copy_tree(left_source, left_codebase)
                copy_tree(right_source, right_codebase)

                left_export_ok, left_export_msg = adapter.export_submission(left_codebase, left_submission)
                right_export_ok, right_export_msg = adapter.export_submission(right_codebase, right_submission)

                if valid and left_export_ok and right_export_ok:
                    match_result = adapter.run_match(
                        left_codebase,
                        right_codebase,
                        match_dir,
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
                    model_id=left_id,
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
                    model_id=right_id,
                    openclaw_agent_id=right_agent_id,
                    provider_model=right_provider_model,
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
                        "match_id": f"{tournament['name']}_round_{round_idx}_match_{match_slot}",
                        "match_slot": match_slot,
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

                round_feedback_payload = feedback_payload
                round_metadata_payload = metadata_payload

                latest_post_by_model_id[left_id] = left_post
                latest_post_by_model_id[right_id] = right_post

            if round_feedback_payload is not None:
                write_json(round_dir / "feedback_package.json", round_feedback_payload)
            if round_metadata_payload is not None:
                write_json(round_dir / "metadata.json", round_metadata_payload)

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

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

from runner.core.pommerman_results import classify_pommerman_result

NEUTRAL_README = """This directory contains logs from your previous Pommerman matches.

Use these logs to improve submission/main.py for future rounds.

Primary files:
- public_scoreboard.json
- package_manifest.json
- matches/*/match_replay.jsonl
- matches/*/run_logs.txt

Notes:
- match_replay.jsonl is public_state_replay_v1 derived from compact trajectory.
- It is not full board/observation replay.
- Only modify submission/main.py.
- Preserve public agent API.
- Keep the submission runnable.
- Do not rely on hidden state or private opponent code.
"""

V4_README = """# Round Feedback

This directory contains public logs from your previous Pommerman matches.

Use these logs to improve `submission/main.py` for future rounds.

For game rules, action meanings, win/draw/loss objective, rewards, and the required submission API, read `../../README.md` first. This feedback package contains match evidence, not the rules specification.

## Objective

Improve future match performance under the tournament scoring rules. Prefer winning over drawing, and drawing over losing. A timeout draw is not a strong success signal if better outcomes are possible. If `submitted_pair_outcome` says both submitted agents lost to a dummy/background agent, treat that as an unfavorable outcome, not as a successful draw.

Current schedule uses single-leg double round-robin. Each match package represents one game. Seat-bias is handled by later reversed encounters in the full double round-robin schedule, not by running multiple games inside one scheduled match.

## Files

- `public_scoreboard.json`: public outcomes for all matches in this round.
- `matches/*/match_index.json`: your match opponent, seed, seat assignment, winner, steps, reward, and replay paths.
- `submitted_pair_outcome`: distinguishes wins, timeout draws, dummy/background-agent wins, and invalid arena fallback results.
- `draw_type`: explains why a pairwise draw occurred when the match winner is reported as `draw`.
- `matches/*/official_record_json/game_state.json`: Pommerman official per-step game-state record when available.
- `matches/*/actions.jsonl`: per-step actions recorded by the wrapper/compact trajectory.
- `matches/*/run_logs.txt`: build, test, and arena stderr logs.
- `package_manifest.json`: package schema and replay-source metadata.

## Suggested Reading Order

1. Start with `public_scoreboard.json` for the public round outcomes.
2. Then read `matches/*/match_index.json` for your own match opponent, seed, seat, winner, steps, reward, and replay paths.
3. Use `matches/*/actions.jsonl` for compact per-step action evidence.
4. Use `matches/*/run_logs.txt` to inspect build, test, or arena errors.
5. Inspect `matches/*/official_record_json/game_state.json` selectively when you need board/state snapshots for a specific match segment. This file can be large and is evidence, not the rules specification.

## Replay Alignment

`official_record_json/game_state.json` contains official Pommerman state snapshots. `state[0]` is the initial snapshot after reset. `actions.jsonl` row `step=t` is the action vector applied to transition from `game_state.state[t]` to `game_state.state[t+1]`, so official replay usually has one more state snapshot than action rows.

## Constraints

- Modify only `submission/main.py`.
- Work only inside this current post-round codebase.
- Do not modify feedback files; they are read-only evidence.
- Do not rely on `logs/`, OpenClaw scratch workspaces, private workspace paths, private opponent code, or non-public artifacts.
- Do not make cosmetic-only changes; changes should be intended to improve future match performance.
"""


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _winner(value: Any) -> str:
    return value if value in {"left", "right", "draw"} else "draw"


def _seat_for_agent(agent_id: str, left_agent_id: str, right_agent_id: str) -> str:
    return "left" if agent_id == left_agent_id else "right"


def _as_four_seats(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value.get(f"seat_{i}") for i in range(4)]
    return [None, None, None, None]


def _replay_rows(
    *,
    round_idx: int,
    match_id: str,
    compact_path: Path,
    arena_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if compact_path.exists():
        for line in compact_path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            counts = payload.get("compact_counts") if isinstance(payload.get("compact_counts"), dict) else {}
            rows.append(
                {
                    "schema_version": "pommerman_public_state_replay_v1",
                    "round": int(round_idx),
                    "match_id": match_id,
                    "step": payload.get("step"),
                    "actions": _as_four_seats(payload.get("actions")),
                    "alive": _as_four_seats(payload.get("alive")),
                    "positions": _as_four_seats(payload.get("positions")),
                    "bomb_count": counts.get("bomb_count", 0),
                    "flame_count": counts.get("flame_count", 0),
                    "powerup_count": counts.get("powerup_count", 0),
                    "reward": payload.get("reward"),
                    "done": bool(payload.get("done", False)),
                }
            )
    if rows:
        rows[-1]["reward"] = arena_payload.get("reward")
        rows[-1]["done"] = True
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _copy_or_empty(src: Path, dst: Path) -> bool:
    if src.exists():
        shutil.copy2(src, dst)
        return True
    dst.write_text("", encoding="utf-8")
    return False


_RUN_LOG_PRIVATE_PATH_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"/root/autodl-tmp/runtime-eval/workspace/codebases/[^\s\"'<>]+"),
        "<workspace_codebases>",
    ),
    (
        re.compile(r"/root/autodl-tmp/runtime-eval/workspace/posts/[^\s\"'<>]+"),
        "<workspace_posts>",
    ),
    (
        re.compile(r"/root/autodl-tmp/runtime-eval/workspace/submissions/[^\s\"'<>]+"),
        "<workspace_submissions>",
    ),
    (
        re.compile(r"/root/autodl-tmp/runtime-eval/openclaw_workspaces/[^\s\"'<>]+"),
        "<openclaw_workspaces>",
    ),
    (
        re.compile(r"/root/\.openclaw/[^\s\"'<>]+"),
        "<openclaw_home>",
    ),
    (
        re.compile(r"/tmp/[^\s\"'<>]+"),
        "<tmp>",
    ),
]


def sanitize_model_visible_run_log(text: str) -> str:
    sanitized = text
    for pattern, replacement in _RUN_LOG_PRIVATE_PATH_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def _read_compact_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _seat_key(seat: str) -> str:
    return "seat_0" if seat == "left" else "seat_1"


def _actions_vector(actions: Any) -> list[Any]:
    if isinstance(actions, list):
        return actions
    if isinstance(actions, dict):
        return [actions.get(f"seat_{i}") for i in range(4)]
    return [None, None, None, None]


def _action_for_seat(actions: Any, seat: str) -> Any:
    key = _seat_key(seat)
    if isinstance(actions, dict):
        return actions.get(key)
    if isinstance(actions, list):
        idx = 0 if seat == "left" else 1
        return actions[idx] if len(actions) > idx else None
    return None


def _write_v4_actions(
    *,
    path: Path,
    compact_path: Path,
    agent_seat: str,
    opponent_seat: str,
) -> int:
    rows = []
    for payload in _read_compact_jsonl(compact_path):
        actions = payload.get("actions")
        rows.append(
            {
                "schema_version": "pommerman_actions_v1",
                "internal_leg_id": "match_a",
                "step": payload.get("step"),
                "actions": _actions_vector(actions),
                "agent_action": _action_for_seat(actions, agent_seat),
                "opponent_action": _action_for_seat(actions, opponent_seat),
                "agent_seat": agent_seat,
                "opponent_seat": opponent_seat,
            }
        )
    _write_jsonl(path, rows)
    return len(rows)


def _checksums_for_files(package_root: Path, relpaths: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for rel in relpaths:
        p = package_root / rel
        if not p.exists():
            continue
        out[rel] = _sha256_file(p)
    return out


def _opponent_agent_id(agent_id: str, left_agent_id: str, right_agent_id: str) -> str:
    if agent_id == left_agent_id:
        return right_agent_id
    return left_agent_id


def write_feedback_package_for_agent(
    *,
    tournament_name: str,
    round_idx: int,
    agent_id: str,
    round_match_records: list[dict[str, Any]],
    feedback_visibility: str = "own_matches_plus_public_scoreboard",
    feedback_package_variant: str = "codeclash_v3",
) -> dict[str, Any]:
    if feedback_visibility != "own_matches_plus_public_scoreboard":
        raise ValueError("unsupported feedback_visibility")
    if feedback_package_variant == "codeclash_v4":
        return write_feedback_package_v4_for_agent(
            tournament_name=tournament_name,
            round_idx=round_idx,
            agent_id=agent_id,
            round_match_records=round_match_records,
            feedback_visibility=feedback_visibility,
        )
    if feedback_package_variant not in {"", "codeclash_v3"}:
        raise ValueError(f"unsupported feedback_package_variant: {feedback_package_variant}")

    post_root = Path("workspace/posts") / tournament_name / agent_id / f"codebase_post_{round_idx}"
    package_root = post_root / "feedback" / f"round_{round_idx}"
    matches_root = package_root / "matches"
    matches_root.mkdir(parents=True, exist_ok=True)

    own_matches = [m for m in round_match_records if agent_id in {m["left_agent_id"], m["right_agent_id"]}]
    own_matches = sorted(own_matches, key=lambda m: m["match_idx"])

    public_scoreboard = {
        "schema_version": "pommerman_public_scoreboard_v3",
        "schedule_mode": "double_round_robin",
        "match_legs": "single",
        "tournament_name": tournament_name,
        "round": int(round_idx),
        "matches": [],
    }

    for m in round_match_records:
        match_dir = Path(m["match_dir"])
        leg_a = _load_json(match_dir / "arena_result_match_a.json")
        public_scoreboard["matches"].append(
            {
                "match_id": m["match_id"],
                "left_agent_id": m["left_agent_id"],
                "right_agent_id": m["right_agent_id"],
                "applied_seed": m.get("applied_seed"),
                "winner": _winner(leg_a.get("left_right_winner")),
                "steps": leg_a.get("steps"),
                "reward": leg_a.get("reward"),
            }
        )

    (package_root / "README.md").write_text(NEUTRAL_README, encoding="utf-8")
    (package_root / "public_scoreboard.json").write_text(
        json.dumps(public_scoreboard, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    package_manifest_matches: list[dict[str, Any]] = []
    round_wins = round_losses = round_draws = 0
    missing_sources: list[str] = []

    for rec in own_matches:
        match_dir = Path(rec["match_dir"])
        match_pkg = matches_root / rec["match_id"]
        match_pkg.mkdir(parents=True, exist_ok=True)

        leg_a = _load_json(match_dir / "arena_result_match_a.json")
        seat_a = _seat_for_agent(agent_id, rec["left_agent_id"], rec["right_agent_id"])
        opponent_agent_id = _opponent_agent_id(agent_id, rec["left_agent_id"], rec["right_agent_id"])
        winner_a = _winner(leg_a.get("left_right_winner"))
        if winner_a == "draw":
            round_draws += 1
        elif winner_a == seat_a:
            round_wins += 1
        else:
            round_losses += 1

        rows_a = _replay_rows(
            round_idx=round_idx,
            match_id=rec["match_id"],
            compact_path=match_dir / "trajectory_compact_match_a.jsonl",
            arena_payload=leg_a,
        )
        _write_jsonl(match_pkg / "match_replay.jsonl", rows_a)

        result_payload = {
            "schema_version": "pommerman_match_result_v3",
            "schedule_mode": "double_round_robin",
            "match_legs": "single",
            "round": int(round_idx),
            "match_id": rec["match_id"],
            "agent_id": agent_id,
            "opponent_agent_id": opponent_agent_id,
            "background_agents": ["dummy2", "dummy3"],
            "requested_seed": rec.get("requested_seed"),
            "applied_seed": rec.get("applied_seed"),
            "seed_control_status": "applied" if rec.get("requested_seed") == rec.get("applied_seed") else "requested_but_not_applied",
            "match_a": {
                "agent_seat": seat_a,
                "opponent_seat": "right" if seat_a == "left" else "left",
                "winner": winner_a,
                "steps": leg_a.get("steps"),
                "reward": leg_a.get("reward"),
                "terminal_reason": "max_steps_or_env_done",
                "replay_path": "match_replay.jsonl",
            },
        }
        (match_pkg / "result.json").write_text(json.dumps(result_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        run_logs_parts: list[str] = []
        for src_name in ["build.log", "test.log", "stderr.log"]:
            ok = _copy_or_empty(match_dir / src_name, match_pkg / src_name)
            if not ok:
                missing_sources.append(f"{rec['match_id']}:{src_name}")
            src_path = match_pkg / src_name
            run_logs_parts.append(f"=== {src_name} ===")
            run_logs_parts.append(src_path.read_text(encoding="utf-8"))
        (match_pkg / "run_logs.txt").write_text("\n".join(run_logs_parts), encoding="utf-8")

        package_manifest_matches.append(
            {
                "match_id": rec["match_id"],
                "opponent_agent_id": opponent_agent_id,
                "requested_seed": rec.get("requested_seed"),
                "applied_seed": rec.get("applied_seed"),
                "winner": winner_a,
                "agent_seat": seat_a,
                "steps": leg_a.get("steps"),
                "reward": leg_a.get("reward"),
                "match_replay_path": f"matches/{rec['match_id']}/match_replay.jsonl",
                "run_logs_path": f"matches/{rec['match_id']}/run_logs.txt",
            }
        )

    package_manifest = {
        "schema_version": "pommerman_feedback_package_v3",
        "schedule_mode": "double_round_robin",
        "match_legs": "single",
        "round": int(round_idx),
        "agent_id": agent_id,
        "feedback_visibility": feedback_visibility,
        "matches": package_manifest_matches,
        "round_record": {"wins": round_wins, "losses": round_losses, "draws": round_draws},
    }
    (package_root / "package_manifest.json").write_text(json.dumps(package_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (package_root / "round_summary.json").write_text(json.dumps(package_manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    checksum_rels = ["README.md", "public_scoreboard.json", "package_manifest.json", "round_summary.json"]
    for rec in own_matches:
        mid = rec["match_id"]
        checksum_rels.extend(
            [
                f"matches/{mid}/result.json",
                f"matches/{mid}/match_replay.jsonl",
                f"matches/{mid}/run_logs.txt",
                f"matches/{mid}/build.log",
                f"matches/{mid}/test.log",
                f"matches/{mid}/stderr.log",
            ]
        )
    checksums = _checksums_for_files(package_root, checksum_rels)

    checksum_payload: dict[str, Any] = {
        "schema_version": "pommerman_feedback_checksums_v3",
        "round": int(round_idx),
        "agent_id": agent_id,
        "files": checksums,
    }
    if missing_sources:
        checksum_payload["missing_sources"] = sorted(missing_sources)

    (package_root / "checksums.json").write_text(json.dumps(checksum_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "agent_id": agent_id,
        "package_root": str(package_root),
        "own_match_count": len(own_matches),
        "public_scoreboard_path": str(package_root / "public_scoreboard.json"),
    }


def write_feedback_package_v4_for_agent(
    *,
    tournament_name: str,
    round_idx: int,
    agent_id: str,
    round_match_records: list[dict[str, Any]],
    feedback_visibility: str = "own_matches_plus_public_scoreboard",
) -> dict[str, Any]:
    if feedback_visibility != "own_matches_plus_public_scoreboard":
        raise ValueError("unsupported feedback_visibility")

    post_root = Path("workspace/posts") / tournament_name / agent_id / f"codebase_post_{round_idx}"
    package_root = post_root / "feedback" / f"round_{round_idx}"
    matches_root = package_root / "matches"
    matches_root.mkdir(parents=True, exist_ok=True)

    own_matches = [m for m in round_match_records if agent_id in {m["left_agent_id"], m["right_agent_id"]}]
    own_matches = sorted(own_matches, key=lambda m: m["match_idx"])

    public_scoreboard = {
        "schema_version": "pommerman_public_scoreboard_v4",
        "round": int(round_idx),
        "schedule_mode": "double_round_robin",
        "match_legs": "single",
        "matches": [],
    }
    for rec in sorted(round_match_records, key=lambda m: m["match_idx"]):
        match_dir = Path(rec["match_dir"])
        arena = _load_json(match_dir / "arena_result_match_a.json") if (match_dir / "arena_result_match_a.json").exists() else {}
        public_scoreboard["matches"].append(
            {
                "round": int(round_idx),
                "match_id": rec["match_id"],
                "left_agent_id": rec["left_agent_id"],
                "right_agent_id": rec["right_agent_id"],
                "winner": _winner(arena.get("left_right_winner")),
                "steps": arena.get("steps"),
                "reward": arena.get("reward"),
                "applied_seed": rec.get("applied_seed"),
                **classify_pommerman_result(arena),
            }
        )

    (package_root / "README.md").write_text(V4_README, encoding="utf-8")
    (package_root / "public_scoreboard.json").write_text(
        json.dumps(public_scoreboard, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    manifest_matches: list[str] = []
    replay_sources: set[str] = set()
    full_board_replay = True

    for rec in own_matches:
        match_dir = Path(rec["match_dir"])
        match_pkg = matches_root / rec["match_id"]
        official_pkg_dir = match_pkg / "official_record_json"
        official_pkg_dir.mkdir(parents=True, exist_ok=True)

        arena = _load_json(match_dir / "arena_result_match_a.json") if (match_dir / "arena_result_match_a.json").exists() else {}
        classification = classify_pommerman_result(arena)
        agent_seat = _seat_for_agent(agent_id, rec["left_agent_id"], rec["right_agent_id"])
        opponent_seat = "right" if agent_seat == "left" else "left"
        opponent_agent_id = _opponent_agent_id(agent_id, rec["left_agent_id"], rec["right_agent_id"])

        official_src = match_dir / "official_record_json_match_a" / "game_state.json"
        official_present = official_src.exists()
        if official_present:
            shutil.copy2(official_src, official_pkg_dir / "game_state.json")
            replay_sources.add("pommerman_record_json_dir")
        else:
            (official_pkg_dir / "README.txt").write_text(
                "Official Pommerman game_state.json was not available for this match. "
                "This package uses compact_trajectory_fallback; see package_manifest.json and actions.jsonl.\n",
                encoding="utf-8",
            )
            replay_sources.add("compact_trajectory_fallback")
            full_board_replay = False

        actions_rel = "actions.jsonl"
        _write_v4_actions(
            path=match_pkg / actions_rel,
            compact_path=match_dir / "trajectory_compact_match_a.jsonl",
            agent_seat=agent_seat,
            opponent_seat=opponent_seat,
        )

        match_index = {
            "schema_version": "pommerman_match_index_v4",
            "round": int(round_idx),
            "match_id": rec["match_id"],
            "agent_id": agent_id,
            "opponent_agent_id": opponent_agent_id,
            "requested_seed": rec.get("requested_seed"),
            "applied_seed": rec.get("applied_seed"),
            "schedule_mode": "double_round_robin",
            "match_legs": "single",
            "seat_swap": False,
            "game": {
                "internal_leg_id": "match_a",
                "agent_seat": agent_seat,
                "opponent_seat": opponent_seat,
                "winner": _winner(arena.get("left_right_winner")),
                "steps": arena.get("steps"),
                "reward": arena.get("reward"),
                **classification,
                "official_record_path": "official_record_json/game_state.json",
                "actions_path": actions_rel,
            },
        }
        (match_pkg / "match_index.json").write_text(
            json.dumps(match_index, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        run_logs_parts: list[str] = []
        for src_name in ["build.log", "test.log", "stderr.log"]:
            run_logs_parts.append(f"=== {src_name} ===")
            src = match_dir / src_name
            run_logs_parts.append(src.read_text(encoding="utf-8") if src.exists() else "<missing>")
        (match_pkg / "run_logs.txt").write_text(
            sanitize_model_visible_run_log("\n".join(run_logs_parts)), encoding="utf-8"
        )
        manifest_matches.append(f"matches/{rec['match_id']}/match_index.json")

    replay_source = "pommerman_record_json_dir" if replay_sources == {"pommerman_record_json_dir"} else "compact_trajectory_fallback"
    if replay_source == "compact_trajectory_fallback":
        full_board_replay = False
    package_manifest = {
        "schema_version": "pommerman_feedback_package_v4",
        "round": int(round_idx),
        "agent_id": agent_id,
        "visibility": feedback_visibility,
        "schedule_mode": "double_round_robin",
        "match_legs": "single",
        "matches": manifest_matches,
        "replay_source": replay_source,
        "full_board_replay": bool(full_board_replay),
        "contains_private_opponent_code": False,
    }
    (package_root / "package_manifest.json").write_text(
        json.dumps(package_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {
        "agent_id": agent_id,
        "package_root": str(package_root),
        "own_match_count": len(own_matches),
        "public_scoreboard_path": str(package_root / "public_scoreboard.json"),
        "replay_source": replay_source,
        "full_board_replay": bool(full_board_replay),
    }


def stage_feedback_packages_for_round(
    *,
    tournament_name: str,
    round_idx: int,
    agent_ids: list[str],
    round_match_records: list[dict[str, Any]],
    feedback_visibility: str = "own_matches_plus_public_scoreboard",
    feedback_package_variant: str = "codeclash_v3",
) -> dict[str, Any]:
    from runner.core.fsops import copy_tree

    created: list[str] = []
    for agent_id in agent_ids:
        play_dir = Path("workspace/codebases") / tournament_name / agent_id / f"codebase_play_{round_idx}"
        post_dir = Path("workspace/posts") / tournament_name / agent_id / f"codebase_post_{round_idx}"
        if play_dir.exists():
            copy_tree(play_dir, post_dir)
        else:
            post_dir.mkdir(parents=True, exist_ok=True)
        write_feedback_package_for_agent(
            tournament_name=tournament_name,
            round_idx=round_idx,
            agent_id=agent_id,
            round_match_records=round_match_records,
            feedback_visibility=feedback_visibility,
            feedback_package_variant=feedback_package_variant,
        )
        created.append(agent_id)

    return {
        "tournament_name": tournament_name,
        "round": int(round_idx),
        "agents": created,
        "package_count": len(created),
    }


__all__ = [
    "write_feedback_package_for_agent",
    "write_feedback_package_v4_for_agent",
    "stage_feedback_packages_for_round",
    "sanitize_model_visible_run_log",
    "NEUTRAL_README",
    "V4_README",
]

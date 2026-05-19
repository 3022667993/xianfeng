from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _infer_tournament_name(logs_root: Path) -> str | None:
    ism = logs_root / "initial_synthesis_manifest.json"
    if ism.exists():
        try:
            payload = _load_json(ism)
            value = payload.get("tournament")
            if isinstance(value, str) and value.strip():
                return value.strip()
        except Exception:
            return None
    return None


def _load_cfg(tournament_name: str | None) -> dict[str, Any]:
    if not isinstance(tournament_name, str) or not tournament_name.strip():
        return {}
    path = Path("configs/tournaments") / f"{tournament_name}.yaml"
    if not path.exists():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def audit_double_round_robin_schedule(
    tournament_name: str | None = None,
    logs_root: Path = Path("logs"),
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    tournament = tournament_name or _infer_tournament_name(logs_root)
    cfg = _load_cfg(tournament)
    num_models = int(cfg.get("num_models", 0) or 0)
    if num_models <= 0:
        ism = logs_root / "initial_synthesis_manifest.json"
        if ism.exists():
            try:
                payload = _load_json(ism)
                agents = payload.get("agents", [])
                if isinstance(agents, list):
                    num_models = len([a for a in agents if isinstance(a, dict) and isinstance(a.get("agent_id"), str)])
            except Exception:
                num_models = 0

    if num_models < 2:
        errors.append("unable to determine num_models for double_round_robin schedule audit")
        return errors, warnings
    if num_models % 2 == 1:
        errors.append("double_round_robin requires an even number of agents; BYE scheduling is not implemented yet.")
        return errors, warnings

    expected_matches_per_round = num_models // 2
    full_double_rr_rounds = 2 * (num_models - 1)
    configured_rounds = int(cfg.get("num_rounds", 0) or 0)
    if configured_rounds > full_double_rr_rounds:
        errors.append(
            f"num_rounds exceeds full double round robin without repeat mode: {configured_rounds} > {full_double_rr_rounds}"
        )

    round_dirs = sorted(p for p in logs_root.glob("round_*") if p.is_dir())
    if not round_dirs:
        errors.append("no round directories found under logs/")
        return errors, warnings

    seen_pairs: dict[tuple[str, str], list[tuple[str, str, int, int]]] = {}
    rounds_seen = 0
    games_seen = 0

    for rd in round_dirs:
        try:
            round_idx = int(rd.name.split("_", 1)[1])
        except Exception:
            continue
        rm_path = rd / "round_manifest.json"
        if not rm_path.exists():
            errors.append(f"{rd}: missing round_manifest.json")
            continue
        rm = _load_json(rm_path)
        rounds_seen += 1

        if rm.get("schedule_mode", "double_round_robin") != "double_round_robin":
            errors.append(f"{rm_path}: schedule_mode must be double_round_robin")
        if rm.get("match_legs", "single") != "single":
            errors.append(f"{rm_path}: match_legs must be single")
        if int(rm.get("matches_per_round", -1) or -1) != expected_matches_per_round:
            errors.append(f"{rm_path}: matches_per_round must be {expected_matches_per_round}")

        matches = rm.get("matches", [])
        if not isinstance(matches, list) or len(matches) != expected_matches_per_round:
            errors.append(f"{rm_path}: expected exactly {expected_matches_per_round} matches")
            continue

        round_agents: list[str] = []
        for m in matches:
            if not isinstance(m, dict):
                errors.append(f"{rm_path}: match entry must be an object")
                continue
            left = m.get("left_agent_id")
            right = m.get("right_agent_id")
            if not isinstance(left, str) or not isinstance(right, str):
                errors.append(f"{rm_path}: left_agent_id/right_agent_id must be strings")
                continue
            if left == right:
                errors.append(f"{rm_path}: self match detected for {left}")
            round_agents.extend([left, right])

            match_dir = rd / f"match_{int(m.get('match_idx', 0) or 0)}"
            if (match_dir / "arena_result_match_b.json").exists():
                errors.append(f"{match_dir}: arena_result_match_b.json must not exist in single-leg mode")
            if (match_dir / "trajectory_compact_match_b.jsonl").exists():
                errors.append(f"{match_dir}: trajectory_compact_match_b.jsonl must not exist in single-leg mode")
            if not (match_dir / "arena_result_match_a.json").exists():
                errors.append(f"{match_dir}: missing arena_result_match_a.json")

            pair_key = tuple(sorted([left, right]))
            seen_pairs.setdefault(pair_key, []).append((left, right, round_idx, int(m.get("match_idx", 0) or 0)))
            games_seen += 1

        if len(round_agents) != num_models or len(set(round_agents)) != num_models:
            errors.append(f"{rm_path}: round must cover all {num_models} agents exactly once")

    if configured_rounds and rounds_seen != configured_rounds:
        errors.append(f"expected exactly {configured_rounds} emitted rounds, found {rounds_seen}")
    if rounds_seen > full_double_rr_rounds:
        errors.append(f"emitted rounds exceed full double round robin: {rounds_seen} > {full_double_rr_rounds}")

    complete = rounds_seen == full_double_rr_rounds
    if complete:
        expected_games = num_models * (num_models - 1)
        if games_seen != expected_games:
            errors.append(f"expected {expected_games} total games, found {games_seen}")
        expected_pairs = (num_models * (num_models - 1)) // 2
        if len(seen_pairs) != expected_pairs:
            errors.append(f"expected {expected_pairs} unique pairs, found {len(seen_pairs)}")
        for pair_key, entries in seen_pairs.items():
            if len(entries) != 2:
                errors.append(f"{pair_key[0]}__vs__{pair_key[1]}: expected exactly two encounters")
                continue
            first, second = sorted(entries, key=lambda x: (x[2], x[3]))
            if first[0] == second[0] or first[1] == second[1]:
                errors.append(f"{pair_key[0]}__vs__{pair_key[1]}: second encounter must reverse left/right")
    else:
        if rounds_seen >= full_double_rr_rounds:
            warnings.append("schedule reached or exceeded full double round robin but round count check failed elsewhere")

    return errors, warnings


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--tournament", required=False)
    parser.add_argument("--logs-root", default="logs")
    args = parser.parse_args()

    errors, warnings = audit_double_round_robin_schedule(
        tournament_name=args.tournament,
        logs_root=Path(args.logs_root),
    )
    for w in warnings:
        print(f"WARN {w}")
    if errors:
        print("pommerman_double_round_robin_schedule_audit=FAIL")
        for e in errors:
            print(f"ERROR {e}")
        return 1
    print("pommerman_double_round_robin_schedule_audit=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

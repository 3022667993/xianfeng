from __future__ import annotations

import argparse
import json
import math
import subprocess
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runner.core.config import ODD_MODEL_COUNT_ERROR


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _pair_tuple(pair_id: str) -> tuple[str, str]:
    a, b = pair_id.split("__vs__", 1)
    return a, b


def _match_legs_ok(match: dict) -> bool:
    return match.get("match_legs") in {"single", None}


def audit_manifest(path: Path) -> tuple[list[str], list[str]]:
    data = _load_json(path)
    errors: list[str] = []
    warnings: list[str] = []

    if data.get("schema_version") != "pommerman_formal_schedule_manifest_v2":
        errors.append("schema_version mismatch")
    if data.get("game") != "pommerman_1v1":
        errors.append("game must be pommerman_1v1")
    if data.get("regime") != "A00":
        errors.append("regime must be A00")
    if data.get("schedule_mode") != "double_round_robin":
        errors.append("schedule_mode mismatch")
    if data.get("match_legs") != "single":
        errors.append("match_legs must be single")
    if data.get("scorecard_policy") != "raw_per_match_scorecard; pair-level aggregation is post-analysis":
        errors.append("scorecard_policy mismatch")
    if data.get("background_agents") != ["dummy2", "dummy3"]:
        errors.append("background_agents must be ['dummy2', 'dummy3']")

    models = data.get("models")
    if not isinstance(models, list) or len(models) < 2:
        errors.append("at least 2 models required")
        return errors, warnings
    model_ids = [m.get("id") for m in models if isinstance(m, dict)]
    n = len(model_ids)
    if len(set(model_ids)) != n:
        errors.append("model ids must be unique")
    if n % 2 == 1:
        errors.append(ODD_MODEL_COUNT_ERROR)

    expected_matches_per_round = n // 2
    expected_full_rounds = 2 * (n - 1)
    expected_total_matches = n * (n - 1)
    expected_pairs = math.comb(n, 2)

    rounds = data.get("rounds")
    if not isinstance(rounds, list) or not rounds:
        errors.append("rounds must be a non-empty list")
        return errors, warnings

    emitted_rounds = len(rounds)
    complete = bool(data.get("complete_double_round_robin", False))
    if emitted_rounds > expected_full_rounds:
        errors.append(f"emitted rounds exceed full double round robin: {emitted_rounds} > {expected_full_rounds}")
    if data.get("emitted_rounds") not in {None, emitted_rounds}:
        errors.append("emitted_rounds mismatch")

    seen_pairs: dict[str, list[tuple[int, int, dict]]] = {}
    total_matches = 0
    for r in rounds:
        if not isinstance(r, dict):
            errors.append("round entry must be object")
            continue
        round_idx = r.get("round_idx")
        cycle = r.get("cycle")
        matches = r.get("matches")
        if not isinstance(matches, list) or len(matches) != expected_matches_per_round:
            errors.append(f"round_{round_idx}: exactly {expected_matches_per_round} matches required")
            continue
        seen: list[str] = []
        for m in matches:
            total_matches += 1
            left = m.get("left_agent")
            right = m.get("right_agent")
            if left == right:
                errors.append(f"round_{round_idx}: self match detected")
            seen.extend([left, right])
            pair_id = m.get("pair_id")
            if not isinstance(pair_id, str) or "__vs__" not in pair_id:
                errors.append(f"round_{round_idx}: invalid pair_id")
                continue
            if not _match_legs_ok(m):
                errors.append(f"round_{round_idx}: {pair_id} match_legs must be single")
            if m.get("schedule_mode") != "double_round_robin":
                errors.append(f"round_{round_idx}: {pair_id} schedule_mode mismatch")
            if m.get("num_agents") != n:
                errors.append(f"round_{round_idx}: {pair_id} num_agents mismatch")
            if m.get("full_double_rr_rounds") != expected_full_rounds:
                errors.append(f"round_{round_idx}: {pair_id} full_double_rr_rounds mismatch")
            if m.get("emitted_rounds") not in {emitted_rounds, None}:
                errors.append(f"round_{round_idx}: {pair_id} emitted_rounds mismatch")
            if m.get("complete_double_round_robin") != complete:
                errors.append(f"round_{round_idx}: {pair_id} complete_double_round_robin mismatch")
            if m.get("encounter_index") not in {1, 2}:
                errors.append(f"round_{round_idx}: {pair_id} invalid encounter_index")
            seen_pairs.setdefault(pair_id, []).append((int(round_idx), int(m.get("match_idx", 0) or 0), m))
        if sorted(seen) != sorted(model_ids):
            errors.append(f"round_{round_idx}: not a perfect matching")

    if total_matches != emitted_rounds * expected_matches_per_round:
        errors.append("total match count mismatch")

    if emitted_rounds == expected_full_rounds:
        if total_matches != expected_total_matches:
            errors.append(f"exactly {expected_total_matches} total matches required")
        if len(seen_pairs) != expected_pairs:
            errors.append(f"exactly {expected_pairs} canonical pairs required")
        for pair_id, entries in seen_pairs.items():
            if len(entries) != 2:
                errors.append(f"{pair_id}: full schedule requires exactly two encounters")
                continue
            first, second = sorted(entries, key=lambda x: (x[0], x[1]))
            if first[2].get("left_agent") == second[2].get("left_agent"):
                errors.append(f"{pair_id}: second encounter must reverse left/right")
            if first[2].get("encounter_index") != 1 or second[2].get("encounter_index") != 2:
                errors.append(f"{pair_id}: encounter_index mismatch")
    else:
        if complete:
            errors.append("complete_double_round_robin cannot be true for a prefix schedule")

    pair_order_by_cycle = data.get("pair_order_by_cycle")
    if isinstance(pair_order_by_cycle, dict):
        c1 = pair_order_by_cycle.get("1") or pair_order_by_cycle.get(1)
        c2 = pair_order_by_cycle.get("2") or pair_order_by_cycle.get(2)
        if isinstance(c1, list) and isinstance(c2, list) and c1 and c2 and c1 != c2:
            errors.append("cycle_1 pair order must equal cycle_2 pair order")

    pairs = data.get("pairs")
    if isinstance(pairs, list):
        for pair in pairs:
            if not isinstance(pair, dict):
                continue
            pair_id = str(pair.get("pair_id") or "unknown_pair")
            legs = pair.get("legs")
            if not isinstance(legs, list):
                continue
            planned = [leg.get("planned_seed") for leg in legs if isinstance(leg, dict)]
            if len(set(planned)) > 1:
                errors.append(f"{pair_id}: planned_seed mismatch")
            applied = [leg.get("applied_seed") for leg in legs if isinstance(leg, dict) and leg.get("applied_seed") is not None]
            if len(set(applied)) > 1:
                errors.append(f"{pair_id}: applied_seed mismatch")

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="logs/pommerman_formal_schedule_manifest.json")
    parser.add_argument("--models", default="configs/models/openclaw_relay_current.yaml")
    parser.add_argument(
        "--tournament",
        default="configs/tournaments/pommerman_gptv16_a00_openclaw_initial_synthesis_full_neutral_double_rr.yaml",
    )
    args = parser.parse_args()

    manifest = Path(args.manifest)
    subprocess.run(
        [
            "python",
            "scripts/build_pommerman_formal_schedule_manifest.py",
            "--models",
            args.models,
            "--tournament",
            args.tournament,
            "--output",
            str(manifest),
        ],
        check=True,
    )

    errors, warnings = audit_manifest(manifest)
    for w in warnings:
        print(f"WARN {w}")
    if errors:
        print("formal_schedule_audit=FAIL")
        for e in errors:
            print(f"ERROR {e}")
        return 1
    print("formal_schedule_audit=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

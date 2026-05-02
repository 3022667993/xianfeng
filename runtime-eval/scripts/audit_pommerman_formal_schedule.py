from __future__ import annotations

import argparse
import json
import math
import subprocess
from pathlib import Path


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _pair_tuple(pair_id: str) -> tuple[str, str]:
    a, b = pair_id.split("__vs__", 1)
    return a, b


def audit_manifest(path: Path) -> tuple[list[str], list[str]]:
    data = _load_json(path)
    errors: list[str] = []
    warnings: list[str] = []

    if data.get("schema_version") != "pommerman_formal_schedule_manifest_v1":
        errors.append("schema_version mismatch")
    if data.get("game") != "pommerman_1v1":
        errors.append("game must be pommerman_1v1")
    if data.get("regime") != "A00":
        errors.append("regime must be A00")
    if data.get("schedule_type") != "two_cycle_double_round_robin":
        errors.append("schedule_type mismatch")
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

    rounds = data.get("rounds")
    expected_total_rounds = 2 * (n - 1) if n % 2 == 0 else 2 * n
    expected_matches_per_round = n // 2
    expected_total_matches = n * (n - 1)
    expected_pairs = math.comb(n, 2)
    if not isinstance(rounds, list) or len(rounds) != expected_total_rounds:
        errors.append(f"exactly {expected_total_rounds} rounds required")
        return errors, warnings

    cycle1_order: list[str] = []
    cycle2_order: list[str] = []
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

        seen = []
        for m in matches:
            total_matches += 1
            left = m.get("left_agent")
            right = m.get("right_agent")
            seen.extend([left, right])
            pair_id = m.get("pair_id")
            if m.get("background_agents") != ["dummy2", "dummy3"]:
                errors.append(f"round_{round_idx}: {pair_id} background_agents mismatch")

            status = m.get("seed_control_status")
            planned = m.get("planned_seed")
            app = m.get("applied_seed")
            seed = m.get("seed")
            if status == "planned_not_executed":
                if planned is None:
                    errors.append(f"round_{round_idx}: {pair_id} planned_not_executed requires planned_seed")
                if app is not None:
                    errors.append(f"round_{round_idx}: {pair_id} planned_not_executed requires null applied_seed")
                if seed is not None:
                    errors.append(f"round_{round_idx}: {pair_id} planned_not_executed requires null seed")
                if m.get("result_path") is not None or m.get("arena_result_path") is not None:
                    errors.append(f"round_{round_idx}: {pair_id} planned_not_executed must not set result paths")
            elif status == "recorded":
                if app is None:
                    errors.append(f"round_{round_idx}: {pair_id} recorded requires applied_seed")
                if m.get("result_path") is None and m.get("arena_result_path") is None:
                    errors.append(f"round_{round_idx}: {pair_id} recorded requires result_path or arena_result_path")
            else:
                errors.append(f"round_{round_idx}: {pair_id} unsupported seed_control_status={status!r}")

            if cycle == 1:
                cycle1_order.append(pair_id)
            elif cycle == 2:
                cycle2_order.append(pair_id)
            else:
                errors.append(f"round_{round_idx}: invalid cycle {cycle}")

        if sorted(seen) != sorted(model_ids):
            if n % 2 == 0:
                errors.append(f"round_{round_idx}: not a perfect matching")
            else:
                bye_agent = r.get("bye_agent")
                if bye_agent not in model_ids:
                    errors.append(f"round_{round_idx}: odd-N schedule requires valid bye_agent")
                expected_seen = sorted([m for m in model_ids if m != bye_agent])
                if sorted(seen) != expected_seen:
                    errors.append(f"round_{round_idx}: odd-N near-perfect matching violated")

    if total_matches != expected_total_matches:
        errors.append(f"exactly {expected_total_matches} total matches required")

    pairs = data.get("pairs")
    if not isinstance(pairs, list) or len(pairs) != expected_pairs:
        errors.append(f"exactly {expected_pairs} canonical pairs required")
        return errors, warnings

    seen_pairs = set()
    for p in pairs:
        if not isinstance(p, dict):
            errors.append("pair entry must be object")
            continue
        pair_id = p.get("pair_id")
        if not isinstance(pair_id, str) or "__vs__" not in pair_id:
            errors.append("invalid pair_id")
            continue
        seen_pairs.add(pair_id)
        a, b = _pair_tuple(pair_id)
        if p.get("agent_A") != a or p.get("agent_B") != b:
            errors.append(f"{pair_id}: canonical agent_A/agent_B mismatch")
        if p.get("background_agents") != ["dummy2", "dummy3"]:
            errors.append(f"{pair_id}: background_agents mismatch")

        legs = p.get("legs")
        if not isinstance(legs, list) or len(legs) != 2:
            errors.append(f"{pair_id}: exactly two legs required")
            continue
        l1 = next((x for x in legs if x.get("cycle") == 1), None)
        l2 = next((x for x in legs if x.get("cycle") == 2), None)
        if l1 is None or l2 is None:
            errors.append(f"{pair_id}: missing cycle_1 or cycle_2 leg")
            continue
        if l1.get("agent_A_seat") != "left" or l1.get("agent_B_seat") != "right":
            errors.append(f"{pair_id}: cycle_1 must be A-left/B-right")
        if l2.get("agent_A_seat") != "right" or l2.get("agent_B_seat") != "left":
            errors.append(f"{pair_id}: cycle_2 must be A-right/B-left")

        if l1.get("planned_seed") != l2.get("planned_seed"):
            errors.append(f"{pair_id}: planned_seed mismatch across legs")
        a1 = l1.get("applied_seed")
        a2 = l2.get("applied_seed")
        if a1 is not None and a2 is not None and a1 != a2:
            errors.append(f"{pair_id}: applied_seed mismatch across legs")

    if len(seen_pairs) != expected_pairs:
        errors.append("canonical pair count mismatch")

    if len(cycle1_order) != expected_pairs or len(cycle2_order) != expected_pairs:
        errors.append(f"each cycle must contain {expected_pairs} matches")
    else:
        if set(cycle1_order) != seen_pairs:
            errors.append("cycle_1 must contain every canonical pair exactly once")
        if set(cycle2_order) != seen_pairs:
            errors.append("cycle_2 must contain every canonical pair exactly once")
        if cycle1_order != cycle2_order:
            errors.append("cycle_1 pair order must equal cycle_2 pair order")

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="logs/pommerman_formal_schedule_manifest.json")
    parser.add_argument("--models", default="configs/models/openclaw_relay_6model_gptv16.yaml")
    parser.add_argument(
        "--tournament",
        default="configs/tournaments/pommerman_gptv16_a00_6model_schedule_smoke.yaml",
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

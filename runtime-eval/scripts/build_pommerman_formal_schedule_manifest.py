from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import yaml


def _load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _stable_pair_seed(pair_id: str, base_seed: int) -> int:
    material = f"{pair_id}|{base_seed}"
    return int(hashlib.sha256(material.encode("utf-8")).hexdigest()[:8], 16) & 0x7FFFFFFF


def _round_robin_pairs(models: list[dict]) -> list[list[tuple[dict, dict]]]:
    order = list(models)
    rounds: list[list[tuple[dict, dict]]] = []
    for _ in range(len(order) - 1):
        half = len(order) // 2
        left_half = order[:half]
        right_half = list(reversed(order[half:]))
        rounds.append(list(zip(left_half, right_half)))
        order = [order[0], order[-1], *order[1:-1]]
    return rounds


def build_manifest(models_cfg: dict, tournament_cfg: dict) -> dict:
    models = models_cfg.get("models", []) if isinstance(models_cfg, dict) else []
    if not isinstance(models, list) or len(models) != 6:
        raise ValueError("formal schedule requires exactly 6 models")

    model_entries: list[dict] = []
    for idx, m in enumerate(models, start=1):
        if not isinstance(m, dict):
            raise ValueError(f"model entry #{idx} must be a mapping")
        mid = m.get("id")
        if not isinstance(mid, str) or not mid.strip():
            raise ValueError(f"model entry #{idx} missing id")
        model_entries.append(
            {
                "id": mid,
                "agent_id": m.get("agent_id"),
                "provider_model": m.get("provider_model"),
                "executor": m.get("executor"),
            }
        )

    if int(tournament_cfg.get("num_rounds", 0)) != 10:
        raise ValueError("formal schedule requires num_rounds=10")
    if int(tournament_cfg.get("matches_per_round", 0)) != 3:
        raise ValueError("formal schedule requires matches_per_round=3")

    background_agents = ["dummy2", "dummy3"]
    base_seed = int(tournament_cfg.get("base_seed", tournament_cfg.get("seed", 1001)))

    cycle1_pairs = _round_robin_pairs(model_entries)
    cycle2_pairs = [[(b, a) for (a, b) in r] for r in cycle1_pairs]

    rounds = []
    pairs_by_id: dict[str, dict] = {}
    cycle1_pair_order: list[str] = []
    cycle2_pair_order: list[str] = []

    def canonical_pair(a: str, b: str) -> tuple[str, str]:
        ordered = sorted([a, b])
        return ordered[0], ordered[1]

    for round_idx, round_matches in enumerate([*cycle1_pairs, *cycle2_pairs], start=1):
        cycle = 1 if round_idx <= 5 else 2
        match_entries = []
        for match_idx, (left, right) in enumerate(round_matches, start=1):
            left_id = left["id"]
            right_id = right["id"]
            agent_a, agent_b = canonical_pair(left_id, right_id)
            pair_id = f"{agent_a}__vs__{agent_b}"
            planned_seed = _stable_pair_seed(pair_id, base_seed)

            if cycle == 1:
                cycle1_pair_order.append(pair_id)
                agent_a_seat = "left"
                agent_b_seat = "right"
            else:
                cycle2_pair_order.append(pair_id)
                agent_a_seat = "right"
                agent_b_seat = "left"

            match_payload = {
                "cycle": cycle,
                "round_idx": round_idx,
                "match_idx": match_idx,
                "pair_id": pair_id,
                "agent_A": agent_a,
                "agent_B": agent_b,
                "left_agent": left_id,
                "right_agent": right_id,
                "agent_A_seat": agent_a_seat,
                "agent_B_seat": agent_b_seat,
                "background_agents": background_agents,
                "planned_seed": planned_seed,
                "applied_seed": None,
                "seed": None,
                "seed_control_status": "planned_not_executed",
                "result_path": None,
                "arena_result_path": None,
            }
            match_entries.append(match_payload)

            pair_entry = pairs_by_id.setdefault(
                pair_id,
                {
                    "pair_id": pair_id,
                    "agent_A": agent_a,
                    "agent_B": agent_b,
                    "background_agents": background_agents,
                    "legs": [],
                },
            )
            pair_entry["legs"].append(
                {
                    "cycle": cycle,
                    "round_idx": round_idx,
                    "match_idx": match_idx,
                    "agent_A_seat": agent_a_seat,
                    "agent_B_seat": agent_b_seat,
                    "planned_seed": planned_seed,
                    "applied_seed": None,
                    "seed": None,
                    "seed_control_status": "planned_not_executed",
                    "result_path": None,
                    "arena_result_path": None,
                }
            )

        rounds.append({"round_idx": round_idx, "cycle": cycle, "matches": match_entries})

    return {
        "schema_version": "pommerman_formal_schedule_manifest_v1",
        "game": "pommerman_1v1",
        "regime": "A00",
        "tournament": tournament_cfg.get("name", "pommerman_gptv16_a00_6model_schedule_smoke"),
        "schedule_type": "two_cycle_double_round_robin",
        "num_models": 6,
        "matches_per_round": 3,
        "total_rounds": 10,
        "total_matches": 30,
        "cycle_1_rounds": [1, 2, 3, 4, 5],
        "cycle_2_rounds": [6, 7, 8, 9, 10],
        "background_agents": background_agents,
        "scorecard_policy": "raw_per_match_scorecard; pair-level aggregation is post-analysis",
        "models": model_entries,
        "rounds": rounds,
        "pairs": [pairs_by_id[k] for k in sorted(pairs_by_id)],
        "cycle_1_pair_order": cycle1_pair_order,
        "cycle_2_pair_order": cycle2_pair_order,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", default="configs/models/openclaw_relay_6model_gptv16.yaml")
    parser.add_argument(
        "--tournament",
        default="configs/tournaments/pommerman_gptv16_a00_6model_schedule_smoke.yaml",
    )
    parser.add_argument("--output", default="logs/pommerman_formal_schedule_manifest.json")
    args = parser.parse_args()

    models_cfg = _load_yaml(Path(args.models))
    tournament_cfg = _load_yaml(Path(args.tournament))
    manifest = build_manifest(models_cfg, tournament_cfg)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote formal schedule manifest: {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

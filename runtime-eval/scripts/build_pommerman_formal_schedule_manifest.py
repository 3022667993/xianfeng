from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runner.core.schedule import build_double_round_robin
from runner.core.config import ODD_MODEL_COUNT_ERROR, resolve_tournament_counts


def _load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _stable_pair_seed(pair_id: str, base_seed: int) -> int:
    material = f"{pair_id}|{base_seed}"
    return int(hashlib.sha256(material.encode("utf-8")).hexdigest()[:8], 16) & 0x7FFFFFFF


def build_manifest(models_cfg: dict, tournament_cfg: dict) -> dict:
    models = models_cfg.get("models", []) if isinstance(models_cfg, dict) else []
    if not isinstance(models, list) or len(models) < 2:
        raise ValueError("formal schedule requires at least 2 models")
    if len(models) % 2 == 1:
        raise ValueError(ODD_MODEL_COUNT_ERROR)
    tournament_cfg = resolve_tournament_counts(tournament_cfg, models)

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

    background_agents = ["dummy2", "dummy3"]
    base_seed = int(tournament_cfg.get("base_seed", tournament_cfg.get("seed", 1001)))
    num_rounds = int(tournament_cfg.get("num_rounds", 0) or 0)
    schedule = build_double_round_robin([m["id"] for m in model_entries], num_rounds=num_rounds)

    rounds = []
    pairs_by_id: dict[str, dict] = {}
    pair_order_by_cycle = schedule["pair_order_by_cycle"]

    for round_item in schedule["rounds"]:
        round_idx = int(round_item["round_idx"])
        cycle = int(round_item["cycle"])
        match_entries = []
        for m in round_item["matches"]:
            match_idx = int(m["match_idx"])
            left_id = str(m["left_agent"])
            right_id = str(m["right_agent"])
            agent_a = str(m["agent_A"])
            agent_b = str(m["agent_B"])
            pair_id = str(m["pair_id"])
            planned_seed = _stable_pair_seed(pair_id, base_seed)
            match_payload = {
                "cycle": cycle,
                "round_idx": round_idx,
                "match_idx": match_idx,
                "pair_id": pair_id,
                "agent_A": agent_a,
                "agent_B": agent_b,
                "left_agent": left_id,
                "right_agent": right_id,
                "agent_A_seat": str(m["agent_A_seat"]),
                "agent_B_seat": str(m["agent_B_seat"]),
                "encounter_index": int(m["encounter_index"]),
                "reverse_of_round": m.get("reverse_of_round"),
                "reverse_of_match": m.get("reverse_of_match"),
                "schedule_mode": "double_round_robin",
                "match_legs": "single",
                "num_agents": schedule["num_agents"],
                "full_double_rr_rounds": schedule["full_double_rr_rounds"],
                "emitted_rounds": schedule["emitted_rounds"],
                "complete_double_round_robin": schedule["complete_double_round_robin"],
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
                    "agent_A_seat": str(m["agent_A_seat"]),
                    "agent_B_seat": str(m["agent_B_seat"]),
                    "encounter_index": int(m["encounter_index"]),
                    "reverse_of_round": m.get("reverse_of_round"),
                    "reverse_of_match": m.get("reverse_of_match"),
                    "planned_seed": planned_seed,
                    "applied_seed": None,
                    "seed": None,
                    "seed_control_status": "planned_not_executed",
                    "result_path": None,
                    "arena_result_path": None,
                }
            )

        rounds.append(
            {
                "round_idx": round_idx,
                "cycle": cycle,
                "matches": match_entries,
            }
        )

    return {
        "schema_version": "pommerman_formal_schedule_manifest_v2",
        "game": "pommerman_1v1",
        "regime": "A00",
        "tournament": tournament_cfg.get("name", "pommerman_gptv16_a00_6model_schedule_smoke"),
        "schedule_mode": "double_round_robin",
        "match_legs": "single",
        "num_models": schedule["num_agents"],
        "matches_per_round": schedule["matches_per_round"],
        "total_rounds": schedule["emitted_rounds"],
        "full_double_rr_rounds": schedule["full_double_rr_rounds"],
        "emitted_rounds": schedule["emitted_rounds"],
        "complete_double_round_robin": schedule["complete_double_round_robin"],
        "total_matches": schedule["total_matches"],
        "canonical_pairs_count": schedule["canonical_pairs_count"],
        "background_agents": background_agents,
        "scorecard_policy": "raw_per_match_scorecard; pair-level aggregation is post-analysis",
        "models": model_entries,
        "rounds": rounds,
        "pairs": [pairs_by_id[k] for k in sorted(pairs_by_id)],
        "pair_order_by_cycle": pair_order_by_cycle,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", default="configs/models/openclaw_relay_current.yaml")
    parser.add_argument(
        "--tournament",
        default="configs/tournaments/pommerman_gptv16_a00_openclaw_initial_synthesis_full_neutral_double_rr.yaml",
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

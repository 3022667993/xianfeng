from __future__ import annotations

import argparse
import json
from pathlib import Path


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_stable_identity(value: object) -> bool:
    if not isinstance(value, str):
        return False
    v = value.strip().lower()
    return bool(v) and v not in {"left", "right"}


def _identity_from_metadata(metadata: dict, side: str) -> str | None:
    candidates = [
        metadata.get(f"{side}_agent_id"),
        metadata.get(f"{side}_model_id"),
    ]
    for c in candidates:
        if _is_stable_identity(c):
            return str(c)
    return None


def _seed_and_status(scorecard: dict) -> tuple[object, str]:
    status = scorecard.get("seed_control_status")
    requested_seed = scorecard.get("requested_seed")
    applied_seed = scorecard.get("applied_seed")
    seed = scorecard.get("seed")
    if status is None:
        return None, None, None, "not_recorded_in_current_smoke"
    return seed, requested_seed, applied_seed, str(status)


def build_manifest(logs_root: Path) -> dict:
    md1 = _load_json(logs_root / "round_1" / "metadata.json")
    sc1 = _load_json(logs_root / "round_1" / "scorecard.json")
    sc2 = _load_json(logs_root / "round_2" / "scorecard.json")

    agent_a = _identity_from_metadata(md1, "left") or "smoke_agent_A"
    agent_b = _identity_from_metadata(md1, "right") or "smoke_agent_B"
    if agent_a == agent_b:
        agent_a = "smoke_agent_A"
        agent_b = "smoke_agent_B"

    seed1, requested1, applied1, status1 = _seed_and_status(sc1)
    seed2, requested2, applied2, status2 = _seed_and_status(sc2)

    return {
        "schema_version": "pommerman_pairing_manifest_v1",
        "game": "pommerman_1v1",
        "regime": "A00",
        "tournament": "smoke_test",
        "seat_swap_policy": "same_pair_two_legs_A_left_B_right_then_A_right_B_left",
        "scorecard_policy": "raw_per_match_scorecard; pair-level aggregation is post-analysis",
        "pairs": [
            {
                "pair_id": f"{agent_a}__vs__{agent_b}",
                "agent_A": agent_a,
                "agent_B": agent_b,
                "background_agents": ["dummy2", "dummy3"],
                "legs": [
                    {
                        "leg": 1,
                        "round_idx": 1,
                        "agent_A_seat": "left",
                        "agent_B_seat": "right",
                        "result_path": "logs/round_1/scorecard.json",
                        "arena_result_path": "logs/round_1/arena_result_match_a.json",
                        "seed": seed1,
                        "requested_seed": requested1,
                        "applied_seed": applied1,
                        "seed_control_status": status1,
                    },
                    {
                        "leg": 2,
                        "round_idx": 2,
                        "agent_A_seat": "right",
                        "agent_B_seat": "left",
                        "result_path": "logs/round_2/scorecard.json",
                        "arena_result_path": "logs/round_2/arena_result_match_a.json",
                        "seed": seed2,
                        "requested_seed": requested2,
                        "applied_seed": applied2,
                        "seed_control_status": status2,
                    },
                ],
            }
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--logs-root", default="logs")
    parser.add_argument("--output", default="logs/pairing_manifest.json")
    args = parser.parse_args()

    logs_root = Path(args.logs_root).resolve()
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    manifest = build_manifest(logs_root)
    output_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote pairing manifest: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

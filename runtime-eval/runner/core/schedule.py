from __future__ import annotations

from dataclasses import dataclass

from runner.core.config import ODD_MODEL_COUNT_ERROR


BYE_AGENT_ID = "__BYE__"


@dataclass(frozen=True)
class ScheduledMatch:
    cycle: int
    round_idx: int
    match_idx: int
    pair_id: str
    agent_A: str
    agent_B: str
    left_agent: str
    right_agent: str
    agent_A_seat: str
    agent_B_seat: str
    encounter_index: int
    reverse_of_round: int | None
    reverse_of_match: int | None


def canonical_pair(a: str, b: str) -> tuple[str, str]:
    x = sorted([a, b])
    return x[0], x[1]


def _round_robin_rounds(entries: list[str]) -> list[list[tuple[str, str]]]:
    order = list(entries)
    rounds: list[list[tuple[str, str]]] = []
    for _ in range(len(order) - 1):
        half = len(order) // 2
        left_half = order[:half]
        right_half = list(reversed(order[half:]))
        rounds.append(list(zip(left_half, right_half)))
        order = [order[0], order[-1], *order[1:-1]]
    return rounds


def build_double_round_robin(agent_ids: list[str], *, num_rounds: int | None = None) -> dict:
    if len(agent_ids) < 2:
        raise ValueError("at least two agents required")
    if len(set(agent_ids)) != len(agent_ids):
        raise ValueError("agent ids must be unique")
    if len(agent_ids) % 2 == 1:
        raise ValueError(ODD_MODEL_COUNT_ERROR)

    entries = list(agent_ids)
    rounds_per_cycle = len(entries) - 1
    matches_per_round = len(entries) // 2
    full_rounds = _round_robin_rounds(entries)
    rounds: list[dict] = []
    pairs: dict[str, dict] = {}
    pair_order_by_cycle: dict[int, list[str]] = {1: [], 2: []}
    encounter_index_by_pair: dict[str, int] = {}
    match_lookup: dict[tuple[int, str], tuple[int, int]] = {}

    for cycle, cycle_rounds in [(1, full_rounds), (2, [[(r, l) for (l, r) in round_pairs] for round_pairs in full_rounds])]:
        for cycle_round_offset, round_pairs in enumerate(cycle_rounds, start=1):
            round_idx = cycle_round_offset if cycle == 1 else rounds_per_cycle + cycle_round_offset
            matches: list[dict] = []
            for match_idx, (left, right) in enumerate(round_pairs, start=1):
                agent_a, agent_b = canonical_pair(left, right)
                pair_id = f"{agent_a}__vs__{agent_b}"
                encounter_index = encounter_index_by_pair.get(pair_id, 0) + 1
                encounter_index_by_pair[pair_id] = encounter_index
                reverse_ref = match_lookup.get((1 if encounter_index == 2 else 2, pair_id))
                reverse_of_round = reverse_ref[0] if reverse_ref else None
                reverse_of_match = reverse_ref[1] if reverse_ref else None
                rec = {
                    "cycle": cycle,
                    "round_idx": round_idx,
                    "match_idx": match_idx,
                    "pair_id": pair_id,
                    "agent_A": agent_a,
                    "agent_B": agent_b,
                    "left_agent": left,
                    "right_agent": right,
                    "agent_A_seat": "left" if cycle == 1 else "right",
                    "agent_B_seat": "right" if cycle == 1 else "left",
                    "encounter_index": encounter_index,
                    "reverse_of_round": reverse_of_round,
                    "reverse_of_match": reverse_of_match,
                    "schedule_mode": "double_round_robin",
                    "match_legs": "single",
                    "num_agents": len(entries),
                    "full_double_rr_rounds": rounds_per_cycle * 2,
                    "emitted_rounds": num_rounds if num_rounds is not None else rounds_per_cycle * 2,
                    "complete_double_round_robin": (num_rounds is None or num_rounds >= rounds_per_cycle * 2),
                }
                matches.append(rec)
                match_lookup[(cycle, pair_id)] = (round_idx, match_idx)
                pairs.setdefault(
                    pair_id,
                    {
                        "pair_id": pair_id,
                        "agent_A": agent_a,
                        "agent_B": agent_b,
                        "legs": [],
                    },
                )["legs"].append(
                    {
                        "cycle": cycle,
                        "round_idx": round_idx,
                        "match_idx": match_idx,
                        "agent_A_seat": rec["agent_A_seat"],
                        "agent_B_seat": rec["agent_B_seat"],
                        "encounter_index": encounter_index,
                        "reverse_of_round": reverse_of_round,
                        "reverse_of_match": reverse_of_match,
                    }
                )
                pair_order_by_cycle[cycle].append(pair_id)
            rounds.append({"round_idx": round_idx, "cycle": cycle, "matches": matches})

    emitted_rounds = rounds[: num_rounds] if num_rounds is not None else rounds
    emitted_pairs = {
        pair_id: {
            "pair_id": pair_id,
            "agent_A": pair["agent_A"],
            "agent_B": pair["agent_B"],
            "legs": [leg for leg in pair["legs"] if num_rounds is None or leg["round_idx"] <= num_rounds],
        }
        for pair_id, pair in pairs.items()
    }
    return {
        "agent_ids": list(agent_ids),
        "num_agents": len(agent_ids),
        "rounds_per_cycle": rounds_per_cycle,
        "full_double_rr_rounds": rounds_per_cycle * 2,
        "matches_per_round": matches_per_round,
        "total_matches": len(entries) * (len(entries) - 1),
        "canonical_pairs_count": (len(entries) * (len(entries) - 1)) // 2,
        "rounds": emitted_rounds,
        "pairs": [emitted_pairs[k] for k in sorted(emitted_pairs)],
        "pair_order_by_cycle": pair_order_by_cycle,
        "is_odd": False,
        "schedule_mode": "double_round_robin",
        "match_legs": "single",
        "emitted_rounds": len(emitted_rounds),
        "complete_double_round_robin": num_rounds is None or num_rounds >= rounds_per_cycle * 2,
    }

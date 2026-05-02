from __future__ import annotations

from dataclasses import dataclass


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


def canonical_pair(a: str, b: str) -> tuple[str, str]:
    x = sorted([a, b])
    return x[0], x[1]


def build_two_cycle_schedule(agent_ids: list[str]) -> dict:
    if len(agent_ids) < 2:
        raise ValueError("at least two agents required")
    if len(set(agent_ids)) != len(agent_ids):
        raise ValueError("agent ids must be unique")

    entries = list(agent_ids)
    is_odd = len(entries) % 2 == 1
    if is_odd:
        entries = [*entries, BYE_AGENT_ID]

    rounds_per_cycle = len(entries) - 1
    matches_per_round = len(entries) // 2
    order = list(entries)
    cycle1_raw: list[list[tuple[str, str]]] = []
    for _ in range(rounds_per_cycle):
        half = len(order) // 2
        left_half = order[:half]
        right_half = list(reversed(order[half:]))
        cycle1_raw.append(list(zip(left_half, right_half)))
        order = [order[0], order[-1], *order[1:-1]]
    cycle2_raw = [[(r, l) for (l, r) in round_pairs] for round_pairs in cycle1_raw]

    rounds: list[dict] = []
    pairs: dict[str, dict] = {}
    cycle_1_pair_order: list[str] = []
    cycle_2_pair_order: list[str] = []
    byes_by_cycle: dict[int, dict[str, int]] = {1: {}, 2: {}}

    for round_idx, round_pairs in enumerate([*cycle1_raw, *cycle2_raw], start=1):
        cycle = 1 if round_idx <= rounds_per_cycle else 2
        matches: list[dict] = []
        bye_agent: str | None = None
        match_idx = 0
        for left, right in round_pairs:
            if BYE_AGENT_ID in {left, right}:
                bye_agent = right if left == BYE_AGENT_ID else left
                continue
            match_idx += 1
            agent_a, agent_b = canonical_pair(left, right)
            pair_id = f"{agent_a}__vs__{agent_b}"
            agent_a_seat = "left" if cycle == 1 else "right"
            agent_b_seat = "right" if cycle == 1 else "left"
            rec = {
                "cycle": cycle,
                "round_idx": round_idx,
                "match_idx": match_idx,
                "pair_id": pair_id,
                "agent_A": agent_a,
                "agent_B": agent_b,
                "left_agent": left,
                "right_agent": right,
                "agent_A_seat": agent_a_seat,
                "agent_B_seat": agent_b_seat,
            }
            matches.append(rec)
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
                    "agent_A_seat": agent_a_seat,
                    "agent_B_seat": agent_b_seat,
                }
            )
            if cycle == 1:
                cycle_1_pair_order.append(pair_id)
            else:
                cycle_2_pair_order.append(pair_id)

        if bye_agent is not None:
            byes_by_cycle[cycle][bye_agent] = byes_by_cycle[cycle].get(bye_agent, 0) + 1
        rounds.append(
            {
                "round_idx": round_idx,
                "cycle": cycle,
                "matches": matches,
                "bye_agent": bye_agent,
            }
        )

    return {
        "agent_ids": list(agent_ids),
        "num_agents": len(agent_ids),
        "rounds_per_cycle": rounds_per_cycle if not is_odd else len(agent_ids),
        "total_rounds": rounds_per_cycle * 2 if not is_odd else len(agent_ids) * 2,
        "matches_per_round": (len(agent_ids) // 2),
        "total_matches": len(agent_ids) * (len(agent_ids) - 1),
        "canonical_pairs_count": (len(agent_ids) * (len(agent_ids) - 1)) // 2,
        "rounds": rounds,
        "pairs": [pairs[k] for k in sorted(pairs)],
        "cycle_1_pair_order": cycle_1_pair_order,
        "cycle_2_pair_order": cycle_2_pair_order,
        "byes_by_cycle": byes_by_cycle,
        "is_odd": is_odd,
    }

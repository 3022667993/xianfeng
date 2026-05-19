from __future__ import annotations

from typing import Any


SEAT_LABELS = {
    0: "left",
    1: "right",
    2: "dummy2",
    3: "dummy3",
}


def _environment_winners(payload: dict[str, Any]) -> list[int]:
    info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
    winners = info.get("winners") if isinstance(info, dict) else None
    if not isinstance(winners, list):
        return []
    out: list[int] = []
    for value in winners:
        try:
            seat = int(value)
        except Exception:
            continue
        if seat in SEAT_LABELS:
            out.append(seat)
    return out


def classify_pommerman_result(
    payload: dict[str, Any],
    *,
    max_steps: int = 800,
    arena_fallback: bool | None = None,
) -> dict[str, Any]:
    environment_winners = _environment_winners(payload)
    environment_winner_labels = [SEAT_LABELS[seat] for seat in environment_winners]
    left_right_winner = payload.get("left_right_winner")
    steps = payload.get("steps")
    reward = payload.get("reward")
    done = payload.get("done")
    fallback = bool(arena_fallback) if arena_fallback is not None else bool(payload.get("arena_fallback_or_invalid"))
    if arena_fallback is None and not fallback:
        fallback = bool(payload.get("arena_fallback"))
    if arena_fallback is None and not fallback:
        fallback = (
            left_right_winner == "draw"
            and steps == 0
            and done is False
            and reward == [0, 0, 0, 0]
            and not environment_winners
        )

    if left_right_winner == "left":
        submitted_pair_outcome = "left_win"
        draw_type = None
    elif left_right_winner == "right":
        submitted_pair_outcome = "right_win"
        draw_type = None
    elif fallback:
        submitted_pair_outcome = "arena_fallback_or_invalid"
        draw_type = "arena_fallback_or_invalid"
    elif left_right_winner == "draw":
        winner_set = set(environment_winners)
        has_dummy_winner = bool(winner_set & {2, 3})
        has_only_dummy_winners = bool(winner_set) and winner_set <= {2, 3}
        if has_only_dummy_winners:
            submitted_pair_outcome = "both_submitted_agents_lost_to_dummy"
            draw_type = "both_lost_to_dummy"
        elif isinstance(steps, int) and steps >= int(max_steps) and not has_dummy_winner:
            submitted_pair_outcome = "timeout_draw"
            draw_type = "timeout_draw"
        elif {0, 1}.issubset(winner_set):
            submitted_pair_outcome = "submitted_agents_tied_with_environment_win"
            draw_type = "submitted_agents_tied"
        else:
            submitted_pair_outcome = "unknown_draw"
            draw_type = "unknown_draw"
    else:
        submitted_pair_outcome = "arena_fallback_or_invalid" if fallback else "unknown_draw"
        draw_type = "arena_fallback_or_invalid" if fallback else "unknown_draw"

    return {
        "environment_winners": environment_winners,
        "environment_winner_labels": environment_winner_labels,
        "submitted_pair_outcome": submitted_pair_outcome,
        "draw_type": draw_type,
    }


def result_classification_fields(payload: dict[str, Any], *, max_steps: int = 800) -> dict[str, Any]:
    return classify_pommerman_result(payload, max_steps=max_steps)


def format_submitted_pair_outcome(payload: dict[str, Any]) -> str:
    winner = payload.get("left_right_winner")
    outcome = payload.get("submitted_pair_outcome")
    draw_type = payload.get("draw_type")
    labels = payload.get("environment_winner_labels")
    if winner != "draw":
        return str(winner)
    if outcome == "both_submitted_agents_lost_to_dummy":
        label_text = ", ".join(str(x) for x in labels) if isinstance(labels, list) and labels else "dummy"
        return f"draw (both submitted agents lost to {label_text})"
    if outcome == "submitted_agents_tied_with_environment_win":
        label_text = ", ".join(str(x) for x in labels) if isinstance(labels, list) and labels else "environment winner"
        return f"draw (submitted agents tied; environment winner: {label_text})"
    if draw_type == "timeout_draw":
        return "draw (timeout)"
    if draw_type == "arena_fallback_or_invalid":
        return "draw (arena fallback or invalid)"
    if draw_type:
        return f"draw ({draw_type})"
    return "draw"

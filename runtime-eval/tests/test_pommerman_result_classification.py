from runner.core.pommerman_results import classify_pommerman_result, format_submitted_pair_outcome


def test_classifies_dummy_winner_draw_as_both_submitted_lost():
    payload = {
        "left_right_winner": "draw",
        "steps": 37,
        "done": True,
        "reward": [-1, -1, 1, -1],
        "info": {"winners": [2]},
    }

    fields = classify_pommerman_result(payload)

    assert fields["environment_winners"] == [2]
    assert fields["environment_winner_labels"] == ["dummy2"]
    assert fields["submitted_pair_outcome"] == "both_submitted_agents_lost_to_dummy"
    assert fields["draw_type"] == "both_lost_to_dummy"
    assert format_submitted_pair_outcome({**payload, **fields}) == "draw (both submitted agents lost to dummy2)"


def test_classifies_timeout_draw_without_dummy_winner():
    fields = classify_pommerman_result(
        {
            "left_right_winner": "draw",
            "steps": 800,
            "done": False,
            "reward": [-1, -1, -1, -1],
            "info": {"winners": []},
        }
    )

    assert fields["environment_winners"] == []
    assert fields["environment_winner_labels"] == []
    assert fields["submitted_pair_outcome"] == "timeout_draw"
    assert fields["draw_type"] == "timeout_draw"


def test_classifies_left_and_right_wins_without_draw_type():
    left_fields = classify_pommerman_result(
        {"left_right_winner": "left", "steps": 42, "reward": [1, -1, -1, -1], "info": {"winners": [0]}}
    )
    right_fields = classify_pommerman_result(
        {"left_right_winner": "right", "steps": 42, "reward": [-1, 1, -1, -1], "info": {"winners": [1]}}
    )

    assert left_fields["submitted_pair_outcome"] == "left_win"
    assert left_fields["draw_type"] is None
    assert right_fields["submitted_pair_outcome"] == "right_win"
    assert right_fields["draw_type"] is None


def test_classifies_arena_fallback_or_invalid():
    fields = classify_pommerman_result(
        {
            "left_right_winner": "draw",
            "steps": 0,
            "done": False,
            "reward": [0, 0, 0, 0],
            "info": {"winners": []},
            "arena_fallback_or_invalid": True,
        }
    )

    assert fields["submitted_pair_outcome"] == "arena_fallback_or_invalid"
    assert fields["draw_type"] == "arena_fallback_or_invalid"

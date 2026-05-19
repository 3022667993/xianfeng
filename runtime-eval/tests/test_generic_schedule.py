import pytest

from runner.core.schedule import build_double_round_robin
from runner.core.config import ODD_MODEL_COUNT_ERROR


def _ids(n: int) -> list[str]:
    return [f"a{i}" for i in range(1, n + 1)]


def _check_even(n: int):
    s = build_double_round_robin(_ids(n))
    assert s["total_matches"] == n * (n - 1)
    assert s["canonical_pairs_count"] == (n * (n - 1)) // 2
    assert s["full_double_rr_rounds"] == 2 * (n - 1)
    assert s["matches_per_round"] == n // 2
    assert s["rounds_per_cycle"] == n - 1
    assert s["emitted_rounds"] == 2 * (n - 1)
    for r in s["rounds"]:
        seen = []
        for m in r["matches"]:
            seen.extend([m["left_agent"], m["right_agent"]])
        assert len(set(seen)) == n
        assert all(seen.count(x) == 1 for x in set(seen))


def test_generic_schedule_even_8_agents():
    _check_even(8)


def test_generic_schedule_even_10_agents():
    _check_even(10)


def test_generic_schedule_even_12_agents():
    _check_even(12)


def test_prefix_schedule_marks_incomplete():
    s = build_double_round_robin(_ids(6), num_rounds=3)
    assert s["emitted_rounds"] == 3
    assert s["complete_double_round_robin"] is False
    assert len(s["rounds"]) == 3


def test_odd_agents_rejected():
    with pytest.raises(ValueError, match=ODD_MODEL_COUNT_ERROR):
        build_double_round_robin(_ids(13))

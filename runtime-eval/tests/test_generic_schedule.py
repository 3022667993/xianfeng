from runner.core.schedule import BYE_AGENT_ID, build_two_cycle_schedule


def _ids(n: int) -> list[str]:
    return [f"a{i}" for i in range(1, n + 1)]


def _check_even(n: int):
    s = build_two_cycle_schedule(_ids(n))
    assert s["total_matches"] == n * (n - 1)
    assert s["canonical_pairs_count"] == (n * (n - 1)) // 2
    assert s["total_rounds"] == 2 * (n - 1)
    assert s["matches_per_round"] == n // 2
    assert len(s["cycle_1_pair_order"]) == (n * (n - 1)) // 2
    assert s["cycle_1_pair_order"] == s["cycle_2_pair_order"]
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


def test_generic_schedule_odd_13_agents_with_byes():
    n = 13
    s = build_two_cycle_schedule(_ids(n))
    assert s["total_matches"] == n * (n - 1)
    assert s["canonical_pairs_count"] == (n * (n - 1)) // 2
    assert s["total_rounds"] == 2 * n
    assert s["matches_per_round"] == n // 2
    assert s["cycle_1_pair_order"] == s["cycle_2_pair_order"]
    for cycle in [1, 2]:
        bye_counts = s["byes_by_cycle"][cycle]
        assert set(bye_counts.keys()) == set(_ids(n))
        assert all(v == 1 for v in bye_counts.values())

    for r in s["rounds"]:
        bye_agent = r["bye_agent"]
        assert bye_agent in _ids(n)
        seen = []
        for m in r["matches"]:
            assert m["left_agent"] != BYE_AGENT_ID
            assert m["right_agent"] != BYE_AGENT_ID
            seen.extend([m["left_agent"], m["right_agent"]])
        assert len(set(seen)) == n - 1
        assert bye_agent not in seen


def test_cycle2_repeats_cycle1_order_for_all_supported_sizes():
    for n in [6, 8, 10, 12, 13]:
        s = build_two_cycle_schedule(_ids(n))
        assert s["cycle_1_pair_order"] == s["cycle_2_pair_order"]


def test_total_matches_equals_n_times_n_minus_1_for_all_supported_sizes():
    for n in [6, 8, 10, 12, 13]:
        s = build_two_cycle_schedule(_ids(n))
        assert s["total_matches"] == n * (n - 1)


def test_no_bye_agent_artifacts_are_created():
    s = build_two_cycle_schedule(_ids(13))
    for r in s["rounds"]:
        for m in r["matches"]:
            assert m["left_agent"] != BYE_AGENT_ID
            assert m["right_agent"] != BYE_AGENT_ID

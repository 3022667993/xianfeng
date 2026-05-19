import pytest

from runner.core.config import ODD_MODEL_COUNT_ERROR, load_yaml, resolve_tournament_counts
from runner.main import _assign_initial_strategy_profiles
from runner.core.schedule import build_double_round_robin


def _models(n: int) -> list[dict]:
    return [
        {
            "id": f"m{i}",
            "agent_id": f"a{i}",
            "provider_model": f"relay/model-{i}",
            "executor": "openclaw-minimal",
            "stratum": ["light", "mid", "strong"][i % 3],
        }
        for i in range(1, n + 1)
    ]


def _prefix_cfg() -> dict:
    return {
        "name": "prefix",
        "game": "pommerman_1v1",
        "num_models": "auto",
        "num_rounds": 3,
        "matches_per_round": "auto",
        "revision_rounds": "auto_before_final",
        "revision_subset_size": "all",
        "schedule_mode": "double_round_robin",
        "match_legs": "single",
    }


def _full_cfg() -> dict:
    return {
        **_prefix_cfg(),
        "name": "full",
        "num_rounds": "auto_full_double_rr",
    }


def test_current_six_model_auto_configs_resolve():
    models = load_yaml("configs/models/openclaw_relay_current.yaml")["models"]
    prefix = resolve_tournament_counts(_prefix_cfg(), models)
    full = resolve_tournament_counts(_full_cfg(), models)

    assert prefix["num_models"] == 6
    assert prefix["matches_per_round"] == 3
    assert prefix["num_rounds"] == 3
    assert prefix["revision_subset_size"] == 6
    assert prefix["revision_rounds"] == [1, 2]
    assert full["num_rounds"] == 10
    assert full["matches_per_round"] == 3


def test_eight_model_prefix_and_full_configs_resolve():
    models = _models(8)
    prefix = resolve_tournament_counts(_prefix_cfg(), models)
    full = resolve_tournament_counts(_full_cfg(), models)
    schedule = build_double_round_robin([m["agent_id"] for m in models], num_rounds=full["num_rounds"])

    assert prefix["num_models"] == 8
    assert prefix["matches_per_round"] == 4
    assert prefix["num_rounds"] == 3
    assert prefix["revision_subset_size"] == 8
    assert prefix["revision_rounds"] == [1, 2]
    assert full["num_rounds"] == 14
    assert full["matches_per_round"] == 4
    assert schedule["total_matches"] == 56


def test_ten_model_full_config_resolves():
    models = _models(10)
    full = resolve_tournament_counts(_full_cfg(), models)
    schedule = build_double_round_robin([m["agent_id"] for m in models], num_rounds=full["num_rounds"])

    assert full["num_models"] == 10
    assert full["matches_per_round"] == 5
    assert full["num_rounds"] == 18
    assert full["revision_subset_size"] == 10
    assert full["revision_rounds"] == list(range(1, 18))
    assert schedule["total_matches"] == 90


def test_odd_model_count_fails_with_bye_error():
    with pytest.raises(ValueError, match=ODD_MODEL_COUNT_ERROR):
        resolve_tournament_counts(_prefix_cfg(), _models(7))
    with pytest.raises(ValueError, match=ODD_MODEL_COUNT_ERROR):
        build_double_round_robin([m["agent_id"] for m in _models(7)])


def test_initial_strategy_profile_assignment_is_dynamic_and_diverse():
    six = _models(6)
    eight = _models(8)

    six_first = _assign_initial_strategy_profiles(six)
    six_second = _assign_initial_strategy_profiles(six)
    eight_profiles = _assign_initial_strategy_profiles(eight)

    assert six_first == six_second
    assert len(set(six_first.values())) == 6
    assert len(eight_profiles) == 8
    assert len(set(eight_profiles.values())) > 1
    assert len(set(eight_profiles.values())) < 8

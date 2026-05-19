from runner.core.config import load_yaml, resolve_tournament_counts


def test_initial_synthesis_3round_neutral_double_rr_smoke_config_loads():
    cfg = load_yaml(
        "configs/tournaments/"
        "pommerman_gptv16_a00_openclaw_initial_synthesis_3round_neutral_double_rr_smoke.yaml"
    )
    models = load_yaml("configs/models/openclaw_relay_current.yaml")["models"]
    resolved = resolve_tournament_counts(cfg, models)
    assert cfg["name"] == "pommerman_gptv16_a00_openclaw_initial_synthesis_3round_neutral_double_rr_smoke"
    assert cfg["num_models"] == "auto"
    assert cfg["matches_per_round"] == "auto"
    assert cfg["revision_rounds"] == "auto_before_final"
    assert cfg["revision_subset_size"] == "all"
    assert resolved["num_models"] == 6
    assert resolved["num_rounds"] == 3
    assert resolved["matches_per_round"] == 3
    assert resolved["revision_rounds"] == [1, 2]
    assert resolved["revision_subset_size"] == 6
    assert cfg["schedule_mode"] == "double_round_robin"
    assert cfg["match_legs"] == "single"
    assert cfg["feedback_package_variant"] == "codeclash_v4"
    assert cfg["initial_synthesis_prompt_variant"] == "neutral"
    assert cfg["revision_prompt_variant"] == "neutral"


def test_initial_synthesis_10round_neutral_double_rr_config_loads():
    cfg = load_yaml(
        "configs/tournaments/"
        "pommerman_gptv16_a00_openclaw_initial_synthesis_10round_neutral_double_rr.yaml"
    )
    assert cfg["name"] == "pommerman_gptv16_a00_openclaw_initial_synthesis_10round_neutral_double_rr"
    assert cfg["num_rounds"] == 10
    assert cfg["matches_per_round"] == 3
    assert cfg["revision_rounds"] == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert cfg["schedule_mode"] == "double_round_robin"
    assert cfg["match_legs"] == "single"
    assert cfg["feedback_package_variant"] == "codeclash_v4"


def test_initial_synthesis_full_neutral_double_rr_config_resolves():
    cfg = load_yaml(
        "configs/tournaments/"
        "pommerman_gptv16_a00_openclaw_initial_synthesis_full_neutral_double_rr.yaml"
    )
    models = load_yaml("configs/models/openclaw_relay_current.yaml")["models"]
    resolved = resolve_tournament_counts(cfg, models)

    assert cfg["name"] == "pommerman_gptv16_a00_openclaw_initial_synthesis_full_neutral_double_rr"
    assert cfg["num_models"] == "auto"
    assert cfg["num_rounds"] == "auto_full_double_rr"
    assert cfg["matches_per_round"] == "auto"
    assert cfg["revision_rounds"] == "auto_before_final"
    assert cfg["revision_subset_size"] == "all"
    assert resolved["num_models"] == 6
    assert resolved["num_rounds"] == 10
    assert resolved["matches_per_round"] == 3
    assert resolved["revision_rounds"] == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert resolved["revision_subset_size"] == 6
    assert resolved["schedule_mode"] == "double_round_robin"
    assert resolved["match_legs"] == "single"
    assert resolved["feedback_package_variant"] == "codeclash_v4"

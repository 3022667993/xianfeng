from runner.core.config import load_yaml


def test_initial_synthesis_3round_neutral_double_rr_smoke_config_loads():
    cfg = load_yaml(
        "configs/tournaments/"
        "pommerman_gptv16_a00_openclaw_initial_synthesis_3round_neutral_double_rr_smoke.yaml"
    )
    assert cfg["name"] == "pommerman_gptv16_a00_openclaw_initial_synthesis_3round_neutral_double_rr_smoke"
    assert cfg["num_rounds"] == 3
    assert cfg["matches_per_round"] == 3
    assert cfg["schedule_mode"] == "double_round_robin"
    assert cfg["match_legs"] == "single"
    assert cfg["feedback_package_variant"] == "codeclash_v3"
    assert cfg["revision_rounds"] == [1, 2]
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
    assert cfg["feedback_package_variant"] == "codeclash_v3"

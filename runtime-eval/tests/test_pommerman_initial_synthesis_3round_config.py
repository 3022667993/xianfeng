from runner.core.config import load_yaml


def test_initial_synthesis_3round_config_loads():
    cfg = load_yaml("configs/tournaments/pommerman_gptv16_a00_openclaw_initial_synthesis_3round_smoke.yaml")
    assert cfg["openclaw_adaptive_smoke"] is True
    assert cfg["initial_synthesis"] is True
    assert cfg["real_openclaw_initial_synthesis"] is True
    assert cfg["initial_synthesis_executor"] == "openclaw-minimal"
    assert cfg["require_all_agents_initial_synthesized"] is True
    assert cfg["require_effective_initial_submission_change"] is True
    assert cfg["initial_synthesis_retry_on_noop"] == 1
    assert cfg["initial_synthesis_retry_on_route_unknown"] == 1
    assert cfg["initial_synthesis_retry_on_timeout"] == 1
    assert cfg["initial_synthesis_prompt_variant"] == "anti_draw_coached"
    assert cfg["require_effective_submission_change"] is True
    assert cfg["revision_retry_on_noop"] == 1
    assert cfg["revision_retry_on_route_unknown"] == 1
    assert cfg["revision_retry_on_timeout"] == 1
    assert cfg["revision_prompt_variant"] == "anti_draw_coached"


def test_initial_synthesis_3round_neutral_config_loads():
    cfg = load_yaml("configs/tournaments/pommerman_gptv16_a00_openclaw_initial_synthesis_3round_neutral_smoke.yaml")
    assert cfg["openclaw_adaptive_smoke"] is True
    assert cfg["initial_synthesis"] is True
    assert cfg["real_openclaw_initial_synthesis"] is True
    assert cfg["initial_synthesis_executor"] == "openclaw-minimal"
    assert cfg["require_all_agents_initial_synthesized"] is True
    assert cfg["require_effective_initial_submission_change"] is True
    assert cfg["initial_synthesis_retry_on_noop"] == 1
    assert cfg["initial_synthesis_retry_on_route_unknown"] == 1
    assert cfg["initial_synthesis_retry_on_timeout"] == 1
    assert cfg["initial_synthesis_prompt_variant"] == "neutral"
    assert cfg["require_effective_submission_change"] is True
    assert cfg["revision_retry_on_noop"] == 1
    assert cfg["revision_retry_on_route_unknown"] == 1
    assert cfg["revision_retry_on_timeout"] == 1
    assert cfg["revision_prompt_variant"] == "neutral"


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

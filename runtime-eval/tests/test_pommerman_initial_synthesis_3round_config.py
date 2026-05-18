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
    assert cfg["initial_synthesis_prompt_variant"] == "anti_draw_coached"
    assert cfg["require_effective_submission_change"] is True
    assert cfg["revision_retry_on_noop"] == 1
    assert cfg["revision_retry_on_route_unknown"] == 1
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
    assert cfg["initial_synthesis_prompt_variant"] == "neutral"
    assert cfg["require_effective_submission_change"] is True
    assert cfg["revision_retry_on_noop"] == 1
    assert cfg["revision_retry_on_route_unknown"] == 1
    assert cfg["revision_prompt_variant"] == "neutral"

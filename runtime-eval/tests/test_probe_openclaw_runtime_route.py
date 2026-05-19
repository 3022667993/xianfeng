import json
from pathlib import Path

from scripts import probe_openclaw_runtime_route as probe


def test_probe_writes_log_and_handles_unknown_model(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    seed_calls = []

    def fake_run_openclaw_agent(
        message: str,
        *,
        agent_id: str,
        provider_model: str | None = None,
        session_id: str | None = None,
        session_state_dir=None,
        session_config_path=None,
    ):
        _ = message
        _ = agent_id
        _ = session_id
        _ = session_state_dir
        _ = session_config_path
        assert provider_model == "relay/qwen3.5-plus"
        return None, "", "FailoverError: Unknown model: relay/qwen3.5-plus", 1

    def fake_seed_isolated_openclaw_state(*, isolated_state_dir, agent_id):
        seed_calls.append((isolated_state_dir, agent_id))
        isolated_state_dir.mkdir(parents=True, exist_ok=True)
        cfg = isolated_state_dir / "openclaw.json"
        cfg.write_text("{}", encoding="utf-8")
        return cfg, []

    monkeypatch.setattr(probe.ocm, "_run_openclaw_agent", fake_run_openclaw_agent)
    monkeypatch.setattr(probe.ocm, "_seed_isolated_openclaw_state", fake_seed_isolated_openclaw_state)
    result = probe.probe_runtime_route("relay/qwen3.5-plus")
    out = Path("logs/openclaw_runtime_route_probe.json")
    assert out.exists()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["requested_provider_model"] == "relay/qwen3.5-plus"
    assert payload["parseable_json"] is False
    assert payload["openclaw_return_code"] == 1
    assert payload["errors"]
    assert "Unknown model: relay/qwen3.5-plus" in payload["stderr_tail"]
    assert payload["openclaw_session_isolated"] is True
    assert payload["openclaw_session_state_dir"].endswith("logs/_runtime_route_probe_tmp/openclaw_home")
    assert payload["openclaw_session_id"].startswith("runtime-eval-probe-")
    assert seed_calls and seed_calls[0][1] == "main"
    assert result["errors"]

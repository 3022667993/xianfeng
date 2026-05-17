import json
from pathlib import Path

from scripts import probe_openclaw_runtime_route as probe


def test_probe_writes_log_and_handles_unknown_model(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    def fake_run_openclaw_agent(message: str, *, agent_id: str, provider_model: str | None = None):
        assert provider_model == "relay/qwen3.5-plus"
        return None, "", "FailoverError: Unknown model: relay/qwen3.5-plus", 1

    monkeypatch.setattr(probe.ocm, "_run_openclaw_agent", fake_run_openclaw_agent)
    result = probe.probe_runtime_route("relay/qwen3.5-plus")
    out = Path("logs/openclaw_runtime_route_probe.json")
    assert out.exists()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["requested_provider_model"] == "relay/qwen3.5-plus"
    assert payload["parseable_json"] is False
    assert payload["openclaw_return_code"] == 1
    assert payload["errors"]
    assert "Unknown model: relay/qwen3.5-plus" in payload["stderr_tail"]
    assert result["errors"]

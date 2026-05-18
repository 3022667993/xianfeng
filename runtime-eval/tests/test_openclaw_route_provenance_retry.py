import json
from pathlib import Path

from runner.main import _extract_openclaw_route_provenance, _route_provenance_verified


def _write_main(path: Path, text: str) -> None:
    p = path / "submission" / "main.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_route_provenance_unknown_with_code_change_is_not_verified():
    ad = {
        "providerRouteStatus": "unknown",
        "actualProvider": None,
        "actualModel": None,
        "fallbackUsed": False,
    }
    status, ap, am, fb = _extract_openclaw_route_provenance(ad)
    assert status == "unknown"
    assert ap is None
    assert am is None
    assert fb is False
    assert _route_provenance_verified(
        provider_route_status=status,
        actual_provider=ap,
        actual_model=am,
        fallback_used=fb,
    ) is False


def test_route_provenance_unknown_then_matched_allows_second_attempt_only(tmp_path):
    initial_base = tmp_path / "base"
    attempt1 = tmp_path / "post_attempt1"
    attempt2 = tmp_path / "post_attempt2"
    _write_main(initial_base, "AGGRESSION = 0\n")
    _write_main(attempt1, "AGGRESSION = 1\n")
    _write_main(attempt2, "AGGRESSION = 1\n")

    ad1 = {"providerRouteStatus": "unknown", "actualProvider": None, "actualModel": None, "fallbackUsed": False}
    ad2 = {"providerRouteStatus": "matched", "actualProvider": "relay", "actualModel": "qwen3.5-plus", "fallbackUsed": False}
    s1, p1, m1, f1 = _extract_openclaw_route_provenance(ad1)
    s2, p2, m2, f2 = _extract_openclaw_route_provenance(ad2)
    assert _route_provenance_verified(provider_route_status=s1, actual_provider=p1, actual_model=m1, fallback_used=f1) is False
    assert _route_provenance_verified(provider_route_status=s2, actual_provider=p2, actual_model=m2, fallback_used=f2) is True

    before_hash = initial_base.joinpath("submission/main.py").read_text(encoding="utf-8")
    after1_hash = attempt1.joinpath("submission/main.py").read_text(encoding="utf-8")
    after2_hash = attempt2.joinpath("submission/main.py").read_text(encoding="utf-8")
    assert before_hash != after1_hash
    assert before_hash != after2_hash


def test_route_unknown_changed_code_not_propagated_in_initial_manifest(tmp_path):
    manifest = {
        "agents": [
            {
                "agent_id": "a1",
                "initial_synthesis_ok": False,
                "initial_provider_route_status": "unknown",
                "initial_actual_provider": None,
                "initial_actual_model": None,
                "effective_initial_submission_changed": True,
                "initial_failure_reason": "OpenClaw route provenance missing despite code change",
            }
        ]
    }
    p = tmp_path / "logs" / "initial_synthesis_manifest.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(manifest), encoding="utf-8")
    got = json.loads(p.read_text(encoding="utf-8"))
    entry = got["agents"][0]
    assert entry["initial_synthesis_ok"] is False
    assert entry["effective_initial_submission_changed"] is True
    assert "route provenance missing" in entry["initial_failure_reason"]


def test_route_matched_with_changed_code_is_verified():
    ad = {
        "providerRouteStatus": "matched",
        "actualProvider": "relay",
        "actualModel": "gemini-2.5-flash-thinking",
        "fallbackUsed": False,
    }
    status, ap, am, fb = _extract_openclaw_route_provenance(ad)
    assert _route_provenance_verified(
        provider_route_status=status,
        actual_provider=ap,
        actual_model=am,
        fallback_used=fb,
    ) is True

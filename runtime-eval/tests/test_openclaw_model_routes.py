import json
from pathlib import Path

from scripts.audit_openclaw_model_routes import audit_validation_report
from scripts.validate_openclaw_model_routes import _classify_static_provider_model


def test_static_validation_catches_missing_relay_prefix():
    known_refs = {"relay/bailian/deepseek-v4-flash"}
    known, notes, suggested = _classify_static_provider_model(
        "bailian/deepseek-v4-flash", known_refs, "ok"
    )
    assert known == "false"
    assert "likely_match_suggested" in notes
    assert suggested == "relay/bailian/deepseek-v4-flash"


def test_static_validation_passes_known_relay_model():
    known_refs = {"relay/bailian/deepseek-v4-flash"}
    known, notes, suggested = _classify_static_provider_model(
        "relay/bailian/deepseek-v4-flash", known_refs, "ok"
    )
    assert known == "true"
    assert "exact_match" in notes
    assert suggested == "relay/bailian/deepseek-v4-flash"


def test_static_audit_fails_when_catalog_unavailable_for_all(tmp_path):
    p = tmp_path / "report.json"
    _write_report(
        p,
        {
            "schema_version": "openclaw_model_route_validation_v1",
            "mode": "static",
            "catalog_status": "catalog_unavailable:no_refs_discovered",
            "model_count": 2,
            "entries": [
                {
                    "id": "m1",
                    "valid_executor": True,
                    "provider_model_nonempty": True,
                    "static_known": "unknown",
                    "notes": "catalog_unavailable",
                },
                {
                    "id": "m2",
                    "valid_executor": True,
                    "provider_model_nonempty": True,
                    "static_known": "unknown",
                    "notes": "catalog_unavailable",
                },
            ],
        },
    )
    errors, warnings = audit_validation_report(p)
    assert any("catalog unavailable for all entries" in e for e in errors)
    assert warnings


def _write_report(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_real_mode_audit_passes_when_all_matched(tmp_path):
    p = tmp_path / "report.json"
    _write_report(
        p,
        {
            "schema_version": "openclaw_model_route_validation_v1",
            "mode": "real",
            "model_count": 2,
            "entries": [
                {
                    "id": "m1",
                    "valid_executor": True,
                    "provider_model_nonempty": True,
                    "real": {
                        "requested_provider_model": "relay/a",
                        "actual_provider": "relay",
                        "actual_model": "a",
                        "provider_route_status": "matched",
                        "openclaw_returncode": 0,
                        "success": True,
                    },
                },
                {
                    "id": "m2",
                    "valid_executor": True,
                    "provider_model_nonempty": True,
                    "real": {
                        "requested_provider_model": "relay/b",
                        "actual_provider": "relay",
                        "actual_model": "b",
                        "provider_route_status": "matched",
                        "openclaw_returncode": 0,
                        "success": True,
                    },
                },
            ],
        },
    )
    errors, warnings = audit_validation_report(p)
    assert errors == []
    assert warnings == []


def test_real_mode_audit_fails_on_mismatch(tmp_path):
    p = tmp_path / "report.json"
    _write_report(
        p,
        {
            "schema_version": "openclaw_model_route_validation_v1",
            "mode": "real",
            "model_count": 1,
            "entries": [
                {
                    "id": "m1",
                    "valid_executor": True,
                    "provider_model_nonempty": True,
                    "real": {
                        "requested_provider_model": "relay/a",
                        "actual_provider": "relay",
                        "actual_model": "x",
                        "provider_route_status": "mismatch",
                        "openclaw_returncode": 0,
                        "success": False,
                    },
                }
            ],
        },
    )
    errors, _warnings = audit_validation_report(p)
    assert any("provider_route_status=mismatch" in e for e in errors)


def test_real_mode_audit_fails_on_unknown(tmp_path):
    p = tmp_path / "report.json"
    _write_report(
        p,
        {
            "schema_version": "openclaw_model_route_validation_v1",
            "mode": "real",
            "model_count": 1,
            "entries": [
                {
                    "id": "m1",
                    "valid_executor": True,
                    "provider_model_nonempty": True,
                    "real": {
                        "requested_provider_model": "relay/a",
                        "actual_provider": None,
                        "actual_model": None,
                        "provider_route_status": "unknown",
                        "openclaw_returncode": 0,
                        "success": False,
                    },
                }
            ],
        },
    )
    errors, _warnings = audit_validation_report(p)
    assert any("provider_route_status=unknown" in e for e in errors)


def test_real_mode_audit_fails_on_relay_gpt41_fallback(tmp_path):
    p = tmp_path / "report.json"
    _write_report(
        p,
        {
            "schema_version": "openclaw_model_route_validation_v1",
            "mode": "real",
            "model_count": 1,
            "entries": [
                {
                    "id": "m1",
                    "valid_executor": True,
                    "provider_model_nonempty": True,
                    "real": {
                        "requested_provider_model": "relay/bailian/deepseek-v4-flash",
                        "actual_provider": "relay",
                        "actual_model": "gpt-4.1",
                        "provider_route_status": "mismatch",
                        "openclaw_returncode": 0,
                        "success": False,
                    },
                }
            ],
        },
    )
    errors, _warnings = audit_validation_report(p)
    assert any("fallback to relay/gpt-4.1" in e for e in errors)

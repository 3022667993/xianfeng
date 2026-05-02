import json
from pathlib import Path

from scripts.build_pommerman_pairing_manifest import build_manifest
from scripts.audit_pommerman_pairing_manifest import audit_manifest


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_build_manifest_uses_stable_fallback_identities_and_leg_seats(tmp_path):
    logs = tmp_path / "logs"
    _write_json(logs / "round_1" / "metadata.json", {
        "left_model_id": None,
        "left_agent_id": None,
        "right_model_id": None,
        "right_agent_id": None,
    })
    _write_json(
        logs / "round_1" / "scorecard.json",
        {
            "left_score": 1,
            "right_score": 0,
            "seed": None,
            "requested_seed": 1001,
            "applied_seed": None,
            "seed_control_status": "requested_but_not_applied",
        },
    )
    _write_json(
        logs / "round_2" / "scorecard.json",
        {
            "left_score": 0,
            "right_score": 1,
            "seed": None,
            "requested_seed": 1001,
            "applied_seed": None,
            "seed_control_status": "requested_but_not_applied",
        },
    )

    manifest = build_manifest(logs)
    pair = manifest["pairs"][0]

    assert pair["agent_A"] == "smoke_agent_A"
    assert pair["agent_B"] == "smoke_agent_B"
    assert pair["pair_id"] == "smoke_agent_A__vs__smoke_agent_B"
    assert pair["background_agents"] == ["dummy2", "dummy3"]

    leg1, leg2 = pair["legs"]
    assert leg1["leg"] == 1
    assert leg1["agent_A_seat"] == "left"
    assert leg1["agent_B_seat"] == "right"
    assert leg1["seed"] is None
    assert leg1["requested_seed"] == 1001
    assert leg1["applied_seed"] is None
    assert leg1["seed_control_status"] == "requested_but_not_applied"

    assert leg2["leg"] == 2
    assert leg2["agent_A_seat"] == "right"
    assert leg2["agent_B_seat"] == "left"
    assert leg2["seed"] is None
    assert leg2["requested_seed"] == 1001
    assert leg2["applied_seed"] is None
    assert leg2["seed_control_status"] == "requested_but_not_applied"


def test_audit_manifest_passes_and_warns_for_missing_seed(tmp_path):
    logs = tmp_path / "logs"
    (logs / "round_1").mkdir(parents=True)
    (logs / "round_2").mkdir(parents=True)
    (logs / "round_1" / "scorecard.json").write_text("{}", encoding="utf-8")
    (logs / "round_2" / "scorecard.json").write_text("{}", encoding="utf-8")
    (logs / "round_1" / "arena_result_match_a.json").write_text("{}", encoding="utf-8")
    (logs / "round_2" / "arena_result_match_a.json").write_text("{}", encoding="utf-8")

    manifest = {
        "schema_version": "pommerman_pairing_manifest_v1",
        "game": "pommerman_1v1",
        "regime": "A00",
        "tournament": "smoke_test",
        "seat_swap_policy": "same_pair_two_legs_A_left_B_right_then_A_right_B_left",
        "scorecard_policy": "raw_per_match_scorecard; pair-level aggregation is post-analysis",
        "pairs": [
            {
                "pair_id": "smoke_agent_A__vs__smoke_agent_B",
                "agent_A": "smoke_agent_A",
                "agent_B": "smoke_agent_B",
                "background_agents": ["dummy2", "dummy3"],
                "legs": [
                    {
                        "leg": 1,
                        "round_idx": 1,
                        "agent_A_seat": "left",
                        "agent_B_seat": "right",
                        "result_path": "logs/round_1/scorecard.json",
                        "arena_result_path": "logs/round_1/arena_result_match_a.json",
                        "seed": None,
                        "requested_seed": None,
                        "applied_seed": None,
                        "seed_control_status": "not_recorded_in_current_smoke",
                    },
                    {
                        "leg": 2,
                        "round_idx": 2,
                        "agent_A_seat": "right",
                        "agent_B_seat": "left",
                        "result_path": "logs/round_2/scorecard.json",
                        "arena_result_path": "logs/round_2/arena_result_match_a.json",
                        "seed": None,
                        "requested_seed": None,
                        "applied_seed": None,
                        "seed_control_status": "not_recorded_in_current_smoke",
                    },
                ],
            }
        ],
    }
    manifest_path = logs / "pairing_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    errors, warnings = audit_manifest(tmp_path, manifest_path)
    assert errors == []
    assert len(warnings) == 2


def _base_manifest() -> dict:
    return {
        "schema_version": "pommerman_pairing_manifest_v1",
        "game": "pommerman_1v1",
        "regime": "A00",
        "tournament": "smoke_test",
        "seat_swap_policy": "same_pair_two_legs_A_left_B_right_then_A_right_B_left",
        "scorecard_policy": "raw_per_match_scorecard; pair-level aggregation is post-analysis",
        "pairs": [
            {
                "pair_id": "smoke_agent_A__vs__smoke_agent_B",
                "agent_A": "smoke_agent_A",
                "agent_B": "smoke_agent_B",
                "background_agents": ["dummy2", "dummy3"],
                "legs": [
                    {
                        "leg": 1,
                        "round_idx": 1,
                        "agent_A_seat": "left",
                        "agent_B_seat": "right",
                        "result_path": "logs/round_1/scorecard.json",
                        "arena_result_path": "logs/round_1/arena_result_match_a.json",
                        "seed": None,
                        "requested_seed": 1001,
                        "applied_seed": None,
                        "seed_control_status": "requested_but_not_applied",
                    },
                    {
                        "leg": 2,
                        "round_idx": 2,
                        "agent_A_seat": "right",
                        "agent_B_seat": "left",
                        "result_path": "logs/round_2/scorecard.json",
                        "arena_result_path": "logs/round_2/arena_result_match_a.json",
                        "seed": None,
                        "requested_seed": 1001,
                        "applied_seed": None,
                        "seed_control_status": "requested_but_not_applied",
                    },
                ],
            }
        ],
    }


def _write_audit_files(tmp_path: Path, manifest: dict) -> Path:
    logs = tmp_path / "logs"
    (logs / "round_1").mkdir(parents=True)
    (logs / "round_2").mkdir(parents=True)
    (logs / "round_1" / "scorecard.json").write_text("{}", encoding="utf-8")
    (logs / "round_2" / "scorecard.json").write_text("{}", encoding="utf-8")
    (logs / "round_1" / "arena_result_match_a.json").write_text("{}", encoding="utf-8")
    (logs / "round_2" / "arena_result_match_a.json").write_text("{}", encoding="utf-8")
    manifest_path = logs / "pairing_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def test_audit_fails_on_mismatched_requested_seed(tmp_path):
    manifest = _base_manifest()
    manifest["pairs"][0]["legs"][1]["requested_seed"] = 2002
    manifest_path = _write_audit_files(tmp_path, manifest)
    errors, _warnings = audit_manifest(tmp_path, manifest_path)
    assert any("requested_seed mismatch" in e for e in errors)


def test_audit_fails_on_mismatched_non_null_applied_seed(tmp_path):
    manifest = _base_manifest()
    leg1 = manifest["pairs"][0]["legs"][0]
    leg2 = manifest["pairs"][0]["legs"][1]
    for leg, applied in ((leg1, 111), (leg2, 222)):
        leg["seed_control_status"] = "applied"
        leg["requested_seed"] = 1001
        leg["applied_seed"] = applied
        leg["seed"] = applied
    manifest_path = _write_audit_files(tmp_path, manifest)
    errors, _warnings = audit_manifest(tmp_path, manifest_path)
    assert any("applied_seed mismatch" in e for e in errors)


def test_audit_allows_requested_but_not_applied_with_warning(tmp_path):
    manifest = _base_manifest()
    manifest_path = _write_audit_files(tmp_path, manifest)
    errors, warnings = audit_manifest(tmp_path, manifest_path)
    assert errors == []
    assert len(warnings) == 2
    assert all("requested but not applied" in w for w in warnings)

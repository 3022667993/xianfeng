import json
from pathlib import Path
import subprocess

from scripts.audit_pommerman_formal_schedule import audit_manifest
from scripts.build_pommerman_formal_schedule_manifest import build_manifest


def _models_cfg() -> dict:
    return {
        "models": [
            {"id": "m1", "agent_id": "m1", "executor": "openclaw-minimal"},
            {"id": "m2", "agent_id": "m2", "executor": "openclaw-minimal"},
            {"id": "m3", "agent_id": "m3", "executor": "openclaw-minimal"},
            {"id": "m4", "agent_id": "m4", "executor": "openclaw-minimal"},
            {"id": "m5", "agent_id": "m5", "executor": "openclaw-minimal"},
            {"id": "m6", "agent_id": "m6", "executor": "openclaw-minimal"},
        ]
    }


def _tournament_cfg() -> dict:
    return {
        "name": "sched_smoke",
        "num_rounds": 10,
        "matches_per_round": 3,
        "seed": 1001,
    }


def _write_manifest(tmp_path, manifest: dict):
    logs = tmp_path / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    path = logs / "pommerman_formal_schedule_manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_builder_counts_and_policy():
    manifest = build_manifest(_models_cfg(), _tournament_cfg())
    assert manifest["num_models"] == 6
    assert manifest["total_rounds"] == 10
    assert manifest["total_matches"] == 30
    assert len(manifest["pairs"]) == 15
    assert len(manifest["rounds"]) == 10
    assert manifest["scorecard_policy"] == "raw_per_match_scorecard; pair-level aggregation is post-analysis"


def test_rounds_are_perfect_matchings_and_cycles_align():
    manifest = build_manifest(_models_cfg(), _tournament_cfg())
    models = sorted([m["id"] for m in manifest["models"]])

    cycle1 = []
    cycle2 = []
    for round_entry in manifest["rounds"]:
        seen = []
        for match in round_entry["matches"]:
            seen.extend([match["left_agent"], match["right_agent"]])
            if round_entry["cycle"] == 1:
                cycle1.append(match["pair_id"])
            else:
                cycle2.append(match["pair_id"])
        assert sorted(seen) == models

    assert cycle1 == cycle2


def test_seat_swap_background_and_requested_seed_invariants():
    manifest = build_manifest(_models_cfg(), _tournament_cfg())
    for pair in manifest["pairs"]:
        assert pair["background_agents"] == ["dummy2", "dummy3"]
        assert len(pair["legs"]) == 2
        leg1 = next(x for x in pair["legs"] if x["cycle"] == 1)
        leg2 = next(x for x in pair["legs"] if x["cycle"] == 2)
        assert leg1["agent_A_seat"] == "left"
        assert leg1["agent_B_seat"] == "right"
        assert leg2["agent_A_seat"] == "right"
        assert leg2["agent_B_seat"] == "left"
        assert leg1["planned_seed"] == leg2["planned_seed"]
        assert leg1["seed_control_status"] == "planned_not_executed"
        assert leg2["seed_control_status"] == "planned_not_executed"


def test_audit_fails_on_mismatched_planned_seed(tmp_path):
    manifest = build_manifest(_models_cfg(), _tournament_cfg())
    pair = manifest["pairs"][0]
    pair["legs"][1]["planned_seed"] = pair["legs"][0]["planned_seed"] + 1
    path = _write_manifest(tmp_path, manifest)
    errors, _warnings = audit_manifest(path)
    assert any("planned_seed mismatch" in e for e in errors)


def test_audit_fails_on_mismatched_non_null_applied_seed(tmp_path):
    manifest = build_manifest(_models_cfg(), _tournament_cfg())
    pair = manifest["pairs"][0]
    pair["legs"][0]["seed_control_status"] = "recorded"
    pair["legs"][1]["seed_control_status"] = "recorded"
    pair["legs"][0]["applied_seed"] = 111
    pair["legs"][1]["applied_seed"] = 222
    pair["legs"][0]["seed"] = 111
    pair["legs"][1]["seed"] = 222

    target_pair_id = pair["pair_id"]
    for round_entry in manifest["rounds"]:
        for match in round_entry["matches"]:
            if match["pair_id"] != target_pair_id:
                continue
            if round_entry["cycle"] == 1:
                match["seed_control_status"] = "recorded"
                match["applied_seed"] = 111
                match["seed"] = 111
            else:
                match["seed_control_status"] = "recorded"
                match["applied_seed"] = 222
                match["seed"] = 222

    path = _write_manifest(tmp_path, manifest)
    errors, _warnings = audit_manifest(path)
    assert any("applied_seed mismatch" in e for e in errors)


def test_default_roster_audit_script_passes(tmp_path):
    manifest = tmp_path / "manifest_default.json"
    proc = subprocess.run(
        [
            "python",
            "scripts/audit_pommerman_formal_schedule.py",
            "--manifest",
            str(manifest),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "formal_schedule_audit=PASS" in proc.stdout


def test_deepseek_glm_roster_build_and_audit_passes(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    manifest = tmp_path / "manifest_dsglm.json"
    proc = subprocess.run(
        [
            "python",
            "scripts/audit_pommerman_formal_schedule.py",
            "--manifest",
            str(manifest),
            "--models",
            "configs/models/openclaw_relay_6model_deepseek_glm.yaml",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "formal_schedule_audit=PASS" in proc.stdout

    data = json.loads(manifest.read_text(encoding="utf-8"))
    got = sorted([m["agent_id"] for m in data["models"]])
    expected = sorted(
        [
            "relay_bailian_deepseek_v4_flash",
            "relay_gemini_2_5_flash_thinking",
            "relay_deepseek_v3",
            "relay_qwen3_5_plus",
            "relay_glm_4_6",
            "relay_glm_4_7",
        ]
    )
    assert got == expected

    cycle1 = []
    cycle2 = []
    for round_entry in data["rounds"]:
        seen = []
        for match in round_entry["matches"]:
            seen.extend([match["left_agent"], match["right_agent"]])
        assert len(set(seen)) == 6
        assert all(seen.count(x) == 1 for x in set(seen))
        if round_entry["cycle"] == 1:
            cycle1.extend([m["pair_id"] for m in round_entry["matches"]])
        else:
            cycle2.extend([m["pair_id"] for m in round_entry["matches"]])
    assert cycle1 == cycle2

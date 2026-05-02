from __future__ import annotations

import json
from pathlib import Path

import yaml


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL {msg}")


def _audit_a00_config() -> None:
    cfg = yaml.safe_load(Path("configs/regimes/A00.yaml").read_text(encoding="utf-8"))
    runtime_controls = cfg.get("runtime_controls", {}) if isinstance(cfg, dict) else {}
    required = {
        "conversational_carryover": False,
        "file_memory": False,
        "visibility": "summary-only",
        "skills_enabled": False,
        "memory_plugin_enabled": False,
        "session_memory_hook": False,
        "pre_compaction_memory_flush": False,
        "startup_memory_prelude": False,
        "fixed_bootstrap": True,
        "fixed_tool_surface": True,
    }
    for key, expected in required.items():
        value = cfg.get(key)
        if value is None and isinstance(runtime_controls, dict):
            value = runtime_controls.get(key)
        _assert(value == expected, f"A00 mismatch {key}={value!r} expected {expected!r}")


def audit_execution_smoke(tournament_name: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    round_dir = Path("logs/round_1")
    manifest_path = round_dir / "round_manifest.json"
    if not manifest_path.exists():
        errors.append("missing logs/round_1/round_manifest.json")
        return errors, warnings

    round_manifest = _load_json(manifest_path)
    matches = round_manifest.get("matches")
    if round_manifest.get("round_idx") != 1:
        errors.append("round_manifest round_idx must be 1")
    if round_manifest.get("matches_per_round") != 3:
        errors.append("round_manifest matches_per_round must be 3")
    if not isinstance(matches, list) or len(matches) != 3:
        errors.append("exactly three matches required in round_manifest")
        return errors, warnings

    if round_manifest.get("scorecard_policy") != "raw_per_match_scorecard; pair-level aggregation is post-analysis":
        errors.append("scorecard_policy mismatch")

    seen_agents: list[str] = []
    for m in matches:
        left = m.get("left_agent_id")
        right = m.get("right_agent_id")
        seen_agents.extend([left, right])

        for field in [
            "metadata_path",
            "scorecard_path",
            "arena_result_match_a_path",
            "arena_result_match_b_path",
        ]:
            p = m.get(field)
            if not isinstance(p, str) or not Path(p).exists():
                errors.append(f"{m.get('match_id')}: missing artifact {field}")

        status = m.get("seed_control_status")
        if status == "requested_but_not_applied":
            if m.get("requested_seed") is None or m.get("applied_seed") is not None:
                errors.append(f"{m.get('match_id')}: invalid requested_but_not_applied seed fields")
            warnings.append(f"{m.get('match_id')}: seed requested but not applied")
        elif status == "applied":
            if m.get("applied_seed") is None or m.get("seed") != m.get("applied_seed"):
                errors.append(f"{m.get('match_id')}: invalid applied seed fields")
        else:
            errors.append(f"{m.get('match_id')}: unsupported seed_control_status={status!r}")

    unique_agents = sorted(set(seen_agents))
    if len(unique_agents) != 6:
        errors.append("round_1 must contain exactly six unique agents")
    for a in unique_agents:
        if seen_agents.count(a) != 1:
            errors.append(f"agent {a} must appear exactly once")

    for root in ["codebases", "submissions", "posts"]:
        tournament_root = Path("workspace") / root / tournament_name
        for side in ["left", "right"]:
            if (tournament_root / side).exists():
                errors.append(f"persistent {side}/ dir must not exist under {tournament_root}")

        for agent_id in unique_agents:
            if not (tournament_root / agent_id).exists():
                errors.append(f"missing persistent agent directory: {tournament_root / agent_id}")

    if (round_dir / "pair_scorecard.json").exists():
        errors.append("paired aggregate scorecard must not exist")

    return errors, warnings


def main() -> int:
    _audit_a00_config()
    tournament_name = "pommerman_gptv16_a00_6model_execution_smoke"
    errors, warnings = audit_execution_smoke(tournament_name)
    for w in warnings:
        print(f"WARN {w}")
    if errors:
        print("execution_smoke_audit=FAIL")
        for e in errors:
            print(f"ERROR {e}")
        return 1
    print("execution_smoke_audit=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
from pathlib import Path

import yaml


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _audit_a00() -> list[str]:
    errs: list[str] = []
    cfg = yaml.safe_load(Path("configs/regimes/A00.yaml").read_text(encoding="utf-8"))
    runtime = cfg.get("runtime_controls", {}) if isinstance(cfg, dict) else {}
    req = {
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
    for k, v in req.items():
        got = cfg.get(k)
        if got is None:
            got = runtime.get(k)
        if got != v:
            errs.append(f"A00 mismatch {k}")
    return errs


def _audit_round_manifest(path: Path, *, expected_round_idx: int) -> tuple[list[str], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    seen_agents: list[str] = []
    if not path.exists():
        return [f"missing {path}"], warnings, seen_agents
    rm = _load_json(path)
    if rm.get("round_idx") != expected_round_idx:
        errors.append(f"round_{expected_round_idx}: round_idx mismatch")
    if rm.get("matches_per_round") != 3:
        errors.append(f"round_{expected_round_idx}: matches_per_round must be 3")
    if rm.get("scorecard_policy") != "raw_per_match_scorecard; pair-level aggregation is post-analysis":
        errors.append(f"round_{expected_round_idx}: scorecard policy mismatch")
    matches = rm.get("matches")
    if not isinstance(matches, list) or len(matches) != 3:
        errors.append(f"round_{expected_round_idx}: exactly 3 matches required")
        return errors, warnings, seen_agents
    for m in matches:
        left = m.get("left_agent_id")
        right = m.get("right_agent_id")
        seen_agents.extend([left, right])
        if m.get("background_agents") != ["dummy2", "dummy3"]:
            errors.append(f"round_{expected_round_idx}: background agents mismatch")
        for f in ["metadata_path", "scorecard_path", "arena_result_match_a_path", "arena_result_match_b_path"]:
            p = m.get(f)
            if not isinstance(p, str) or not Path(p).exists():
                errors.append(f"round_{expected_round_idx}: missing artifact {f}")
        if m.get("requested_seed") is None:
            errors.append(f"round_{expected_round_idx}: requested_seed missing")
        status = m.get("seed_control_status")
        if status == "requested_but_not_applied":
            warnings.append(f"round_{expected_round_idx}/{m.get('match_id')}: seed requested but not applied")
        elif status == "applied":
            if m.get("applied_seed") is None or m.get("seed") != m.get("applied_seed"):
                errors.append(f"round_{expected_round_idx}: applied seed fields invalid")
        else:
            errors.append(f"round_{expected_round_idx}: unsupported seed_control_status")
    if len(set(seen_agents)) != 6 or any(seen_agents.count(a) != 1 for a in set(seen_agents)):
        errors.append(f"round_{expected_round_idx}: must be perfect matching over 6 unique agents")
    return errors, warnings, seen_agents


def audit_openclaw_adaptive_2round_smoke(
    tournament_name: str = "pommerman_gptv16_a00_openclaw_adaptive_2round_smoke",
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    r1_errors, r1_warnings, round1_agents = _audit_round_manifest(
        Path("logs/round_1/round_manifest.json"), expected_round_idx=1
    )
    errors.extend(r1_errors)
    warnings.extend(r1_warnings)
    r2_errors, r2_warnings, round2_agents = _audit_round_manifest(
        Path("logs/round_2/round_manifest.json"), expected_round_idx=2
    )
    errors.extend(r2_errors)
    warnings.extend(r2_warnings)

    all_agents = sorted(set(round1_agents + round2_agents))
    if len(all_agents) != 6:
        errors.append("must observe exactly 6 unique agents across rounds 1-2")

    rev_path = Path("logs/round_1/revision_manifest.json")
    if not rev_path.exists():
        errors.append("missing logs/round_1/revision_manifest.json")
        return errors, warnings
    rev = _load_json(rev_path)
    rev_agents = rev.get("agents")
    if not isinstance(rev_agents, list) or len(rev_agents) != 6:
        errors.append("revision_manifest must include exactly 6 agent entries")
        return errors, warnings
    for a in rev_agents:
        if a.get("revision_attempted") is not True:
            errors.append("all round_1 agents must be revision_attempted=true")
        if a.get("revision_executor") != "openclaw-minimal":
            errors.append("all round_1 agents must use revision_executor=openclaw-minimal")
        if a.get("openclaw_invoked") is not True:
            errors.append("all round_1 agents must have openclaw_invoked=true")
        if a.get("fallback_used") is not False:
            errors.append("all round_1 agents must have fallback_used=false")
        if a.get("revision_ok") is not True:
            errors.append("all round_1 agents must have revision_ok=true")
        if a.get("provider_route_status") != "matched":
            errors.append("all round_1 agents must have provider_route_status=matched")
        if a.get("revision_status") == "skipped_by_budget_guard":
            errors.append("no round_1 agent may be skipped_by_budget_guard")
        if a.get("revision_executor") in {"dryrun-noop", "rule-minimal"}:
            errors.append("no round_1 agent may use dryrun-noop/rule-minimal")

    prop_path = Path("logs/round_2/propagation_manifest.json")
    if not prop_path.exists():
        errors.append("missing logs/round_2/propagation_manifest.json")
        return errors, warnings
    prop = _load_json(prop_path)
    entries = prop.get("agents")
    if not isinstance(entries, list) or len(entries) != 6:
        errors.append("propagation_manifest must include exactly 6 agents")
        return errors, warnings
    prop_by_agent = {x.get("agent_id"): x for x in entries if isinstance(x, dict)}
    if len(prop_by_agent) != 6:
        errors.append("propagation_manifest agent ids must be unique and complete")
    for agent_id in all_agents:
        rec = prop_by_agent.get(agent_id)
        if not isinstance(rec, dict):
            errors.append(f"missing propagation record for agent {agent_id}")
            continue
        if rec.get("propagated") is not True or rec.get("propagation_ok") is not True:
            errors.append(f"{agent_id}: propagation flags must be true")
        if rec.get("source_revision_ok") is not True:
            errors.append(f"{agent_id}: source_revision_ok must be true")
        if rec.get("source_provider_route_status") != "matched":
            errors.append(f"{agent_id}: source_provider_route_status must be matched")
        source_post = Path(str(rec.get("source_post_path")))
        target_play = Path(str(rec.get("target_play_path")))
        if not source_post.exists():
            errors.append(f"{agent_id}: source_post_path missing")
        if not target_play.exists():
            errors.append(f"{agent_id}: target_play_path missing")
        expected_source = Path("workspace/posts") / tournament_name / agent_id / "codebase_post_1"
        expected_target = Path("workspace/codebases") / tournament_name / agent_id / "codebase_play_2"
        if source_post != expected_source:
            errors.append(f"{agent_id}: source_post_path mismatch")
        if target_play != expected_target:
            errors.append(f"{agent_id}: target_play_path mismatch")
        sub2 = Path("workspace/submissions") / tournament_name / agent_id / "submission_2"
        if not sub2.exists():
            errors.append(f"{agent_id}: submission_2 missing")

    for root in ["codebases", "submissions", "posts"]:
        troot = Path("workspace") / root / tournament_name
        for side in ["left", "right"]:
            if (troot / side).exists():
                errors.append(f"persistent {side}/ dir must not exist")

    for rd in [Path("logs/round_1"), Path("logs/round_2")]:
        if (rd / "pair_scorecard.json").exists():
            errors.append("paired aggregate scorecard must not exist")

    return errors, warnings


def main() -> int:
    errors = _audit_a00()
    e2, w2 = audit_openclaw_adaptive_2round_smoke()
    errors.extend(e2)
    for w in w2:
        print(f"WARN {w}")
    if errors:
        print("openclaw_adaptive_2round_smoke_audit=FAIL")
        for e in errors:
            print(f"ERROR {e}")
        return 1
    print("openclaw_adaptive_2round_smoke_audit=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

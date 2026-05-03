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


def audit_openclaw_revision_smoke(
    tournament_name: str,
    *,
    require_all_agents: bool = False,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    rd = Path("logs/round_1")
    rm_path = rd / "round_manifest.json"
    rev_path = rd / "revision_manifest.json"
    if not rm_path.exists():
        return ["missing round_manifest.json"], warnings
    if not rev_path.exists():
        return ["missing revision_manifest.json"], warnings

    rm = _load_json(rm_path)
    rev = _load_json(rev_path)
    matches = rm.get("matches")
    if rm.get("round_idx") != 1:
        errors.append("round_idx must be 1")
    if rm.get("matches_per_round") != 3:
        errors.append("matches_per_round must be 3")
    if not isinstance(matches, list) or len(matches) != 3:
        errors.append("exactly 3 matches required")
        return errors, warnings
    if rm.get("scorecard_policy") != "raw_per_match_scorecard; pair-level aggregation is post-analysis":
        errors.append("scorecard policy mismatch")

    seen = []
    for m in matches:
        left = m.get("left_agent_id")
        right = m.get("right_agent_id")
        seen.extend([left, right])
        if m.get("background_agents") != ["dummy2", "dummy3"]:
            errors.append("background agents mismatch")
        for f in ["metadata_path", "scorecard_path", "arena_result_match_a_path", "arena_result_match_b_path"]:
            p = m.get(f)
            if not isinstance(p, str) or not Path(p).exists():
                errors.append(f"missing artifact {f}")

        status = m.get("seed_control_status")
        if m.get("requested_seed") is None:
            errors.append("requested_seed missing")
        if status == "requested_but_not_applied":
            warnings.append(f"{m.get('match_id')}: seed requested but not applied")
        elif status == "applied":
            if m.get("applied_seed") is None or m.get("seed") != m.get("applied_seed"):
                errors.append("applied seed fields invalid")
        else:
            errors.append("unsupported seed_control_status")

    if len(set(seen)) != 6 or any(seen.count(a) != 1 for a in set(seen)):
        errors.append("round must be perfect matching over 6 unique agents")

    agents = rev.get("agents") if isinstance(rev, dict) else None
    if not isinstance(agents, list) or len(agents) != 6:
        errors.append("revision_manifest must include 6 agents")
        return errors, warnings

    attempted_ok = []
    attempted_count = 0
    for a in agents:
        attempted = bool(a.get("revision_attempted"))
        if attempted:
            attempted_count += 1
            if a.get("revision_executor") != "openclaw-minimal":
                errors.append("attempted agent must use openclaw-minimal")
            if not a.get("openclaw_invoked"):
                errors.append("attempted agent must have openclaw_invoked=true")
            if a.get("fallback_used") is not False:
                errors.append("attempted agent must have fallback_used=false")
            if a.get("revision_executor") in {"dryrun-noop", "rule-minimal"}:
                errors.append("attempted agent cannot use dryrun-noop/rule-minimal")
            prs = a.get("provider_route_status")
            if prs == "mismatch":
                errors.append("attempted agent has provider route mismatch")
            elif prs == "unknown":
                if require_all_agents:
                    errors.append("attempted agent has provider route unknown")
                else:
                    warnings.append(f"{a.get('agent_id')}: provider route unknown")
            elif prs != "matched":
                errors.append(f"attempted agent has unsupported provider route status: {prs!r}")
            if a.get("revision_ok"):
                attempted_ok.append(a)
        else:
            if a.get("revision_status") != "skipped_by_budget_guard":
                errors.append("non-selected agent must be skipped_by_budget_guard")
            if a.get("openclaw_invoked"):
                errors.append("non-selected agent cannot invoke openclaw")
            if a.get("fallback_used") is not False:
                errors.append("non-selected fallback_used must be false")

    if not attempted_ok:
        errors.append("at least one attempted openclaw-minimal revision must succeed")
    if require_all_agents:
        if attempted_count != len(agents):
            errors.append("all agents must be revision_attempted=true")
        for a in agents:
            if not bool(a.get("revision_attempted")):
                continue
            if not bool(a.get("revision_ok")):
                errors.append("all attempted agents must have revision_ok=true")
            if a.get("provider_route_status") != "matched":
                errors.append("all attempted agents must have provider_route_status=matched")
            if a.get("revision_status") == "skipped_by_budget_guard":
                errors.append("no agent may be skipped_by_budget_guard in all-agent mode")
            if a.get("openclaw_invoked") is not True:
                errors.append("all attempted agents must have openclaw_invoked=true")
            if a.get("fallback_used") is not False:
                errors.append("all attempted agents must have fallback_used=false")
            if a.get("revision_executor") in {"dryrun-noop", "rule-minimal"}:
                errors.append("attempted agent cannot use dryrun-noop/rule-minimal")

    for root in ["codebases", "submissions", "posts"]:
        troot = Path("workspace") / root / tournament_name
        for side in ["left", "right"]:
            if (troot / side).exists():
                errors.append(f"persistent {side}/ dir must not exist")

    if (rd / "pair_scorecard.json").exists():
        errors.append("paired aggregate scorecard must not exist")

    return errors, warnings


def main() -> int:
    errors = _audit_a00()
    e2, w2 = audit_openclaw_revision_smoke("pommerman_gptv16_a00_openclaw_revision_smoke")
    errors.extend(e2)
    for w in w2:
        print(f"WARN {w}")
    if errors:
        print("openclaw_revision_smoke_audit=FAIL")
        for e in errors:
            print(f"ERROR {e}")
        return 1
    print("openclaw_revision_smoke_audit=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

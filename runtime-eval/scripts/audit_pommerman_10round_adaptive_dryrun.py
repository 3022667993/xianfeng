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
    for k, exp in required.items():
        v = cfg.get(k)
        if v is None:
            v = runtime.get(k)
        if v != exp:
            errs.append(f"A00 mismatch {k}={v!r} expected {exp!r}")
    return errs


def audit_adaptive_dryrun(tournament_name: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    pair_order_c1: list[str] = []
    pair_order_c2: list[str] = []
    all_agents: list[str] = []
    pair_seed: dict[str, int | None] = {}

    for round_idx in range(1, 11):
        rd = Path("logs") / f"round_{round_idx}"
        rm = rd / "round_manifest.json"
        if not rm.exists():
            errors.append(f"missing {rm}")
            continue
        payload = _load_json(rm)
        if payload.get("round_idx") != round_idx:
            errors.append(f"round_{round_idx}: round_idx mismatch")
        if payload.get("matches_per_round") != 3:
            errors.append(f"round_{round_idx}: matches_per_round must be 3")
        if payload.get("scorecard_policy") != "raw_per_match_scorecard; pair-level aggregation is post-analysis":
            errors.append(f"round_{round_idx}: scorecard_policy mismatch")

        cycle = payload.get("cycle")
        expected_cycle = 1 if round_idx <= 5 else 2
        if cycle != expected_cycle:
            errors.append(f"round_{round_idx}: cycle mismatch")

        matches = payload.get("matches")
        if not isinstance(matches, list) or len(matches) != 3:
            errors.append(f"round_{round_idx}: exactly 3 matches required")
            continue

        seen = []
        for m in matches:
            left = m.get("left_agent_id")
            right = m.get("right_agent_id")
            seen.extend([left, right])
            all_agents.extend([left, right])
            pair_id = m.get("pair_id")
            if m.get("background_agents") != ["dummy2", "dummy3"]:
                errors.append(f"round_{round_idx}:{pair_id} background mismatch")
            for f in ["metadata_path", "scorecard_path", "arena_result_match_a_path", "arena_result_match_b_path"]:
                p = m.get(f)
                if not isinstance(p, str) or not Path(p).exists():
                    errors.append(f"round_{round_idx}:{pair_id} missing {f}")

            status = m.get("seed_control_status")
            req = m.get("requested_seed")
            app = m.get("applied_seed")
            seed = m.get("seed")
            if req is None:
                errors.append(f"round_{round_idx}:{pair_id} requested_seed missing")
            if status == "requested_but_not_applied":
                if app is not None or seed is not None:
                    errors.append(f"round_{round_idx}:{pair_id} requested_but_not_applied invalid fields")
                warnings.append(f"round_{round_idx}:{pair_id} seed requested but not applied")
            elif status == "applied":
                if app is None or seed != app:
                    errors.append(f"round_{round_idx}:{pair_id} applied status invalid fields")
            else:
                errors.append(f"round_{round_idx}:{pair_id} unsupported seed_control_status={status!r}")

            if expected_cycle == 1:
                pair_order_c1.append(pair_id)
            else:
                pair_order_c2.append(pair_id)

            prior = pair_seed.get(pair_id)
            if prior is None:
                pair_seed[pair_id] = req
            elif req != prior:
                errors.append(f"pair {pair_id} requested_seed mismatch across cycles")

            md_path = Path(m["metadata_path"])
            md = _load_json(md_path)
            if not md.get("adaptive_dryrun"):
                errors.append(f"round_{round_idx}:{pair_id} metadata missing adaptive_dryrun=true")
            if not md.get("low_cost_revision"):
                errors.append(f"round_{round_idx}:{pair_id} metadata missing low_cost_revision=true")
            if md.get("revision_executor") != "dryrun-noop":
                errors.append(f"round_{round_idx}:{pair_id} metadata revision_executor must be dryrun-noop")

        if len(set(seen)) != 6 or any(seen.count(a) != 1 for a in set(seen)):
            errors.append(f"round_{round_idx}: not a perfect matching over 6 agents")

        if (rd / "pair_scorecard.json").exists():
            errors.append(f"round_{round_idx}: paired aggregate scorecard must not exist")

    agents = sorted(set(all_agents))
    if len(agents) != 6:
        errors.append("expected exactly 6 unique agents")

    if len(pair_order_c1) == 15 and len(pair_order_c2) == 15 and pair_order_c1 != pair_order_c2:
        errors.append("cycle_2 pair order must equal cycle_1 pair order")

    for root in ["codebases", "submissions", "posts"]:
        troot = Path("workspace") / root / tournament_name
        for side in ["left", "right"]:
            if (troot / side).exists():
                errors.append(f"persistent {side}/ must not exist under {troot}")
        for agent in agents:
            for r in range(1, 11):
                suffix = {
                    "codebases": f"codebase_play_{r}",
                    "submissions": f"submission_{r}",
                    "posts": f"codebase_post_{r}",
                }[root]
                p = troot / agent / suffix
                if not p.exists():
                    errors.append(f"missing {p}")

    for agent in agents:
        for r in range(1, 10):
            post = Path("workspace/posts") / tournament_name / agent / f"codebase_post_{r}"
            nxt = Path("workspace/codebases") / tournament_name / agent / f"codebase_play_{r+1}"
            if not post.exists() or not nxt.exists():
                continue
            post_main = post / "submission" / "main.py"
            nxt_main = nxt / "submission" / "main.py"
            if post_main.exists() and nxt_main.exists():
                if post_main.read_text(encoding="utf-8") != nxt_main.read_text(encoding="utf-8"):
                    errors.append(f"propagation mismatch for {agent} round_{r}->round_{r+1}")

    return errors, warnings


def main() -> int:
    errors = _audit_a00()
    e2, w2 = audit_adaptive_dryrun("pommerman_gptv16_a00_6model_adaptive_dryrun")
    errors.extend(e2)
    for w in w2:
        print(f"WARN {w}")
    if errors:
        print("adaptive_dryrun_audit=FAIL")
        for e in errors:
            print(f"ERROR {e}")
        return 1
    print("adaptive_dryrun_audit=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

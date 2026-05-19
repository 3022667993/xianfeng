from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import yaml


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _now_utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time()))


def _infer_tournament_name(logs_root: Path, posts_root: Path) -> str | None:
    ism = logs_root / "initial_synthesis_manifest.json"
    if ism.exists():
        try:
            payload = _load_json(ism)
            value = payload.get("tournament")
            if isinstance(value, str) and value.strip():
                return value.strip()
        except Exception:
            pass
    if posts_root.exists():
        candidates = sorted(p.name for p in posts_root.iterdir() if p.is_dir())
        if len(candidates) == 1:
            return candidates[0]
    return None


def _feedback_package_root(*, posts_root: Path, tournament: str, agent_id: str, round_idx: int) -> Path:
    return posts_root / tournament / agent_id / f"codebase_post_{round_idx}" / "feedback" / f"round_{round_idx}"


def _feedback_package_v4_metrics(package_roots: list[Path]) -> dict[str, Any]:
    replay_source_counts: dict[str, int] = {}
    full_board_replay_true = 0
    full_board_replay_false = 0
    official_record_present = 0
    official_record_missing = 0
    v4_package_count = 0
    for root in package_roots:
        manifest_path = root / "package_manifest.json"
        if not manifest_path.exists():
            continue
        try:
            manifest = _load_json(manifest_path)
        except Exception:
            continue
        if manifest.get("schema_version") != "pommerman_feedback_package_v4":
            continue
        v4_package_count += 1
        replay_source = str(manifest.get("replay_source") or "unknown")
        replay_source_counts[replay_source] = replay_source_counts.get(replay_source, 0) + 1
        if manifest.get("full_board_replay") is True:
            full_board_replay_true += 1
        else:
            full_board_replay_false += 1
        matches = manifest.get("matches", [])
        if not isinstance(matches, list):
            continue
        for rel in matches:
            if not isinstance(rel, str):
                continue
            game_state = (root / rel).parent / "official_record_json" / "game_state.json"
            if game_state.exists():
                official_record_present += 1
            else:
                official_record_missing += 1
    return {
        "v4_package_count": v4_package_count,
        "replay_source_counts": replay_source_counts,
        "full_board_replay_true": full_board_replay_true,
        "full_board_replay_false": full_board_replay_false,
        "official_record_present": official_record_present,
        "official_record_missing": official_record_missing,
    }


def _infer_agent_ids_from_round_manifest(round_manifest: dict[str, Any]) -> list[str]:
    ids: set[str] = set()
    matches = round_manifest.get("matches", [])
    if not isinstance(matches, list):
        return []
    for m in matches:
        if not isinstance(m, dict):
            continue
        for key in ["left_agent_id", "right_agent_id"]:
            value = m.get(key)
            if isinstance(value, str) and value.strip():
                ids.add(value.strip())
    return sorted(ids)


def _read_models_path_from_logs(logs_root: Path) -> str | None:
    path = logs_root / "openclaw_model_route_validation.json"
    if not path.exists():
        return None
    try:
        payload = _load_json(path)
    except Exception:
        return None
    value = payload.get("models_path")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _load_model_strata_by_agent(models_path: str | None) -> dict[str, str]:
    if not isinstance(models_path, str) or not models_path.strip():
        return {}
    path = Path(models_path)
    if not path.exists():
        return {}
    try:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    models = cfg.get("models", []) if isinstance(cfg, dict) else []
    if not isinstance(models, list):
        return {}
    out: dict[str, str] = {}
    for rec in models:
        if not isinstance(rec, dict):
            continue
        agent_id = rec.get("agent_id") or rec.get("id")
        stratum = rec.get("stratum")
        if isinstance(agent_id, str) and agent_id.strip() and isinstance(stratum, str) and stratum.strip():
            out[agent_id.strip()] = stratum.strip()
    return out


def _audit_status_from_errors(errors: list[str] | None) -> str:
    if errors is None:
        return "UNKNOWN"
    if len(errors) == 0:
        return "PASS"
    text = "\n".join(str(e) for e in errors).lower()
    not_run_markers = [
        "missing logs",
        "missing logs/",
        "missing logs directory",
        "no round directories found",
        "no logs/round",
        "no logs/round_*",
        "missing round_manifest",
        "missing logs/initial_synthesis_manifest.json",
        "no revised agents found",
    ]
    if any(m in text for m in not_run_markers):
        return "NOT_RUN"
    return "FAIL"


def _run_audit(func, *args, **kwargs) -> tuple[str, list[str]]:
    try:
        errors, warnings = func(*args, **kwargs)
        _ = warnings
        if not isinstance(errors, list):
            return "UNKNOWN", ["audit returned invalid errors type"]
        return _audit_status_from_errors(errors), errors
    except Exception as exc:
        return "UNKNOWN", [repr(exc)]


def build_tournament_report(
    *,
    tournament_name: str | None = None,
    logs_root: Path = Path("logs"),
    posts_root: Path = Path("workspace/posts"),
) -> dict[str, Any]:
    tournament = tournament_name or _infer_tournament_name(logs_root, posts_root) or "unknown_tournament"
    cfg_path = Path("configs/tournaments") / f"{tournament}.yaml"
    cfg_path_str = str(cfg_path) if cfg_path.exists() else None
    cfg = {}
    if cfg_path.exists():
        try:
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        except Exception:
            cfg = {}

    initial_manifest_path = logs_root / "initial_synthesis_manifest.json"
    initial_manifest = _load_json(initial_manifest_path) if initial_manifest_path.exists() else None
    models_path = _read_models_path_from_logs(logs_root)
    strata_by_agent = _load_model_strata_by_agent(models_path)

    roster: list[dict[str, Any]] = []
    if isinstance(initial_manifest, dict) and isinstance(initial_manifest.get("agents"), list):
        for rec in initial_manifest["agents"]:
            if not isinstance(rec, dict):
                continue
            agent_id = rec.get("agent_id")
            if not isinstance(agent_id, str) or not agent_id:
                continue
            roster.append(
                {
                    "agent_id": agent_id,
                    "provider_model": rec.get("provider_model"),
                    "executor": "openclaw-minimal",
                    "stratum": strata_by_agent.get(agent_id, "unknown"),
                }
            )
    roster_agent_ids = [str(r.get("agent_id")) for r in roster if isinstance(r, dict) and isinstance(r.get("agent_id"), str)]
    num_agents = len(roster_agent_ids) if roster_agent_ids else int(cfg.get("num_models", 0) or 0)
    full_double_rr_rounds = (2 * (num_agents - 1)) if num_agents >= 2 else 0

    round_dirs = sorted(p for p in logs_root.glob("round_*") if p.is_dir())
    rounds_out: list[dict[str, Any]] = []
    prompt_variants = {
        "initial_synthesis_prompt_variant": None,
        "revision_prompt_variant": None,
    }
    feedback_package_variant = None
    feedback_visibility = None
    incomplete = False
    pair_counts: dict[tuple[str, str], list[tuple[str, str]]] = {}
    games_seen = 0
    all_feedback_package_roots: list[Path] = []

    for rd in round_dirs:
        try:
            round_idx = int(rd.name.split("_", 1)[1])
        except Exception:
            continue
        round_manifest_path = rd / "round_manifest.json"
        if not round_manifest_path.exists():
            incomplete = True
            continue
        rm = _load_json(round_manifest_path)
        if isinstance(rm.get("revision_prompt_variant"), str):
            prompt_variants["revision_prompt_variant"] = rm.get("revision_prompt_variant")
        if isinstance(rm.get("initial_synthesis_prompt_variant"), str):
            prompt_variants["initial_synthesis_prompt_variant"] = rm.get("initial_synthesis_prompt_variant")
        if isinstance(rm.get("feedback_package_variant"), str):
            feedback_package_variant = rm.get("feedback_package_variant")
        if isinstance(rm.get("feedback_visibility"), str):
            feedback_visibility = rm.get("feedback_visibility")

        matches = rm.get("matches", [])
        match_rows: list[dict[str, Any]] = []
        winners: list[str] = []
        steps: list[int] = []

        if isinstance(matches, list):
            for m in matches:
                if not isinstance(m, dict):
                    continue
                match_id = m.get("match_id")
                match_idx = m.get("match_idx")
                if not isinstance(match_id, str) or not isinstance(match_idx, int):
                    continue
                md = rd / f"match_{match_idx}"
                arena_a_path = md / "arena_result_match_a.json"
                if not arena_a_path.exists():
                    incomplete = True
                    continue
                arena_a = _load_json(arena_a_path)
                wa = arena_a.get("left_right_winner")
                if wa in {"left", "right", "draw"}:
                    winners.append(wa)
                sa = arena_a.get("steps")
                if isinstance(sa, int):
                    steps.append(sa)
                left_agent = str(m.get("left_agent_id") or "")
                right_agent = str(m.get("right_agent_id") or "")
                if left_agent and right_agent:
                    key = tuple(sorted([left_agent, right_agent]))
                    pair_counts.setdefault(key, []).append((left_agent, right_agent))
                    games_seen += 1
                match_rows.append(
                    {
                        "match_id": match_id,
                        "left_agent_id": left_agent,
                        "right_agent_id": right_agent,
                        "seed": m.get("applied_seed") if "applied_seed" in m else m.get("seed"),
                        "winner": arena_a.get("left_right_winner"),
                        "steps": arena_a.get("steps"),
                        "reward": arena_a.get("reward"),
                    }
                )

        match_count = len(match_rows)
        draw_matches = sum(1 for w in winners if w == "draw")
        non_draw_matches = sum(1 for w in winners if w in {"left", "right"})
        avg_steps = (sum(steps) / len(steps)) if steps else 0.0
        draw_rate = (draw_matches / match_count) if match_count else 0.0

        revision_manifest_path = rd / "revision_manifest.json"
        revision_present = revision_manifest_path.exists()
        revision_agents: list[dict[str, Any]] = []
        expected_agents_with_package = 0
        agents_with_package = 0
        expected_agent_ids_for_package: list[str] = []
        candidate_agent_ids_for_package = roster_agent_ids or _infer_agent_ids_from_round_manifest(rm)
        package_agent_ids_present = [
            aid
            for aid in candidate_agent_ids_for_package
            if _feedback_package_root(posts_root=posts_root, tournament=tournament, agent_id=aid, round_idx=round_idx).exists()
        ]
        agents_with_package = len(package_agent_ids_present)
        if revision_present:
            rev = _load_json(revision_manifest_path)
            entries = rev.get("agents", [])
            if isinstance(entries, list):
                for rec in entries:
                    if not isinstance(rec, dict):
                        continue
                    agent_id = rec.get("agent_id")
                    if not isinstance(agent_id, str) or not agent_id:
                        continue
                    if bool(rec.get("revision_attempted", False)):
                        expected_agent_ids_for_package.append(agent_id)
                    revision_agents.append(
                        {
                            "agent_id": agent_id,
                            "revision_ok": bool(rec.get("revision_ok", False)),
                            "provider_route_status": rec.get("provider_route_status"),
                            "actual_provider": rec.get("actual_provider"),
                            "actual_model": rec.get("actual_model"),
                            "fallback_used": bool(rec.get("fallback_used", False)),
                            "effective_submission_changed": bool(rec.get("effective_submission_changed", False)),
                            "before_hash": rec.get("submission_main_sha256_before"),
                            "after_hash": rec.get("submission_main_sha256_after"),
                            "changed_files_hash_based": rec.get("changed_files_hash_based") if isinstance(rec.get("changed_files_hash_based"), list) else [],
                        }
                    )
        else:
            if agents_with_package > 0:
                expected_agent_ids_for_package = list(candidate_agent_ids_for_package)

        if expected_agent_ids_for_package:
            agents_with_package = sum(
                1
                for aid in expected_agent_ids_for_package
                if _feedback_package_root(posts_root=posts_root, tournament=tournament, agent_id=aid, round_idx=round_idx).exists()
            )
            package_roots_for_round = [
                _feedback_package_root(posts_root=posts_root, tournament=tournament, agent_id=aid, round_idx=round_idx)
                for aid in expected_agent_ids_for_package
                if _feedback_package_root(posts_root=posts_root, tournament=tournament, agent_id=aid, round_idx=round_idx).exists()
            ]
        else:
            package_roots_for_round = [
                _feedback_package_root(posts_root=posts_root, tournament=tournament, agent_id=aid, round_idx=round_idx)
                for aid in candidate_agent_ids_for_package
                if _feedback_package_root(posts_root=posts_root, tournament=tournament, agent_id=aid, round_idx=round_idx).exists()
            ]
        all_feedback_package_roots.extend(package_roots_for_round)
        v4_round_metrics = _feedback_package_v4_metrics(package_roots_for_round)
        expected_agents_with_package = len(expected_agent_ids_for_package)
        feedback_packages_present = (expected_agents_with_package > 0) or (agents_with_package > 0)
        if expected_agents_with_package > agents_with_package:
            incomplete = True
        if v4_round_metrics["official_record_missing"] and v4_round_metrics["full_board_replay_true"]:
            incomplete = True

        propagation_present = (logs_root / f"round_{round_idx + 1}" / "propagation_manifest.json").exists()
        all_hashes_match = None
        if propagation_present:
            prop = _load_json(logs_root / f"round_{round_idx + 1}" / "propagation_manifest.json")
            entries = prop.get("agents", [])
            if isinstance(entries, list) and entries:
                matches_post = [bool(e.get("propagation_matches_post", False)) for e in entries if isinstance(e, dict)]
                all_hashes_match = all(matches_post) if matches_post else None

        rounds_out.append(
            {
                "round": round_idx,
                "schedule_mode": str(rm.get("schedule_mode") or "double_round_robin"),
                "match_legs": str(rm.get("match_legs") or "single"),
                "matches": match_rows,
                "round_summary": {
                    "match_count": match_count,
                    "draw_matches": draw_matches,
                    "non_draw_matches": non_draw_matches,
                    "draw_rate": round(draw_rate, 6),
                    "average_terminal_step": round(avg_steps, 3),
                },
                "feedback_packages": {
                    "present": feedback_packages_present,
                    "agents_with_package": agents_with_package,
                    "expected_agents_with_package": expected_agents_with_package,
                    **v4_round_metrics,
                },
                "revision": {"present": revision_present, "agents": revision_agents},
                "propagation_to_next_round": {
                    "present": propagation_present,
                    "all_hashes_match": all_hashes_match,
                },
            }
        )

    unique_pairs_seen = len(pair_counts)
    complete_double_round_robin = False
    if num_agents >= 2 and games_seen == num_agents * (num_agents - 1):
        complete_double_round_robin = True
        for entries in pair_counts.values():
            if len(entries) != 2 or entries[0] == entries[1]:
                complete_double_round_robin = False
                break

    initial_section: dict[str, Any] = {"present": bool(initial_manifest_path.exists())}
    if isinstance(initial_manifest, dict) and isinstance(initial_manifest.get("agents"), list):
        agents = []
        hashes = []
        for rec in initial_manifest["agents"]:
            if not isinstance(rec, dict):
                continue
            agent_id = rec.get("agent_id")
            if not isinstance(agent_id, str) or not agent_id:
                continue
            starter_sha = rec.get("starter_submission_sha256")
            initial_sha = rec.get("initial_submission_sha256")
            if isinstance(initial_sha, str):
                hashes.append(initial_sha)
            agents.append(
                {
                    "agent_id": agent_id,
                    "strategy_profile_id": rec.get("initial_strategy_profile_id"),
                    "starter_submission_sha256": starter_sha,
                    "initial_submission_sha256": initial_sha,
                    "effective_initial_submission_changed": bool(rec.get("effective_initial_submission_changed", False)),
                    "provider_route_status": rec.get("initial_provider_route_status"),
                    "actual_provider": rec.get("initial_actual_provider"),
                    "actual_model": rec.get("initial_actual_model"),
                    "fallback_used": bool(rec.get("initial_fallback_used", False)),
                }
            )
        initial_section = {
            "present": True,
            "unique_initial_submission_hash_count": len(set(hashes)),
            "agents": agents,
        }

    audits: dict[str, str] = {
        "initial_synthesis": "NOT_RUN",
        "feedback_package": "NOT_RUN",
        "process_feedback": "NOT_RUN",
        "compact_trajectory": "NOT_RUN",
        "seed_control": "NOT_RUN",
        "effective_revision": "NOT_RUN",
        "double_round_robin_schedule": "NOT_RUN",
    }
    audit_errors_debug: dict[str, list[str]] = {}
    try:
        from scripts.audit_pommerman_initial_synthesis import audit_pommerman_initial_synthesis
        from scripts.audit_pommerman_process_feedback import audit_process_feedback
        from scripts.audit_pommerman_compact_trajectory import audit_compact_trajectory
        from scripts.audit_pommerman_seed_control import audit_seed_control
        from scripts.audit_pommerman_effective_revision import audit_effective_revision
        from scripts.audit_pommerman_feedback_package import audit_feedback_package
        from scripts.audit_pommerman_double_round_robin_schedule import audit_double_round_robin_schedule

        audits["initial_synthesis"], audit_errors_debug["initial_synthesis"] = _run_audit(audit_pommerman_initial_synthesis, tournament)
        audits["process_feedback"], audit_errors_debug["process_feedback"] = _run_audit(audit_process_feedback, logs_root)
        audits["compact_trajectory"], audit_errors_debug["compact_trajectory"] = _run_audit(audit_compact_trajectory, logs_root)
        audits["seed_control"], audit_errors_debug["seed_control"] = _run_audit(audit_seed_control, logs_root)
        audits["effective_revision"], audit_errors_debug["effective_revision"] = _run_audit(audit_effective_revision)
        audits["feedback_package"], audit_errors_debug["feedback_package"] = _run_audit(
            audit_feedback_package, tournament_name=tournament, logs_root=logs_root, posts_root=posts_root
        )
        audits["double_round_robin_schedule"], audit_errors_debug["double_round_robin_schedule"] = _run_audit(
            audit_double_round_robin_schedule, tournament_name=tournament, logs_root=logs_root
        )
    except Exception:
        pass

    feedback_replay_summary = _feedback_package_v4_metrics(all_feedback_package_roots)
    limitations = [
        "Feedback Package v4 uses official record_json_dir when available and compact trajectory fallback otherwise.",
        "seat-bias is controlled by later reversed encounter in full double round-robin, not by running multiple games inside one scheduled match.",
        "A 3-round smoke is only a prefix of the full double round-robin schedule.",
        "Full board/observation replay is only claimed when official game_state.json records are present.",
    ]

    report: dict[str, Any] = {
        "schema_version": "pommerman_tournament_report_v2",
        "generated_at_utc": _now_utc_iso(),
        "tournament_config_path": cfg_path_str,
        "tournament_name": tournament,
        "game": "pommerman_1v1",
        "regime": "A00",
        "schedule_mode": "double_round_robin",
        "match_legs": "single",
        "prompt_variants": prompt_variants,
        "feedback_package_variant": feedback_package_variant,
        "feedback_visibility": feedback_visibility,
        "feedback_replay_summary": feedback_replay_summary,
        "model_roster": roster,
        "initial_synthesis": initial_section,
        "rounds": rounds_out,
        "pair_coverage": {
            "rounds_seen": len(rounds_out),
            "games_seen": games_seen,
            "unique_pairs_seen": unique_pairs_seen,
            "num_agents": num_agents,
            "full_double_rr_rounds": full_double_rr_rounds,
            "complete_double_round_robin": complete_double_round_robin,
        },
        "audits": audits,
        "limitations": limitations,
        "incomplete": bool(incomplete),
    }

    def _is_hard_fail(audit_name: str) -> bool:
        if audits.get(audit_name) != "FAIL":
            return False
        errs = audit_errors_debug.get(audit_name, [])
        text = "\n".join(str(e) for e in errs).lower()
        soft_markers = [
            "missing",
            "no round",
            "not found",
            "unable to determine num_models",
            "rounds must be a non-empty list",
            "at least 2 models required",
        ]
        if any(marker in text for marker in soft_markers):
            return False
        return True

    any_hard_fail = any(_is_hard_fail(k) for k in audits.keys())
    all_pass = all(v == "PASS" for v in audits.values())
    if report["incomplete"]:
        verdict = "INCOMPLETE"
    elif any_hard_fail:
        verdict = "FAIL"
    elif all_pass:
        verdict = "PASS"
    else:
        verdict = "INCOMPLETE"
    report["verdict"] = verdict
    return report


def render_tournament_report_markdown(report: dict[str, Any]) -> str:
    tn = report.get("tournament_name")
    gen = report.get("generated_at_utc")
    cfg = report.get("tournament_config_path") or "unknown"
    verdict = report.get("verdict") or "UNKNOWN"

    lines: list[str] = []
    lines.append(f"# Pommerman Tournament Report: {tn}")
    lines.append("")
    lines.append(f"- Generated at: {gen}")
    lines.append(f"- Tournament config: {cfg}")
    lines.append(f"- Verdict: **{verdict}**")
    lines.append(f"- schedule_mode: {report.get('schedule_mode')}")
    lines.append(f"- match_legs: {report.get('match_legs')}")
    lines.append("")

    pv = report.get("prompt_variants") or {}
    lines.append("## Prompt Variants")
    lines.append("")
    lines.append(f"- initial_synthesis_prompt_variant: {pv.get('initial_synthesis_prompt_variant')}")
    lines.append(f"- revision_prompt_variant: {pv.get('revision_prompt_variant')}")
    lines.append(f"- feedback_package_variant: {report.get('feedback_package_variant')}")
    lines.append(f"- feedback_visibility: {report.get('feedback_visibility')}")
    lines.append("")

    frs = report.get("feedback_replay_summary") or {}
    lines.append("## Feedback Replay")
    lines.append("")
    lines.append(f"- replay_source_counts: {frs.get('replay_source_counts')}")
    lines.append(f"- full_board_replay_true: {frs.get('full_board_replay_true')}")
    lines.append(f"- full_board_replay_false: {frs.get('full_board_replay_false')}")
    lines.append(f"- official_record_present: {frs.get('official_record_present')}")
    lines.append(f"- official_record_missing: {frs.get('official_record_missing')}")
    lines.append("")

    roster = report.get("model_roster") or []
    lines.append("## Model Roster")
    lines.append("")
    lines.append("| agent_id | provider_model | executor | stratum |")
    lines.append("| --- | --- | --- | --- |")
    for rec in roster:
        if not isinstance(rec, dict):
            continue
        lines.append(
            f"| {rec.get('agent_id')} | {rec.get('provider_model')} | {rec.get('executor')} | {rec.get('stratum')} |"
        )
    lines.append("")

    coverage = report.get("pair_coverage") or {}
    lines.append("## Pair Coverage")
    lines.append("")
    lines.append(f"- rounds_seen: {coverage.get('rounds_seen')}")
    lines.append(f"- games_seen: {coverage.get('games_seen')}")
    lines.append(f"- unique_pairs_seen: {coverage.get('unique_pairs_seen')}")
    lines.append(f"- full_double_rr_rounds: {coverage.get('full_double_rr_rounds')}")
    lines.append(f"- complete_double_round_robin: {coverage.get('complete_double_round_robin')}")
    lines.append("")

    lines.append("## Rounds")
    lines.append("")
    for rd in report.get("rounds", []) or []:
        if not isinstance(rd, dict):
            continue
        r = rd.get("round")
        lines.append(f"### Round {r}")
        lines.append("")
        lines.append(f"- schedule_mode: {rd.get('schedule_mode')}")
        lines.append(f"- match_legs: {rd.get('match_legs')}")
        matches = rd.get("matches", [])
        lines.append("| round | match | left | right | seed | winner | steps | reward |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        if isinstance(matches, list):
            for m in matches:
                if not isinstance(m, dict):
                    continue
                lines.append(
                    f"| {r} | {m.get('match_id')} | {m.get('left_agent_id')} | {m.get('right_agent_id')} | {m.get('seed')} | "
                    f"{m.get('winner')} | {m.get('steps')} | {m.get('reward')} |"
                )
        lines.append("")
        rs = rd.get("round_summary", {}) if isinstance(rd.get("round_summary"), dict) else {}
        lines.append(f"- match_count: {rs.get('match_count')}")
        lines.append(f"- draw_rate: {rs.get('draw_rate')}")
        lines.append(f"- average_terminal_step: {rs.get('average_terminal_step')}")
        lines.append("")

    lines.append("## Audit Summary")
    lines.append("")
    for name, status in (report.get("audits") or {}).items():
        lines.append(f"- {name}: {status}")
    lines.append("")

    lines.append("## Limitations")
    lines.append("")
    for x in report.get("limitations", []) or []:
        lines.append(f"- {x}")
    lines.append("")
    return "\n".join(lines)


def write_tournament_report(
    *,
    tournament_name: str | None = None,
    logs_root: Path = Path("logs"),
    posts_root: Path = Path("workspace/posts"),
) -> dict[str, Any]:
    report = build_tournament_report(tournament_name=tournament_name, logs_root=logs_root, posts_root=posts_root)
    logs_root.mkdir(parents=True, exist_ok=True)
    (logs_root / "tournament_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (logs_root / "tournament_report.md").write_text(render_tournament_report_markdown(report), encoding="utf-8")
    return report

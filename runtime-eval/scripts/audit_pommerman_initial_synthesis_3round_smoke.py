from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.audit_pommerman_double_round_robin_schedule import audit_double_round_robin_schedule
from scripts.audit_pommerman_initial_synthesis import audit_pommerman_initial_synthesis


DEFAULT_TOURNAMENT_CONFIG = Path(
    "configs/tournaments/pommerman_gptv16_a00_openclaw_initial_synthesis_3round_neutral_double_rr_smoke.yaml"
)
DEFAULT_TOURNAMENT_NAME = "pommerman_gptv16_a00_openclaw_initial_synthesis_3round_neutral_double_rr_smoke"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_tournament_config(tournament_config_path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(tournament_config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"failed to read tournament config: {tournament_config_path}: {exc!r}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"invalid tournament config payload: {tournament_config_path}")
    return payload


def _load_tournament_config_name(tournament_config_path: Path) -> str:
    payload = _load_tournament_config(tournament_config_path)
    tournament_name = payload.get("name")
    if not isinstance(tournament_name, str) or not tournament_name.strip():
        raise ValueError(f"tournament config missing non-empty name: {tournament_config_path}")
    return tournament_name.strip()


def _check_seed_applied(payload: dict[str, Any], label: str, errors: list[str]) -> None:
    if payload.get("seed_control_status") != "applied":
        errors.append(f"{label}: seed_control_status must be applied")
    requested_seed = payload.get("requested_seed")
    if requested_seed is None:
        errors.append(f"{label}: requested_seed missing")
    if payload.get("applied_seed") != requested_seed:
        errors.append(f"{label}: applied_seed must equal requested_seed")
    if payload.get("seed") != requested_seed:
        errors.append(f"{label}: seed must equal requested_seed")
    if payload.get("seed_control_method_applied") != "env.seed(...)":
        errors.append(f"{label}: seed_control_method_applied must be env.seed(...)")
    methods = payload.get("seed_control_methods_attempted")
    if not isinstance(methods, list) or "env.seed(...)" not in methods:
        errors.append(f"{label}: seed_control_methods_attempted must include env.seed(...)")
    if "seed_control_env_seed_return" not in payload:
        errors.append(f"{label}: seed_control_env_seed_return missing")


def _audit_round_manifest(path: Path, expected_round_idx: int) -> tuple[list[str], set[str]]:
    errors: list[str] = []
    seen_agents: list[str] = []
    if not path.exists():
        return [f"missing {path}"], set()
    rm = _load_json(path)
    if rm.get("round_idx") != expected_round_idx:
        errors.append(f"round_{expected_round_idx}: round_idx mismatch")
    if rm.get("matches_per_round") != 3:
        errors.append(f"round_{expected_round_idx}: matches_per_round must be 3")
    if rm.get("schedule_mode", "double_round_robin") != "double_round_robin":
        errors.append(f"round_{expected_round_idx}: schedule_mode must be double_round_robin")
    if rm.get("match_legs", "single") != "single":
        errors.append(f"round_{expected_round_idx}: match_legs must be single")
    if rm.get("scorecard_policy") != "raw_per_match_scorecard; pair-level aggregation is post-analysis":
        errors.append(f"round_{expected_round_idx}: scorecard policy mismatch")
    matches = rm.get("matches")
    if not isinstance(matches, list) or len(matches) != 3:
        errors.append(f"round_{expected_round_idx}: exactly 3 matches required")
        return errors, set(seen_agents)
    for m in matches:
        if not isinstance(m, dict):
            errors.append(f"round_{expected_round_idx}: match entry must be object")
            continue
        left = m.get("left_agent_id")
        right = m.get("right_agent_id")
        if isinstance(left, str):
            seen_agents.append(left)
        if isinstance(right, str):
            seen_agents.append(right)
        if m.get("background_agents") != ["dummy2", "dummy3"]:
            errors.append(f"round_{expected_round_idx}: background agents mismatch")
        if m.get("pair_id") is None:
            errors.append(f"round_{expected_round_idx}: pair_id missing")
        for field in ["metadata_path", "scorecard_path", "arena_result_match_a_path"]:
            path_value = m.get(field)
            if not isinstance(path_value, str) or not Path(path_value).exists():
                errors.append(f"round_{expected_round_idx}: missing artifact {field}")
        _check_seed_applied(m, f"round_{expected_round_idx}/{m.get('match_id')}", errors)
    if len(seen_agents) != 6 or len(set(seen_agents)) != 6:
        errors.append(f"round_{expected_round_idx}: must be perfect matching over 6 unique agents")
    return errors, set(seen_agents)


def _audit_revision_manifest(path: Path, label: str) -> list[str]:
    errors: list[str] = []
    if not path.exists():
        return [f"missing {path}"]
    rev = _load_json(path)
    require_effective = bool(rev.get("require_effective_submission_change", False))
    agents = rev.get("agents")
    if not isinstance(agents, list) or len(agents) != 6:
        return [f"{label}: revision_manifest must include exactly 6 entries"]
    for agent in agents:
        if not isinstance(agent, dict):
            errors.append(f"{label}: revision entry must be object")
            continue
        if agent.get("revision_attempted") is not True:
            errors.append(f"{label}: revision_attempted=true required")
        if agent.get("openclaw_invoked") is not True:
            errors.append(f"{label}: openclaw_invoked=true required")
        if agent.get("revision_ok") is not True:
            errors.append(f"{label}: revision_ok=true required")
        if agent.get("provider_route_status") != "matched":
            errors.append(f"{label}: provider_route_status=matched required")
        if agent.get("fallback_used") is not False:
            errors.append(f"{label}: fallback_used=false required")
        if agent.get("revision_executor") in {"dryrun-noop", "rule-minimal"}:
            errors.append(f"{label}: revision_executor cannot be dryrun-noop/rule-minimal")
        if "effective_submission_changed" not in agent:
            errors.append(f"{label}: effective_submission_changed required")
        if "changed_files_hash_based" not in agent:
            errors.append(f"{label}: changed_files_hash_based required")
        if agent.get("changed_files_inconsistent_with_hash") is True:
            errors.append(f"{label}: changed_files inconsistent with submission hash")
        if require_effective and agent.get("effective_submission_changed") is not True:
            errors.append(f"{label}: require_effective_submission_change=true but effective_submission_changed=false")
    return errors


def _audit_propagation_manifest(
    path: Path,
    *,
    tournament_name: str,
    source_round: int,
    target_round: int,
    expected_agents: set[str],
) -> list[str]:
    errors: list[str] = []
    if not path.exists():
        return [f"missing {path}"]
    payload = _load_json(path)
    entries = payload.get("agents")
    if not isinstance(entries, list) or len(entries) != 6:
        return [f"{path}: propagation_manifest must include exactly 6 agents"]
    by_agent = {e.get("agent_id"): e for e in entries if isinstance(e, dict)}
    if set(by_agent.keys()) != expected_agents:
        errors.append(f"{path}: propagation agents mismatch")
    for agent_id in expected_agents:
        rec = by_agent.get(agent_id)
        if not isinstance(rec, dict):
            errors.append(f"{path}: missing propagation record for {agent_id}")
            continue
        if rec.get("propagated") is not True or rec.get("propagation_ok") is not True:
            errors.append(f"{path}: {agent_id} propagated/propagation_ok must be true")
        if rec.get("source_revision_ok") is not True:
            errors.append(f"{path}: {agent_id} source_revision_ok must be true")
        if rec.get("source_provider_route_status") != "matched":
            errors.append(f"{path}: {agent_id} source_provider_route_status must be matched")
        if rec.get("source_round") != source_round:
            errors.append(f"{path}: {agent_id} source_round mismatch")
        if rec.get("target_round") != target_round:
            errors.append(f"{path}: {agent_id} target_round mismatch")
        source_post_path = Path(str(rec.get("source_post_path")))
        target_play_path = Path(str(rec.get("target_play_path")))
        expected_source = Path("workspace/posts") / tournament_name / agent_id / f"codebase_post_{source_round}"
        expected_target = Path("workspace/codebases") / tournament_name / agent_id / f"codebase_play_{target_round}"
        if source_post_path != expected_source:
            errors.append(f"{path}: {agent_id} source_post_path mismatch")
        if target_play_path != expected_target:
            errors.append(f"{path}: {agent_id} target_play_path mismatch")
        source_sha = rec.get("source_submission_sha256")
        target_sha = rec.get("target_submission_sha256")
        actual_source_sha = _sha256_file(source_post_path / "submission/main.py")
        actual_target_sha = _sha256_file(target_play_path / "submission/main.py")
        if source_sha != actual_source_sha:
            errors.append(f"{path}: {agent_id} source_submission_sha256 mismatch")
        if target_sha != actual_target_sha:
            errors.append(f"{path}: {agent_id} target_submission_sha256 mismatch")
        if source_sha != target_sha:
            errors.append(f"{path}: {agent_id} source/target submission sha256 differ")
        if rec.get("propagation_matches_post") is not True:
            errors.append(f"{path}: {agent_id} propagation_matches_post must be true")
    return errors


def _audit_match_artifacts(round_idx: int, errors: list[str]) -> None:
    round_dir = Path(f"logs/round_{round_idx}")
    for match_dir in sorted(p for p in round_dir.glob("match_*") if p.is_dir()):
        for required in [
            "metadata.json",
            "scorecard.json",
            "arena_result_match_a.json",
            "trajectory_summary.json",
            "trajectory_compact_match_a.jsonl",
            "trajectory_events.json",
        ]:
            if not (match_dir / required).exists():
                errors.append(f"{match_dir}: missing {required}")
        if (match_dir / "arena_result_match_b.json").exists():
            errors.append(f"{match_dir}: arena_result_match_b.json must not exist in single-leg mode")
        metadata = _load_json(match_dir / "metadata.json") if (match_dir / "metadata.json").exists() else {}
        for agent_id in [metadata.get("left_agent_id"), metadata.get("right_agent_id")]:
            if not isinstance(agent_id, str):
                continue
            if not (match_dir / f"agent_feedback_{agent_id}.json").exists():
                errors.append(f"{match_dir}: missing agent_feedback_{agent_id}.json")
            if not (match_dir / f"agent_feedback_{agent_id}.md").exists():
                errors.append(f"{match_dir}: missing agent_feedback_{agent_id}.md")
        for payload_name in [
            "metadata.json",
            "scorecard.json",
            "arena_result_match_a.json",
            "trajectory_summary.json",
            "trajectory_events.json",
        ]:
            payload_path = match_dir / payload_name
            if payload_path.exists():
                _check_seed_applied(_load_json(payload_path), str(payload_path), errors)


def audit_pommerman_initial_synthesis_3round_smoke(
    tournament_name: str = DEFAULT_TOURNAMENT_NAME,
    tournament_config_path: Path = DEFAULT_TOURNAMENT_CONFIG,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    e0, w0 = audit_pommerman_initial_synthesis(tournament_name=tournament_name)
    errors.extend(e0)
    warnings.extend(w0)

    if not tournament_config_path.exists():
        errors.append(f"missing initial synthesis 3round tournament config: {tournament_config_path}")
    else:
        try:
            cfg = _load_tournament_config(tournament_config_path)
            configured_name = str(cfg.get("name", "")).strip()
            if configured_name != tournament_name:
                errors.append(
                    "tournament_name mismatch with config: "
                    f"{tournament_name} != {configured_name} ({tournament_config_path})"
                )
            if cfg.get("schedule_mode") != "double_round_robin":
                errors.append(f"{tournament_config_path}: schedule_mode must be double_round_robin")
            if cfg.get("match_legs") != "single":
                errors.append(f"{tournament_config_path}: match_legs must be single")
            if int(cfg.get("num_rounds", 0) or 0) != 3:
                errors.append(f"{tournament_config_path}: num_rounds must be 3 for prefix smoke")
        except ValueError as exc:
            errors.append(str(exc))

    e_schedule, w_schedule = audit_double_round_robin_schedule(tournament_name=tournament_name)
    errors.extend(e_schedule)
    warnings.extend(w_schedule)

    round_agent_sets: list[set[str]] = []
    for round_idx in [1, 2, 3]:
        e_round, agents = _audit_round_manifest(Path(f"logs/round_{round_idx}/round_manifest.json"), round_idx)
        errors.extend(e_round)
        round_agent_sets.append(agents)
        _audit_match_artifacts(round_idx, errors)

    all_agents = set.union(*round_agent_sets) if round_agent_sets else set()
    if len(all_agents) != 6:
        errors.append("must observe exactly 6 unique agents")

    ip_path = Path("logs/round_1/initial_propagation_manifest.json")
    if not ip_path.exists():
        errors.append("missing logs/round_1/initial_propagation_manifest.json")
    else:
        ip = _load_json(ip_path)
        entries = ip.get("agents")
        if not isinstance(entries, list) or len(entries) != 6:
            errors.append("initial_propagation_manifest must include exactly 6 entries")
        else:
            by_agent = {x.get("agent_id"): x for x in entries if isinstance(x, dict)}
            for agent_id in all_agents:
                rec = by_agent.get(agent_id)
                if not isinstance(rec, dict):
                    errors.append(f"initial propagation missing agent {agent_id}")
                    continue
                source = Path(str(rec.get("source_initial_post_path")))
                target = Path(str(rec.get("target_play_path")))
                if _sha256_file(source / "submission/main.py") != _sha256_file(target / "submission/main.py"):
                    errors.append(f"initial propagation hash mismatch for {agent_id}")
                if rec.get("propagation_matches_post") is not True:
                    errors.append(f"initial propagation propagation_matches_post must be true for {agent_id}")

    errors.extend(_audit_revision_manifest(Path("logs/round_1/revision_manifest.json"), "round_1"))
    errors.extend(_audit_revision_manifest(Path("logs/round_2/revision_manifest.json"), "round_2"))

    expected_agents = all_agents if all_agents else {f"a{i}" for i in range(1, 7)}
    errors.extend(
        _audit_propagation_manifest(
            Path("logs/round_2/propagation_manifest.json"),
            tournament_name=tournament_name,
            source_round=1,
            target_round=2,
            expected_agents=expected_agents,
        )
    )
    errors.extend(
        _audit_propagation_manifest(
            Path("logs/round_3/propagation_manifest.json"),
            tournament_name=tournament_name,
            source_round=2,
            target_round=3,
            expected_agents=expected_agents,
        )
    )

    for root in ["codebases", "submissions", "posts"]:
        troot = Path("workspace") / root / tournament_name
        for side in ["left", "right"]:
            if (troot / side).exists():
                errors.append(f"persistent {side}/ dir must not exist")

    for round_idx in [1, 2, 3]:
        if Path(f"logs/round_{round_idx}/pair_scorecard.json").exists():
            errors.append("paired aggregate scorecard must not exist")

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audit Pommerman A00 initial-synthesis 3-round single-leg double_round_robin prefix smoke artifacts."
        )
    )
    parser.add_argument(
        "--tournament",
        default=str(DEFAULT_TOURNAMENT_CONFIG),
        help="Path to tournament YAML config.",
    )
    parser.add_argument(
        "--tournament-name",
        default=None,
        help="Optional explicit tournament name override. Defaults to config `name`.",
    )
    args = parser.parse_args()

    tournament_config_path = Path(args.tournament)
    tournament_name = args.tournament_name
    if tournament_name is None:
        try:
            tournament_name = _load_tournament_config_name(tournament_config_path)
        except ValueError as exc:
            print("pommerman_initial_synthesis_3round_smoke_audit=FAIL")
            print(f"ERROR {exc}")
            return 1

    errors, warnings = audit_pommerman_initial_synthesis_3round_smoke(
        tournament_name=tournament_name,
        tournament_config_path=tournament_config_path,
    )
    for warning in warnings:
        print(f"WARN {warning}")
    if errors:
        print("pommerman_initial_synthesis_3round_smoke_audit=FAIL")
        for error in errors:
            print(f"ERROR {error}")
        return 1
    print("pommerman_initial_synthesis_3round_smoke_audit=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

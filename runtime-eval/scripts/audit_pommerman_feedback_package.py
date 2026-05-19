from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from runner.core.pommerman_results import classify_pommerman_result


FORBIDDEN_FILENAMES = {
    "revision_manifest.json",
    "propagation_manifest.json",
    "revision_audit.json",
}

FORBIDDEN_TEXT_TOKENS = {
    # OpenClaw internals / provenance
    "provider_route_status",
    "actual_provider",
    "actual_model",
    "fallback_used",
    "requested_provider_model",
    "openclaw_default_missing_placeholders",
    "effective_submission_changed",
    "effective_revision",
    "route_provenance",
}

NEUTRAL_README_FORBIDDEN_TACTICS = [
    "center movement",
    "wood clearing",
    "powerups",
    "opponent pressure",
    "reduce stop",
    "safe aggression",
]

V4_README_FORBIDDEN = [
    "starter_repos",
    "match_b",
    "both legs",
    "paired legs",
    "seat-swap legs",
    *NEUTRAL_README_FORBIDDEN_TACTICS,
]

V4_PRIVACY_TOKENS = [
    "provider_route_status",
    "actual_provider",
    "actual_model",
    "fallback_used",
    "requested_provider_model",
    "openclaw_default_missing_placeholders",
    "effective_submission_changed",
    "effective_revision",
    "route_provenance",
    "/root/autodl-tmp/runtime-eval/workspace/",
    "/root/.openclaw/",
    "openclaw_workspaces/minimal/runtime_eval_runs",
    "workspace/codebases",
    "workspace/posts",
    "workspace/submissions",
    "codebase_play_",
    "codebase_post_",
    "diff_path",
    "revision_audit.json",
    "match_b",
]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _iter_jsonl(path: Path):
    for idx, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except Exception as exc:
            raise ValueError(f"{path}: invalid json line {idx}: {exc!r}")
        if not isinstance(payload, dict):
            raise ValueError(f"{path}: json line {idx} is not an object")
        yield idx, payload


def _infer_tournament_name(posts_root: Path, logs_root: Path) -> str | None:
    ism = logs_root / "initial_synthesis_manifest.json"
    if ism.exists():
        try:
            payload = _load_json(ism)
            value = payload.get("tournament")
            if isinstance(value, str) and value.strip():
                return value.strip()
        except Exception:
            pass
    candidates = sorted(p.name for p in posts_root.iterdir() if p.is_dir()) if posts_root.exists() else []
    if len(candidates) == 1:
        return candidates[0]
    return None


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_roster_agent_ids(logs_root: Path) -> list[str]:
    ism = logs_root / "initial_synthesis_manifest.json"
    if not ism.exists():
        return []
    try:
        payload = _load_json(ism)
    except Exception:
        return []
    agents = payload.get("agents", [])
    if not isinstance(agents, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for rec in agents:
        if not isinstance(rec, dict):
            continue
        aid = rec.get("agent_id")
        if isinstance(aid, str) and aid.strip() and aid not in seen:
            seen.add(aid)
            out.append(aid)
    return out


def _infer_agent_ids_from_round_manifest(round_manifest: dict[str, Any]) -> list[str]:
    matches = round_manifest.get("matches", [])
    if not isinstance(matches, list):
        return []
    ids: set[str] = set()
    for m in matches:
        if not isinstance(m, dict):
            continue
        for key in ["left_agent_id", "right_agent_id"]:
            v = m.get(key)
            if isinstance(v, str) and v.strip():
                ids.add(v.strip())
    return sorted(ids)


def _text_contains_forbidden(path: Path, tokens: list[str]) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8").lower()
    except Exception:
        return []
    return [token for token in tokens if token in text]


def _audit_v4_package(
    *,
    package_root: Path,
    agent_id: str,
    round_idx: int,
    match_by_id: dict[str, dict[str, Any]],
    round_dir: Path,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    readme_path = package_root / "README.md"
    scoreboard_path = package_root / "public_scoreboard.json"
    manifest_path = package_root / "package_manifest.json"

    for req in [readme_path, scoreboard_path, manifest_path]:
        if not req.exists():
            errors.append(f"{package_root}: missing required file {req.name}")
    if not manifest_path.exists():
        return errors, warnings

    manifest = _load_json(manifest_path)
    if manifest.get("schema_version") != "pommerman_feedback_package_v4":
        errors.append(f"{manifest_path}: schema_version mismatch")
    if int(manifest.get("round", -1) or -1) != int(round_idx):
        errors.append(f"{manifest_path}: round mismatch")
    if manifest.get("agent_id") != agent_id:
        errors.append(f"{manifest_path}: agent_id mismatch")
    if manifest.get("visibility") != "own_matches_plus_public_scoreboard":
        errors.append(f"{manifest_path}: visibility mismatch")
    if manifest.get("schedule_mode") != "double_round_robin":
        errors.append(f"{manifest_path}: schedule_mode must be double_round_robin")
    if manifest.get("match_legs") != "single":
        errors.append(f"{manifest_path}: match_legs must be single")
    if manifest.get("contains_private_opponent_code") is not False:
        errors.append(f"{manifest_path}: contains_private_opponent_code must be false")

    replay_source = manifest.get("replay_source")
    if replay_source not in {"pommerman_record_json_dir", "compact_trajectory_fallback"}:
        errors.append(f"{manifest_path}: invalid replay_source")
    full_board_replay = manifest.get("full_board_replay")
    if replay_source == "pommerman_record_json_dir" and full_board_replay is not True:
        errors.append(f"{manifest_path}: pommerman_record_json_dir requires full_board_replay=true")
    if replay_source == "compact_trajectory_fallback" and full_board_replay is not False:
        errors.append(f"{manifest_path}: compact_trajectory_fallback requires full_board_replay=false")

    if readme_path.exists():
        text = readme_path.read_text(encoding="utf-8")
        if "../../README.md" not in text:
            errors.append(f"{readme_path}: must reference ../../README.md")
        for token in V4_README_FORBIDDEN:
            if token in text.lower():
                errors.append(f"{readme_path}: contains forbidden v4 README token: {token}")

    if scoreboard_path.exists():
        scoreboard_text = scoreboard_path.read_text(encoding="utf-8")
        lower = scoreboard_text.lower()
        for token in V4_PRIVACY_TOKENS:
            if token in lower:
                errors.append(f"{scoreboard_path}: contains forbidden token: {token}")
        scoreboard = json.loads(scoreboard_text)
        if scoreboard.get("schema_version") != "pommerman_public_scoreboard_v4":
            errors.append(f"{scoreboard_path}: schema_version mismatch")
        if scoreboard.get("schedule_mode") != "double_round_robin":
            errors.append(f"{scoreboard_path}: schedule_mode mismatch")
        if scoreboard.get("match_legs") != "single":
            errors.append(f"{scoreboard_path}: match_legs mismatch")
        sc_matches = scoreboard.get("matches")
        if not isinstance(sc_matches, list):
            errors.append(f"{scoreboard_path}: matches must be a list")
        elif len(sc_matches) != len(match_by_id):
            errors.append(f"{scoreboard_path}: expected {len(match_by_id)} matches, found {len(sc_matches)}")
        if isinstance(sc_matches, list):
            for row in sc_matches:
                if not isinstance(row, dict):
                    continue
                for key in ["environment_winners", "environment_winner_labels", "submitted_pair_outcome", "draw_type"]:
                    if key not in row:
                        errors.append(f"{scoreboard_path}: match row missing {key}")

    expected_own_matches = [
        m
        for m in match_by_id.values()
        if agent_id in {m.get("left_agent_id"), m.get("right_agent_id")}
    ]
    own_match_ids = sorted(str(m.get("match_id")) for m in expected_own_matches if isinstance(m.get("match_id"), str))
    matches_dir = package_root / "matches"
    if not matches_dir.exists():
        errors.append(f"{package_root}: missing matches/ directory")
        return errors, warnings
    present_match_dirs = sorted(p.name for p in matches_dir.iterdir() if p.is_dir())
    extra = sorted(set(present_match_dirs) - set(own_match_ids))
    if extra:
        errors.append(f"{matches_dir}: contains non-own match directories: {extra}")

    manifest_matches = manifest.get("matches")
    if not isinstance(manifest_matches, list):
        errors.append(f"{manifest_path}: matches must be a list")
        manifest_matches = []
    expected_manifest_matches = [f"matches/{mid}/match_index.json" for mid in own_match_ids]
    if sorted(manifest_matches) != sorted(expected_manifest_matches):
        errors.append(f"{manifest_path}: matches list mismatch")

    any_missing_official = False
    for mid in own_match_ids:
        match_pkg = matches_dir / mid
        if not match_pkg.exists():
            errors.append(f"{matches_dir}: missing match directory {mid}")
            continue
        match_index_path = match_pkg / "match_index.json"
        actions_path = match_pkg / "actions.jsonl"
        run_logs_path = match_pkg / "run_logs.txt"
        official_path = match_pkg / "official_record_json" / "game_state.json"
        for req in [match_index_path, actions_path, run_logs_path]:
            if not req.exists():
                errors.append(f"{match_pkg}: missing {req.name}")
        if not official_path.exists():
            any_missing_official = True

        match_rec = match_by_id.get(mid, {})
        match_idx = int(match_rec.get("match_idx", -1) or -1)
        source_match_dir = round_dir / f"match_{match_idx}" if match_idx > 0 else None
        metadata = None
        arena_a = None
        if source_match_dir is not None and source_match_dir.exists():
            if (source_match_dir / "metadata.json").exists():
                metadata = _load_json(source_match_dir / "metadata.json")
            if (source_match_dir / "arena_result_match_a.json").exists():
                arena_a = _load_json(source_match_dir / "arena_result_match_a.json")

        if match_index_path.exists():
            index_text = match_index_path.read_text(encoding="utf-8")
            if "match_b" in index_text.lower():
                errors.append(f"{match_index_path}: contains match_b")
            match_index = json.loads(index_text)
            if match_index.get("schema_version") != "pommerman_match_index_v4":
                errors.append(f"{match_index_path}: schema_version mismatch")
            if match_index.get("schedule_mode") != "double_round_robin":
                errors.append(f"{match_index_path}: schedule_mode mismatch")
            if match_index.get("match_legs") != "single":
                errors.append(f"{match_index_path}: match_legs mismatch")
            if match_index.get("seat_swap") is not False:
                errors.append(f"{match_index_path}: seat_swap must be false")
            if "legs" in match_index:
                errors.append(f"{match_index_path}: must not use paired legs schema")
            game = match_index.get("game")
            if not isinstance(game, dict):
                errors.append(f"{match_index_path}: missing game object")
                game = {}
            if game.get("internal_leg_id") != "match_a":
                errors.append(f"{match_index_path}: internal_leg_id must be match_a")
            if match_index.get("agent_id") != agent_id:
                errors.append(f"{match_index_path}: agent_id mismatch")
            if match_index.get("match_id") != mid:
                errors.append(f"{match_index_path}: match_id mismatch")
            if isinstance(metadata, dict):
                if match_index.get("requested_seed") != metadata.get("requested_seed"):
                    errors.append(f"{match_index_path}: requested_seed mismatch vs metadata")
                if match_index.get("applied_seed") != metadata.get("applied_seed"):
                    errors.append(f"{match_index_path}: applied_seed mismatch vs metadata")
            if isinstance(arena_a, dict):
                expected_classification = classify_pommerman_result(arena_a)
                if game.get("winner") != arena_a.get("left_right_winner"):
                    errors.append(f"{match_index_path}: winner mismatch vs arena")
                if game.get("steps") != arena_a.get("steps"):
                    errors.append(f"{match_index_path}: steps mismatch vs arena")
                if game.get("reward") != arena_a.get("reward"):
                    errors.append(f"{match_index_path}: reward mismatch vs arena")
                for key, expected_value in expected_classification.items():
                    if game.get(key) != expected_value:
                        errors.append(f"{match_index_path}: {key} mismatch vs arena")

        if actions_path.exists():
            rows = [payload for _line_no, payload in _iter_jsonl(actions_path)]
            for row in rows:
                if row.get("schema_version") != "pommerman_actions_v1":
                    errors.append(f"{actions_path}: schema_version mismatch")
                    break
                if row.get("internal_leg_id") != "match_a":
                    errors.append(f"{actions_path}: internal_leg_id must be match_a")
                    break
                if "agent_action" not in row or "opponent_action" not in row:
                    errors.append(f"{actions_path}: missing agent_action/opponent_action")
                    break
                if "match_b" in json.dumps(row).lower():
                    errors.append(f"{actions_path}: contains match_b")
                    break

    if full_board_replay is True and any_missing_official:
        errors.append(f"{manifest_path}: full_board_replay=true but game_state.json is missing")
    if replay_source == "pommerman_record_json_dir" and any_missing_official:
        errors.append(f"{manifest_path}: official replay source selected but game_state.json is missing")

    for p in sorted(x for x in package_root.rglob("*") if x.is_file()):
        if p.suffix in {".log"}:
            continue
        try:
            text = p.read_text(encoding="utf-8").lower()
        except Exception:
            continue
        for token in V4_PRIVACY_TOKENS:
            if token in text:
                errors.append(f"{p}: contains forbidden token: {token}")

    return errors, warnings


def audit_feedback_package(
    *,
    tournament_name: str | None = None,
    logs_root: Path = Path("logs"),
    posts_root: Path = Path("workspace/posts"),
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    tournament = tournament_name or _infer_tournament_name(posts_root, logs_root)
    if not tournament:
        errors.append("unable to infer tournament_name; pass --tournament or ensure logs/initial_synthesis_manifest.json exists")
        return errors, warnings

    roster_agent_ids = _load_roster_agent_ids(logs_root)
    cfg = _load_yaml(Path("configs/tournaments") / f"{tournament}.yaml")
    require_all_agents_revised = bool(cfg.get("require_all_agents_revised", False))
    revision_rounds_raw = cfg.get("revision_rounds", [])
    revision_rounds: set[int] = set()
    if revision_rounds_raw == "auto_before_final":
        raw_num_rounds = cfg.get("num_rounds", 0)
        if raw_num_rounds == "auto_full_double_rr":
            observed_rounds = [
                int(p.name.split("_", 1)[1])
                for p in logs_root.glob("round_*")
                if p.is_dir() and p.name.split("_", 1)[1].isdigit()
            ]
            num_rounds = max(observed_rounds) if observed_rounds else 0
        else:
            try:
                num_rounds = int(raw_num_rounds or 0)
            except Exception:
                num_rounds = 0
        revision_rounds = set(range(1, num_rounds))
    elif isinstance(revision_rounds_raw, list):
        for r in revision_rounds_raw:
            try:
                revision_rounds.add(int(r))
            except Exception:
                continue

    round_dirs = sorted(p for p in logs_root.glob("round_*") if p.is_dir())
    if not round_dirs:
        errors.append("no round directories found under logs/")
        return errors, warnings

    for rd in round_dirs:
        try:
            round_idx = int(rd.name.split("_", 1)[1])
        except Exception:
            continue
        match_dirs = sorted(p for p in rd.glob("match_*") if p.is_dir())
        has_match_artifacts = any((md / "metadata.json").exists() for md in match_dirs)
        rev_manifest_path = rd / "revision_manifest.json"
        has_revision_manifest = rev_manifest_path.exists()
        if not has_match_artifacts and not has_revision_manifest and not (rd / "round_manifest.json").exists():
            # The runner may create placeholder logs/round_k directories ahead of time.
            # Skip empty rounds that have no artifacts yet.
            continue
        round_manifest_path = rd / "round_manifest.json"
        if not round_manifest_path.exists():
            errors.append(f"{rd}: missing round_manifest.json")
            continue
        round_manifest = _load_json(round_manifest_path)
        matches = round_manifest.get("matches", [])
        if not isinstance(matches, list) or not matches:
            errors.append(f"{round_manifest_path}: missing matches")
            continue
        match_by_id: dict[str, dict[str, Any]] = {}
        for m in matches:
            if not isinstance(m, dict):
                continue
            mid = m.get("match_id")
            if isinstance(mid, str) and mid:
                match_by_id[mid] = m

        expected_agent_ids: list[str] = []
        if has_revision_manifest:
            rev_manifest = _load_json(rev_manifest_path)
            agents = rev_manifest.get("agents", [])
            if not isinstance(agents, list) or not agents:
                errors.append(f"{rev_manifest_path}: missing agents")
                continue
            for agent_rec in agents:
                if not isinstance(agent_rec, dict):
                    continue
                if not bool(agent_rec.get("revision_attempted", False)):
                    continue
                agent_id = agent_rec.get("agent_id")
                if not isinstance(agent_id, str) or not agent_id:
                    errors.append(f"{rev_manifest_path}: invalid agent_id in revision manifest")
                    continue
                expected_agent_ids.append(agent_id)
        else:
            # When the tournament requires all agents to be revised after this round, feedback
            # packages must exist even if the revision stage crashed before emitting a manifest.
            if require_all_agents_revised and (not revision_rounds or round_idx in revision_rounds):
                expected_agent_ids = roster_agent_ids or _infer_agent_ids_from_round_manifest(round_manifest)

        if expected_agent_ids:
            present = sum(
                1
                for aid in expected_agent_ids
                if (posts_root / tournament / aid / f"codebase_post_{round_idx}" / "feedback" / f"round_{round_idx}").exists()
            )
            if present != len(expected_agent_ids):
                errors.append(f"round_{round_idx} feedback packages incomplete: {present}/{len(expected_agent_ids)}")

        for agent_id in expected_agent_ids:

            package_root = posts_root / tournament / agent_id / f"codebase_post_{round_idx}" / "feedback" / f"round_{round_idx}"
            if not package_root.exists():
                errors.append(f"{package_root}: missing feedback package root")
                continue

            for forbidden in FORBIDDEN_FILENAMES:
                if (package_root / forbidden).exists():
                    errors.append(f"{package_root}: forbidden file present: {forbidden}")

            package_manifest_path = package_root / "package_manifest.json"
            if package_manifest_path.exists():
                try:
                    package_manifest = _load_json(package_manifest_path)
                except Exception as exc:
                    errors.append(f"{package_manifest_path}: failed to parse json: {exc!r}")
                    package_manifest = {}
                if package_manifest.get("schema_version") == "pommerman_feedback_package_v4":
                    e4, w4 = _audit_v4_package(
                        package_root=package_root,
                        agent_id=agent_id,
                        round_idx=round_idx,
                        match_by_id=match_by_id,
                        round_dir=rd,
                    )
                    errors.extend(e4)
                    warnings.extend(w4)
                    continue

            readme_path = package_root / "README.md"
            round_summary_path = package_root / "round_summary.json"
            scoreboard_path = package_root / "public_scoreboard.json"
            checksums_path = package_root / "checksums.json"
            for req in [readme_path, round_summary_path, scoreboard_path, checksums_path]:
                if not req.exists():
                    errors.append(f"{package_root}: missing required file {req.name}")

            if readme_path.exists():
                text = readme_path.read_text(encoding="utf-8").lower()
                for token in NEUTRAL_README_FORBIDDEN_TACTICS:
                    if token in text:
                        errors.append(f"{readme_path}: contains forbidden neutral coaching token: {token}")

            if round_summary_path.exists():
                try:
                    rs = _load_json(round_summary_path)
                    if rs.get("schema_version") != "pommerman_feedback_package_v3":
                        errors.append(f"{round_summary_path}: schema_version mismatch")
                    if int(rs.get("round", -1) or -1) != int(round_idx):
                        errors.append(f"{round_summary_path}: round mismatch")
                    if rs.get("agent_id") != agent_id:
                        errors.append(f"{round_summary_path}: agent_id mismatch")
                except Exception as exc:
                    errors.append(f"{round_summary_path}: failed to parse json: {exc!r}")

            # Scoreboard should be public and never contain private workspace paths.
            if scoreboard_path.exists():
                try:
                    scoreboard_text = scoreboard_path.read_text(encoding="utf-8")
                    lower = scoreboard_text.lower()
                    for tok in sorted(FORBIDDEN_TEXT_TOKENS):
                        if tok in lower:
                            errors.append(f"{scoreboard_path}: contains forbidden token: {tok}")
                    sc = json.loads(scoreboard_text)
                    if isinstance(sc, dict):
                        sc_matches = sc.get("matches", [])
                        if isinstance(sc_matches, list) and len(sc_matches) != len(match_by_id):
                            errors.append(f"{scoreboard_path}: expected {len(match_by_id)} matches, found {len(sc_matches)}")
                except Exception as exc:
                    errors.append(f"{scoreboard_path}: failed to parse json: {exc!r}")

            checksums_payload: dict[str, Any] | None = None
            if checksums_path.exists():
                try:
                    checksums_payload = _load_json(checksums_path)
                except Exception as exc:
                    errors.append(f"{checksums_path}: failed to parse json: {exc!r}")
                    checksums_payload = None
            if isinstance(checksums_payload, dict):
                files = checksums_payload.get("files")
                if not isinstance(files, dict):
                    errors.append(f"{checksums_path}: missing files mapping")
                    files = {}
                for relpath, digest in files.items():
                    if not isinstance(relpath, str) or not isinstance(digest, str):
                        errors.append(f"{checksums_path}: invalid checksum entry type")
                        continue
                    p = package_root / relpath
                    if not p.exists():
                        errors.append(f"{checksums_path}: listed file missing: {relpath}")
                        continue
                    actual = _sha256_file(p)
                    if actual != digest:
                        errors.append(f"{checksums_path}: checksum mismatch for {relpath}")

            # Validate that only own match packages exist and are consistent with arena artifacts.
            expected_own_matches = [
                m
                for m in match_by_id.values()
                if agent_id in {m.get("left_agent_id"), m.get("right_agent_id")}
            ]
            own_match_ids = sorted(str(m.get("match_id")) for m in expected_own_matches if isinstance(m.get("match_id"), str))

            matches_dir = package_root / "matches"
            if not matches_dir.exists():
                errors.append(f"{package_root}: missing matches/ directory")
                continue
            present_match_dirs = sorted(p.name for p in matches_dir.iterdir() if p.is_dir())
            extra = sorted(set(present_match_dirs) - set(own_match_ids))
            if extra:
                errors.append(f"{matches_dir}: contains non-own match directories: {extra}")

            for mid in own_match_ids:
                match_pkg = matches_dir / mid
                if not match_pkg.exists():
                    errors.append(f"{matches_dir}: missing match directory {mid}")
                    continue
                req_files = [
                    match_pkg / "result.json",
                    match_pkg / "match_replay.jsonl",
                    match_pkg / "build.log",
                    match_pkg / "test.log",
                    match_pkg / "stderr.log",
                ]
                for p in req_files:
                    if not p.exists():
                        errors.append(f"{match_pkg}: missing {p.name}")

                # Compare seeds against match metadata.
                match_rec = match_by_id.get(mid, {})
                match_idx = int(match_rec.get("match_idx", -1) or -1)
                match_dir = rd / f"match_{match_idx}" if match_idx > 0 else None
                metadata = None
                arena_a = None
                if match_dir is not None and match_dir.exists():
                    if (match_dir / "metadata.json").exists():
                        try:
                            metadata = _load_json(match_dir / "metadata.json")
                        except Exception:
                            metadata = None
                    if (match_dir / "arena_result_match_a.json").exists():
                        try:
                            arena_a = _load_json(match_dir / "arena_result_match_a.json")
                        except Exception:
                            arena_a = None

                if (match_pkg / "result.json").exists():
                    opponent_id: str | None = None
                    try:
                        result = _load_json(match_pkg / "result.json")
                        if result.get("schema_version") != "pommerman_match_result_v3":
                            errors.append(f"{match_pkg / 'result.json'}: schema_version mismatch")
                        if int(result.get("round", -1) or -1) != int(round_idx):
                            errors.append(f"{match_pkg / 'result.json'}: round mismatch")
                        if result.get("agent_id") != agent_id:
                            errors.append(f"{match_pkg / 'result.json'}: agent_id mismatch")
                        if result.get("match_id") != mid:
                            errors.append(f"{match_pkg / 'result.json'}: match_id mismatch")
                        if isinstance(result.get("opponent_agent_id"), str):
                            opponent_id = str(result.get("opponent_agent_id"))
                        if isinstance(metadata, dict):
                            if result.get("applied_seed") != metadata.get("applied_seed"):
                                errors.append(f"{match_pkg / 'result.json'}: applied_seed mismatch vs metadata")
                            if result.get("requested_seed") != metadata.get("requested_seed"):
                                errors.append(f"{match_pkg / 'result.json'}: requested_seed mismatch vs metadata")
                        if isinstance(arena_a, dict):
                            ma = result.get("match_a", {}) if isinstance(result.get("match_a"), dict) else {}
                            if ma.get("steps") != arena_a.get("steps"):
                                errors.append(f"{match_pkg / 'result.json'}: match_a steps mismatch vs arena")
                            if ma.get("reward") != arena_a.get("reward"):
                                errors.append(f"{match_pkg / 'result.json'}: match_a reward mismatch vs arena")
                    except Exception as exc:
                        errors.append(f"{match_pkg / 'result.json'}: failed to parse json: {exc!r}")
                    if opponent_id:
                        opponent_path_tokens = [
                            f"workspace/codebases/{tournament}/{opponent_id}".lower(),
                            f"workspace/posts/{tournament}/{opponent_id}".lower(),
                            f"workspace/submissions/{tournament}/{opponent_id}".lower(),
                        ]
                        for log_name in ["build.log", "test.log", "stderr.log"]:
                            lp = match_pkg / log_name
                            if not lp.exists():
                                continue
                            try:
                                log_text = lp.read_text(encoding="utf-8").lower()
                            except Exception:
                                continue
                            for tok in opponent_path_tokens:
                                if tok in log_text:
                                    errors.append(f"{lp}: contains opponent workspace path token: {tok}")

                replay_path = match_pkg / "match_replay.jsonl"
                if replay_path.exists():
                    try:
                        rows = [payload for _line_no, payload in _iter_jsonl(replay_path)]
                    except ValueError as exc:
                        errors.append(str(exc))
                        continue
                    if not rows:
                        errors.append(f"{replay_path}: no replay rows")
                        continue
                    for row in rows:
                        if row.get("schema_version") != "pommerman_public_state_replay_v1":
                            errors.append(f"{replay_path}: schema_version mismatch in replay row")
                            break
                    if isinstance(arena_a, dict):
                        steps = arena_a.get("steps")
                        if isinstance(steps, int):
                            if len(rows) not in {steps, steps + 1}:
                                errors.append(f"{replay_path}: row_count={len(rows)} does not match arena steps={steps}")
                            elif len(rows) == steps + 1:
                                warnings.append(f"{replay_path}: accepted off-by-one replay row count vs steps")
                        if rows[-1].get("reward") != arena_a.get("reward"):
                            errors.append(f"{replay_path}: final reward does not match arena reward")
                        if rows[-1].get("done") is not True:
                            warnings.append(f"{replay_path}: final row done != true")

            # Heuristic leak checks over all text files in the package (excluding gz replay blobs).
            for p in sorted(x for x in package_root.rglob("*") if x.is_file()):
                if p.suffix in {".gz", ".log"}:
                    continue
                try:
                    text = p.read_text(encoding="utf-8")
                except Exception:
                    continue
                lower = text.lower()
                for tok in sorted(FORBIDDEN_TEXT_TOKENS):
                    if tok in lower:
                        errors.append(f"{p}: contains forbidden token: {tok}")

    return errors, warnings


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--tournament", required=False)
    args = parser.parse_args()

    errors, warnings = audit_feedback_package(tournament_name=args.tournament)
    for w in warnings:
        print(f"WARN {w}")
    if errors:
        print("pommerman_feedback_package_audit=FAIL")
        for e in errors:
            print(f"ERROR {e}")
        return 1
    print("pommerman_feedback_package_audit=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

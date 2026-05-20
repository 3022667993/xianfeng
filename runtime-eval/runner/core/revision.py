from __future__ import annotations

import json
from pathlib import Path
import shutil
import difflib
import subprocess
import hashlib
from typing import Any, Iterable


def copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _read_text(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines(keepends=True)
    except Exception:
        return []


def _sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _infer_post_context(codebase_post_dir: Path) -> tuple[str | None, str | None]:
    """Best-effort parse `workspace/posts/<tournament>/<agent_id>/codebase_post_<round>`."""
    try:
        parts = list(codebase_post_dir.resolve().parts)
    except Exception:
        parts = list(codebase_post_dir.parts)
    if "workspace" not in parts or "posts" not in parts:
        return None, None
    try:
        posts_idx = parts.index("posts")
    except ValueError:
        return None, None
    if posts_idx + 2 >= len(parts):
        return None, None
    tournament_name = parts[posts_idx + 1]
    agent_id = parts[posts_idx + 2]
    return str(tournament_name), str(agent_id)


def _infer_codebase_post_round_idx(codebase_post_dir: Path) -> int | None:
    name = codebase_post_dir.name
    prefix = "codebase_post_"
    if not name.startswith(prefix):
        return None
    suffix = name[len(prefix):]
    try:
        return int(suffix)
    except Exception:
        return None


def _normalize_round_match_records(round_match_records: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if round_match_records is None:
        return out
    for rec in round_match_records:
        if not isinstance(rec, dict):
            continue
        required = ["match_id", "match_idx", "match_dir", "left_agent_id", "right_agent_id"]
        if not all(k in rec for k in required):
            continue
        out.append(rec)
    return out


def write_diff_patch(before_dir: Path, after_dir: Path, out_path: Path) -> None:
    diffs: list[str] = []

    before_files = sorted([p for p in before_dir.rglob("*") if p.is_file()])
    after_files = sorted([p for p in after_dir.rglob("*") if p.is_file()])

    rel_before = {p.relative_to(before_dir): p for p in before_files}
    rel_after = {p.relative_to(after_dir): p for p in after_files}

    all_keys = sorted(set(rel_before) | set(rel_after))

    for rel in all_keys:
        before_path = rel_before.get(rel)
        after_path = rel_after.get(rel)

        before_lines = _read_text(before_path) if before_path else []
        after_lines = _read_text(after_path) if after_path else []

        diff = difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=str(before_path) if before_path else f"/dev/null:{rel}",
            tofile=str(after_path) if after_path else f"/dev/null:{rel}",
        )
        diffs.extend(diff)

    out_path.write_text("".join(diffs), encoding="utf-8")


def _read_feedback_winner(round_idx: int) -> str | None:
    if round_idx <= 1:
        return None

    feedback_path = Path("logs") / f"round_{round_idx - 1}" / "feedback_package.json"
    if not feedback_path.exists():
        return None

    try:
        feedback_data = json.loads(feedback_path.read_text(encoding="utf-8"))
        scorecard = feedback_data.get("scorecard", {})
        winner = scorecard.get("left_right_winner")
        if winner in {"left", "right", "draw"}:
            return winner
    except Exception:
        return None

    return None


def _read_aggression(submission_main_path: Path) -> int:
    marker = "AGGRESSION = "
    for line in submission_main_path.read_text(encoding="utf-8").splitlines():
        if line.startswith(marker):
            value = line[len(marker):].strip()
            if value in {"0", "1"}:
                return int(value)
    raise ValueError(f"missing editable AGGRESSION in {submission_main_path}")


def _read_aggression_optional(submission_main_path: Path) -> int | None:
    try:
        return _read_aggression(submission_main_path)
    except Exception:
        return None


def _write_aggression(submission_main_path: Path, new_value: int) -> None:
    marker = "AGGRESSION = "
    lines = submission_main_path.read_text(encoding="utf-8").splitlines()
    updated = False
    for idx, line in enumerate(lines):
        if line.startswith(marker):
            lines[idx] = f"{marker}{new_value}"
            updated = True
            break
    if not updated:
        raise ValueError(f"missing editable AGGRESSION in {submission_main_path}")
    submission_main_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _append_revision_log(
    log_path: Path,
    round_idx: int,
    side: str,
    changed: bool,
    old_aggression: int | None,
    new_aggression: int | None,
    reason: str,
    executor: str,
    success: bool,
    changed_files: list[str],
    model_id: str | None = None,
    agent_id: str | None = None,
    provider_model: str | None = None,
) -> None:
    prev = ""
    if log_path.exists():
        prev = log_path.read_text(encoding="utf-8")

    changed_text = "yes" if changed else "no"
    success_text = "yes" if success else "no"
    old_aggression_text = str(old_aggression) if isinstance(old_aggression, int) else "-"
    new_aggression_text = str(new_aggression) if isinstance(new_aggression, int) else "-"
    files_text = ",".join(changed_files) if changed_files else "-"
    prev += (
        f"\n- round_{round_idx}: minimal revision for {side}"
        f" | executor={executor}"
        f" | model_id={model_id or '-'}"
        f" | agent_id={agent_id or '-'}"
        f" | provider_model={provider_model or '-'}"
        f" | success={success_text}"
        f" | changed={changed_text}"
        f" | aggression_before={old_aggression_text}"
        f" | aggression_after={new_aggression_text}"
        f" | changed_files={files_text}"
        f" | reason={reason}\n"
    )
    log_path.write_text(prev, encoding="utf-8")


def _apply_rule_revision(
    submission_main_path: Path,
    round_idx: int,
    side: str,
    previous_winner: str | None,
    log_path: Path,
    model_id: str | None = None,
    agent_id: str | None = None,
    provider_model: str | None = None,
) -> tuple[bool, str]:
    old_aggression = _read_aggression(submission_main_path)
    new_aggression = old_aggression
    previous_round = round_idx - 1

    should_toggle = (
        previous_winner is not None
        and previous_winner != "draw"
        and previous_winner != side
    )
    if should_toggle:
        new_aggression = 1 - old_aggression
        _write_aggression(submission_main_path, new_aggression)

    if round_idx == 1:
        reason = "no previous feedback_package.json"
    elif previous_winner is None:
        reason = f"round_{previous_round} feedback unavailable or missing scorecard.left_right_winner"
    else:
        reason = f"round_{previous_round} scorecard.left_right_winner={previous_winner}"

    _append_revision_log(
        log_path=log_path,
        round_idx=round_idx,
        side=side,
        changed=new_aggression != old_aggression,
        old_aggression=old_aggression,
        new_aggression=new_aggression,
        reason=reason,
        executor="rule-minimal",
        success=True,
        changed_files=["submission/main.py"] if new_aggression != old_aggression else [],
        model_id=model_id,
        agent_id=agent_id,
        provider_model=provider_model,
    )

    if new_aggression != old_aggression:
        return True, f"minimal revision applied: AGGRESSION {old_aggression}->{new_aggression}"
    return True, "minimal revision applied: AGGRESSION unchanged"


def _apply_openclaw_minimal_revision(
    codebase_post_dir: Path,
    submission_main_path: Path,
    round_idx: int,
    side: str,
    game: str,
    regime: str,
    previous_winner: str | None,
    log_path: Path,
    model_id: str | None = None,
    provider_model: str | None = None,
    openclaw_agent_id: str | None = None,
    retry_on_noop: bool = False,
    feedback_artifact_paths: list[str] | None = None,
    prompt_variant: str = "anti_draw_coached",
) -> tuple[bool, str]:
    old_aggression = _read_aggression_optional(submission_main_path)
    previous_round = round_idx - 1
    if round_idx == 1:
        reason = "no previous feedback_package.json"
        _append_revision_log(
            log_path=log_path,
            round_idx=round_idx,
            side=side,
            changed=False,
            old_aggression=old_aggression,
            new_aggression=old_aggression,
            reason=reason,
            executor="openclaw-minimal",
            success=True,
            changed_files=[],
            model_id=model_id,
            agent_id=openclaw_agent_id,
            provider_model=provider_model,
        )
        return True, "openclaw-minimal revision applied: AGGRESSION unchanged"

    feedback_path = Path("logs") / f"round_{previous_round}" / "feedback_package.json"
    feedback_path_arg: Path | None = None
    if prompt_variant != "neutral":
        if not feedback_path.exists():
            reason = f"round_{previous_round} feedback_package.json missing"
            _append_revision_log(
                log_path=log_path,
                round_idx=round_idx,
                side=side,
                changed=False,
                old_aggression=old_aggression,
                new_aggression=old_aggression,
                reason=reason,
                executor="openclaw-minimal",
                success=False,
                changed_files=[],
                model_id=model_id,
                agent_id=openclaw_agent_id,
                provider_model=provider_model,
            )
            return False, f"openclaw-minimal revision failed: {reason}"
        feedback_path_arg = feedback_path
    else:
        feedback_path_arg = feedback_path if feedback_path.exists() else None

    bootstrap_path = Path(__file__).with_name("openclaw_minimal_bootstrap.txt")
    feedback_round_idx = _infer_codebase_post_round_idx(codebase_post_dir)
    if feedback_round_idx is None:
        feedback_round_idx = max(0, int(round_idx) - 1)
    runner_cmd = [
        "python",
        "-m",
        "runner.core.openclaw_minimal",
        "--bootstrap",
        str(bootstrap_path),
        "--codebase-post-dir",
        str(codebase_post_dir),
        "--round-idx",
        str(int(feedback_round_idx)),
        "--side",
        side,
        "--game",
        game,
        "--regime",
        regime,
    ]
    if feedback_path_arg is not None:
        runner_cmd.extend(["--feedback-path", str(feedback_path_arg)])
    if openclaw_agent_id:
        runner_cmd.extend(["--agent-id", openclaw_agent_id])
    if model_id:
        runner_cmd.extend(["--model-id", model_id])
    if provider_model:
        runner_cmd.extend(["--provider-model", provider_model])
    if retry_on_noop:
        runner_cmd.append("--retry-on-noop")
    runner_cmd.extend(["--prompt-variant", prompt_variant])
    if isinstance(feedback_artifact_paths, list):
        for p in feedback_artifact_paths:
            if isinstance(p, str) and p.strip():
                runner_cmd.extend(["--artifact-path", p])
    proc = subprocess.run(
        runner_cmd,
        capture_output=True,
        text=True,
        check=False,
    )

    if proc.returncode != 0:
        stderr = proc.stderr.strip() or proc.stdout.strip() or "unknown openclaw-minimal error"
        _append_revision_log(
            log_path=log_path,
            round_idx=round_idx,
            side=side,
            changed=False,
            old_aggression=old_aggression,
            new_aggression=old_aggression,
            reason=f"round_{previous_round} scorecard.left_right_winner={previous_winner}",
            executor="openclaw-minimal",
            success=False,
            changed_files=[],
            model_id=model_id,
            agent_id=openclaw_agent_id,
            provider_model=provider_model,
        )
        return False, f"openclaw-minimal revision failed: {stderr}"

    try:
        result = json.loads(proc.stdout.strip())
    except Exception:
        _append_revision_log(
            log_path=log_path,
            round_idx=round_idx,
            side=side,
            changed=False,
            old_aggression=old_aggression,
            new_aggression=old_aggression,
            reason=f"round_{previous_round} scorecard.left_right_winner={previous_winner}",
            executor="openclaw-minimal",
            success=False,
            changed_files=[],
            model_id=model_id,
            agent_id=openclaw_agent_id,
            provider_model=provider_model,
        )
        return False, "openclaw-minimal revision failed: invalid JSON result"

    new_aggression = _read_aggression_optional(submission_main_path)
    result_previous_winner = result.get("previous_winner") or previous_winner
    reason = f"round_{previous_round} scorecard.left_right_winner={result_previous_winner}"
    changed_files = result.get("changed_files", [])
    changed = bool(result.get("changed", False))
    success = bool(result.get("success", False))
    timeout_error = False
    context_overflow_error = bool(result.get("context_overflow_detected", False))
    error_text = str(result.get("error") or "")
    if "openclaw timeout" in error_text:
        timeout_error = True
    if "openclaw context overflow" in error_text.lower() or "context overflow" in error_text.lower():
        context_overflow_error = True
    audit_path = result.get("audit_path")
    if isinstance(audit_path, str) and audit_path:
        try:
            audit_payload = json.loads(Path(audit_path).read_text(encoding="utf-8"))
            errors = audit_payload.get("errors", [])
            if isinstance(errors, list) and any(isinstance(e, str) and "openclaw timeout" in e for e in errors):
                timeout_error = True
            if isinstance(errors, list) and any(isinstance(e, str) and "context overflow" in e.lower() for e in errors):
                context_overflow_error = True
            if bool(audit_payload.get("context_overflow_detected", False)):
                context_overflow_error = True
        except Exception:
            pass

    _append_revision_log(
        log_path=log_path,
        round_idx=round_idx,
        side=side,
        changed=changed,
        old_aggression=old_aggression,
        new_aggression=new_aggression,
        reason=reason,
        executor="openclaw-minimal",
        success=success,
        changed_files=changed_files,
        model_id=model_id,
        agent_id=openclaw_agent_id,
        provider_model=provider_model,
    )

    if timeout_error:
        return False, "openclaw timeout"
    if context_overflow_error:
        return False, "openclaw context overflow"
    if not success:
        if error_text:
            return False, f"openclaw-minimal revision failed: {error_text}"
        return False, "openclaw-minimal revision failed: unsuccessful result"
    if changed:
        if isinstance(old_aggression, int) and isinstance(new_aggression, int):
            return True, f"openclaw-minimal revision applied: AGGRESSION {old_aggression}->{new_aggression}"
        return True, "openclaw-minimal revision applied: submission/main.py changed"
    return True, "openclaw-minimal revision applied: AGGRESSION unchanged"


def _apply_openclaw_minimal_initial_synthesis(
    codebase_post_dir: Path,
    submission_main_path: Path,
    game: str,
    regime: str,
    log_path: Path,
    model_id: str | None = None,
    provider_model: str | None = None,
    openclaw_agent_id: str | None = None,
    retry_on_noop: bool = False,
    strategy_profile_id: str | None = None,
    strategy_profile_text: str | None = None,
    prompt_variant: str = "anti_draw_coached",
) -> tuple[bool, str]:
    old_aggression = _read_aggression_optional(submission_main_path)
    runner_cmd = [
        "python",
        "-m",
        "runner.core.openclaw_minimal",
        "--mode",
        "initial_synthesis",
        "--bootstrap",
        str(Path(__file__).with_name("openclaw_minimal_bootstrap.txt")),
        "--codebase-post-dir",
        str(codebase_post_dir),
        "--side",
        "left",
        "--game",
        game,
        "--regime",
        regime,
    ]
    if openclaw_agent_id:
        runner_cmd.extend(["--agent-id", openclaw_agent_id])
    if model_id:
        runner_cmd.extend(["--model-id", model_id])
    if provider_model:
        runner_cmd.extend(["--provider-model", provider_model])
    if retry_on_noop:
        runner_cmd.append("--retry-on-noop")
    runner_cmd.extend(["--prompt-variant", prompt_variant])
    if strategy_profile_id:
        runner_cmd.extend(["--strategy-profile-id", strategy_profile_id])
    if strategy_profile_text:
        runner_cmd.extend(["--strategy-profile-text", strategy_profile_text])

    proc = subprocess.run(
        runner_cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or proc.stdout.strip() or "unknown openclaw-minimal error"
        _append_revision_log(
            log_path=log_path,
            round_idx=0,
            side="initial",
            changed=False,
            old_aggression=old_aggression,
            new_aggression=old_aggression,
            reason="initial synthesis",
            executor="openclaw-minimal",
            success=False,
            changed_files=[],
            model_id=model_id,
            agent_id=openclaw_agent_id,
            provider_model=provider_model,
        )
        return False, f"openclaw-minimal initial synthesis failed: {stderr}"

    try:
        result = json.loads(proc.stdout.strip())
    except Exception:
        _append_revision_log(
            log_path=log_path,
            round_idx=0,
            side="initial",
            changed=False,
            old_aggression=old_aggression,
            new_aggression=old_aggression,
            reason="initial synthesis",
            executor="openclaw-minimal",
            success=False,
            changed_files=[],
            model_id=model_id,
            agent_id=openclaw_agent_id,
            provider_model=provider_model,
        )
        return False, "openclaw-minimal initial synthesis failed: invalid JSON result"

    new_aggression = _read_aggression_optional(submission_main_path)
    changed_files = result.get("changed_files", [])
    changed = bool(result.get("changed", False))
    success = bool(result.get("success", False))
    timeout_error = False
    context_overflow_error = bool(result.get("context_overflow_detected", False))
    error_text = str(result.get("error") or "")
    if "openclaw timeout" in error_text:
        timeout_error = True
    if "openclaw context overflow" in error_text.lower() or "context overflow" in error_text.lower():
        context_overflow_error = True
    audit_path = result.get("audit_path")
    if isinstance(audit_path, str) and audit_path:
        try:
            audit_payload = json.loads(Path(audit_path).read_text(encoding="utf-8"))
            errors = audit_payload.get("errors", [])
            if isinstance(errors, list) and any(isinstance(e, str) and "openclaw timeout" in e for e in errors):
                timeout_error = True
            if isinstance(errors, list) and any(isinstance(e, str) and "context overflow" in e.lower() for e in errors):
                context_overflow_error = True
            if bool(audit_payload.get("context_overflow_detected", False)):
                context_overflow_error = True
        except Exception:
            pass
    _append_revision_log(
        log_path=log_path,
        round_idx=0,
        side="initial",
        changed=changed,
        old_aggression=old_aggression,
        new_aggression=new_aggression,
        reason="initial synthesis",
        executor="openclaw-minimal",
        success=success,
        changed_files=changed_files if isinstance(changed_files, list) else [],
        model_id=model_id,
        agent_id=openclaw_agent_id,
        provider_model=provider_model,
    )
    if timeout_error:
        return False, "openclaw timeout"
    if context_overflow_error:
        return False, "openclaw context overflow"
    if not success:
        if error_text:
            return False, f"openclaw-minimal initial synthesis failed: {error_text}"
        return False, "openclaw-minimal initial synthesis failed: unsuccessful result"
    if changed:
        if isinstance(old_aggression, int) and isinstance(new_aggression, int):
            return True, f"openclaw-minimal initial synthesis applied: AGGRESSION {old_aggression}->{new_aggression}"
        return True, "openclaw-minimal initial synthesis applied: submission/main.py changed"
    return True, "openclaw-minimal initial synthesis applied: AGGRESSION unchanged"


def apply_minimal_revision(
    codebase_play_dir: Path,
    codebase_post_dir: Path,
    round_idx: int,
    side: str,
    game: str = "",
    regime: str = "",
    model_id: str | None = None,
    executor: str | None = None,
    openclaw_agent_id: str | None = None,
    provider_model: str | None = None,
    require_effective_submission_change: bool = False,
    revision_retry_on_noop: int = 0,
    revision_retry_on_timeout: int = 0,
    feedback_artifact_paths: list[str] | None = None,
    feedback_package_variant: str | None = None,
    feedback_visibility: str | None = None,
    round_match_records: list[dict[str, Any]] | None = None,
    prompt_variant: str = "anti_draw_coached",
    skip_copy_tree: bool = False,
) -> tuple[bool, str]:
    if skip_copy_tree:
        # The caller may have already staged the post codebase (e.g., to ensure feedback
        # packages exist even if revisions later fail). If the directory is missing, fall
        # back to a clean copy.
        if not codebase_post_dir.exists():
            copy_tree(codebase_play_dir, codebase_post_dir)
    else:
        copy_tree(codebase_play_dir, codebase_post_dir)

    submission_main_path = codebase_post_dir / "submission" / "main.py"
    notes_dir = codebase_post_dir / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)

    log_path = notes_dir / "revision_log.md"
    previous_winner = _read_feedback_winner(round_idx)

    # Feedback Package v3/v4 (CodeClash-style) is written into the post codebase so OpenClaw can
    # reference it as `codebase_post_t/feedback/round_<round>` during revision.
    if feedback_package_variant in {"codeclash_v3", "codeclash_v4"}:
        tournament_name, tournament_agent_id = _infer_post_context(codebase_post_dir)
        feedback_round_idx = _infer_codebase_post_round_idx(codebase_post_dir)
        norm_records = _normalize_round_match_records(round_match_records)
        if tournament_name and tournament_agent_id and feedback_round_idx is not None and norm_records:
            try:
                from runner.core.pommerman_feedback_package import write_feedback_package_for_agent

                write_feedback_package_for_agent(
                    tournament_name=tournament_name,
                    round_idx=feedback_round_idx,
                    agent_id=tournament_agent_id,
                    round_match_records=norm_records,
                    feedback_visibility=feedback_visibility or "own_matches_plus_public_scoreboard",
                    feedback_package_variant=feedback_package_variant or "codeclash_v3",
                )
            except Exception:
                # Fail-open for now: feedback package generation should not break revisions.
                pass

    # Real model runs must be fail-closed and never fall back to rule-minimal.
    if model_id:
        current_aggression = _read_aggression_optional(submission_main_path)
        if not executor:
            _append_revision_log(
                log_path=log_path,
                round_idx=round_idx,
                side=side,
                changed=False,
                old_aggression=current_aggression,
                new_aggression=current_aggression,
                reason="missing executor for model-backed revision",
                executor="unknown",
                success=False,
                changed_files=[],
                model_id=model_id,
                agent_id=openclaw_agent_id,
                provider_model=provider_model,
            )
            return False, "minimal revision failed: missing executor for model-backed revision"
        if executor != "openclaw-minimal":
            _append_revision_log(
                log_path=log_path,
                round_idx=round_idx,
                side=side,
                changed=False,
                old_aggression=current_aggression,
                new_aggression=current_aggression,
                reason=f"unsupported executor for model-backed revision: {executor}",
                executor=executor,
                success=False,
                changed_files=[],
                model_id=model_id,
                agent_id=openclaw_agent_id,
                provider_model=provider_model,
            )
            return False, f"minimal revision failed: unsupported executor '{executor}' for model-backed revision"

    # Smoke/pilot runs without model metadata may use rule-minimal.
    # OpenClaw is selected whenever executor is openclaw-minimal or agent id is provided.
    use_openclaw_minimal = bool(openclaw_agent_id) or executor == "openclaw-minimal"
    if use_openclaw_minimal:
        retries = max(0, int(revision_retry_on_noop or 0)) if require_effective_submission_change else 0
        timeout_retries = max(0, int(revision_retry_on_timeout or 0))
        before_hash = _sha256_file(submission_main_path)
        last_msg = "openclaw-minimal revision failed: unknown error"
        for attempt in range(retries + 1):
            ok, msg = _apply_openclaw_minimal_revision(
                codebase_post_dir=codebase_post_dir,
                submission_main_path=submission_main_path,
                round_idx=round_idx,
                side=side,
                game=game,
                regime=regime,
                previous_winner=previous_winner,
                log_path=log_path,
                model_id=model_id,
                provider_model=provider_model,
                openclaw_agent_id=openclaw_agent_id,
                retry_on_noop=attempt > 0,
                feedback_artifact_paths=feedback_artifact_paths,
                prompt_variant=prompt_variant,
            )
            last_msg = msg
            if not ok:
                msg_l = msg.lower()
                if ("timeout" in msg_l or "context overflow" in msg_l) and attempt < timeout_retries:
                    continue
                if "submission contract validation failed" in msg_l and attempt < retries:
                    continue
                return ok, msg
            if not require_effective_submission_change:
                return ok, msg
            after_hash = _sha256_file(submission_main_path)
            if before_hash != after_hash:
                return ok, msg
            if attempt < retries:
                continue
        return False, "OpenClaw revision made no effective submission/main.py change"

    return _apply_rule_revision(
        submission_main_path=submission_main_path,
        round_idx=round_idx,
        side=side,
        previous_winner=previous_winner,
        log_path=log_path,
        model_id=model_id,
        agent_id=openclaw_agent_id,
        provider_model=provider_model,
    )


def apply_minimal_initial_synthesis(
    starter_codebase_dir: Path,
    codebase_post_dir: Path,
    *,
    game: str = "",
    regime: str = "",
    model_id: str | None = None,
    executor: str | None = None,
    openclaw_agent_id: str | None = None,
    provider_model: str | None = None,
    require_effective_submission_change: bool = False,
    initial_synthesis_retry_on_noop: int = 0,
    initial_synthesis_retry_on_timeout: int = 0,
    strategy_profile_id: str | None = None,
    strategy_profile_text: str | None = None,
    prompt_variant: str = "anti_draw_coached",
) -> tuple[bool, str]:
    copy_tree(starter_codebase_dir, codebase_post_dir)

    submission_main_path = codebase_post_dir / "submission" / "main.py"
    notes_dir = codebase_post_dir / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    log_path = notes_dir / "revision_log.md"
    current_aggression = _read_aggression_optional(submission_main_path)

    if not executor:
        _append_revision_log(
            log_path=log_path,
            round_idx=0,
            side="initial",
            changed=False,
            old_aggression=current_aggression,
            new_aggression=current_aggression,
            reason="missing executor for initial synthesis",
            executor="unknown",
            success=False,
            changed_files=[],
            model_id=model_id,
            agent_id=openclaw_agent_id,
            provider_model=provider_model,
        )
        return False, "initial synthesis failed: missing executor"
    if executor != "openclaw-minimal":
        _append_revision_log(
            log_path=log_path,
            round_idx=0,
            side="initial",
            changed=False,
            old_aggression=current_aggression,
            new_aggression=current_aggression,
            reason=f"unsupported executor for initial synthesis: {executor}",
            executor=executor,
            success=False,
            changed_files=[],
            model_id=model_id,
            agent_id=openclaw_agent_id,
            provider_model=provider_model,
        )
        return False, f"initial synthesis failed: unsupported executor '{executor}'"

    retries = max(0, int(initial_synthesis_retry_on_noop or 0)) if require_effective_submission_change else 0
    timeout_retries = max(0, int(initial_synthesis_retry_on_timeout or 0))
    before_hash = _sha256_file(submission_main_path)
    last_msg = "openclaw-minimal initial synthesis failed: unknown error"
    for attempt in range(retries + 1):
        ok, msg = _apply_openclaw_minimal_initial_synthesis(
            codebase_post_dir=codebase_post_dir,
            submission_main_path=submission_main_path,
            game=game,
            regime=regime,
            log_path=log_path,
            model_id=model_id,
            provider_model=provider_model,
            openclaw_agent_id=openclaw_agent_id,
            retry_on_noop=attempt > 0,
            strategy_profile_id=strategy_profile_id,
            strategy_profile_text=strategy_profile_text,
            prompt_variant=prompt_variant,
        )
        last_msg = msg
        if not ok:
            msg_l = msg.lower()
            if ("timeout" in msg_l or "context overflow" in msg_l) and attempt < timeout_retries:
                continue
            if "submission contract validation failed" in msg_l and attempt < retries:
                continue
            return ok, msg
        if not require_effective_submission_change:
            return ok, msg
        after_hash = _sha256_file(submission_main_path)
        if before_hash != after_hash:
            return ok, msg
        if attempt < retries:
            continue
    return False, "OpenClaw initial synthesis made no effective submission/main.py change"


def apply_noop_revision(
    codebase_play_dir: Path,
    codebase_post_dir: Path,
    round_idx: int,
    side: str,
) -> tuple[bool, str]:
    """Backward-compatible no-op revision used by smoke tests.

    Copies codebase_play_dir to codebase_post_dir and appends a minimal
    revision log entry without changing the submission.
    """
    copy_tree(codebase_play_dir, codebase_post_dir)

    notes_dir = codebase_post_dir / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    log_path = notes_dir / "revision_log.md"

    prev = ""
    if log_path.exists():
        prev = log_path.read_text(encoding="utf-8")

    prev += f"\n- round_{round_idx}: noop revision for {side}\n"
    log_path.write_text(prev, encoding="utf-8")

    return True, "noop revision applied"

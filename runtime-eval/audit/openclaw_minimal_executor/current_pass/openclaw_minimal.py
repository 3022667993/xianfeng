from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


OPENCLAW_DIR = Path(os.environ.get("OPENCLAW_DIR", "/root/autodl-tmp/external/openclaw"))
OPENCLAW_TIMEOUT_SECONDS = int(os.environ.get("OPENCLAW_AGENT_TIMEOUT", "600"))

ALLOWED_TOOLS = {"read", "write", "edit", "exec"}

FORBIDDEN_TOOL_PREFIXES = (
    "web_",
    "sessions_",
)

FORBIDDEN_TOOLS_EXACT = {
    "process",
    "canvas",
    "nodes",
    "cron",
    "message",
    "tts",
    "gateway",
    "agents_list",
    "subagents",
    "session_status",
}

FORBIDDEN_BOOTSTRAP_NAMES = {
    "SOUL.md",
    "HEARTBEAT.md",
    "BOOTSTRAP.md",
    "MEMORY.md",
}

FORBIDDEN_WORKSPACE_FILES = {
    "SOUL.md",
    "HEARTBEAT.md",
    "BOOTSTRAP.md",
    "BOOT.md",
    "MEMORY.md",
}

ALLOWED_CHANGED_FILES = {
    "submission/main.py",
}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _safe_rel(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def _snapshot_files(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    if not root.exists():
        return snapshot
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = _safe_rel(path, root)
        snapshot[rel] = _sha256_file(path)
    return snapshot


def _changed_files(before: dict[str, str], after: dict[str, str]) -> list[str]:
    keys = sorted(set(before) | set(after))
    return [key for key in keys if before.get(key) != after.get(key)]


def _extract_json_object(text: str) -> dict[str, Any]:
    """Extract a JSON object from OpenClaw stdout.

    Preferred target is the outer `openclaw agent --json` object containing
    payloads/meta/systemPromptReport. If stdout instead contains only the
    assistant-visible JSON, return that too; the audit layer will fail closed
    when systemPromptReport is absent.
    """
    decoder = json.JSONDecoder()
    candidates: list[tuple[int, int, dict[str, Any]]] = []

    for idx, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, end = decoder.raw_decode(text[idx:])
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue

        score = 0
        if "payloads" in obj:
            score += 10
        if "meta" in obj:
            score += 10
        meta = obj.get("meta")
        if isinstance(meta, dict) and "systemPromptReport" in meta:
            score += 30
        if isinstance(meta, dict) and "agentMeta" in meta:
            score += 10

        candidates.append((score, end, obj))

    if not candidates:
        raise ValueError("no JSON object found in OpenClaw output")

    # Prefer the real OpenClaw wrapper. If absent, return the largest/most
    # complete JSON object and let audit fail closed.
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def _run_openclaw_agent(message: str) -> tuple[dict[str, Any] | None, str, str, int]:
    commands = [
        [
            "pnpm",
            "openclaw",
            "agent",
            "--agent",
            "main",
            "--message",
            message,
            "--json",
            "--local",
            "--timeout",
            str(OPENCLAW_TIMEOUT_SECONDS),
        ],
        [
            "node",
            "openclaw.mjs",
            "agent",
            "--agent",
            "main",
            "--message",
            message,
            "--json",
            "--local",
            "--timeout",
            str(OPENCLAW_TIMEOUT_SECONDS),
        ],
    ]

    last_stdout = ""
    last_stderr = ""
    last_code = 127

    for cmd in commands:
        exe = cmd[0]
        if shutil.which(exe) is None:
            continue

        env = os.environ.copy()
        env.setdefault(
            "OPENCLAW_BOOTSTRAP_BASENAMES",
            "AGENTS.md,TOOLS.md,IDENTITY.md,USER.md",
        )

        proc = subprocess.run(
            cmd,
            cwd=OPENCLAW_DIR,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=OPENCLAW_TIMEOUT_SECONDS + 30,
        )

        last_stdout = proc.stdout
        last_stderr = proc.stderr
        last_code = proc.returncode

        if proc.returncode == 0:
            combined_output = proc.stdout + "\n" + proc.stderr
            return _extract_json_object(combined_output), proc.stdout, proc.stderr, proc.returncode

    return None, last_stdout, last_stderr, last_code


def _make_revision_message(
    *,
    bootstrap_text: str,
    run_dir: Path,
    codebase_post_t_dir: Path,
    feedback_copy_path: Path,
    side: str,
    game: str,
    regime: str,
) -> str:
    return f"""You are OpenClaw-Minimal running inside a controlled runtime-eval revision executor.

IMPORTANT:
You are in a constrained one-shot revision smoke.
Do not use web tools.
Do not use subagents or session tools.
Do not run shell commands in this run.
Do not write memory notes, analysis logs, test logs, or extra artifacts.
Only modify the allowed file listed below.

Experiment:
- game: {game}
- regime: {regime}
- side: {side}
- run_dir: {run_dir}
- codebase_post_t_dir: {codebase_post_t_dir}
- feedback_package_path: {feedback_copy_path}

Bootstrap contract:
{bootstrap_text}

Task:
- Read feedback from: {feedback_copy_path}
- Inspect bot code at: {codebase_post_t_dir / "submission/main.py"}
- For Pommerman A00, revise the bot based on the feedback.
- Only modify: {codebase_post_t_dir / "submission/main.py"}
- Do not modify: {codebase_post_t_dir / "notes/revision_log.md"}
- The runner will write revision_log.md separately.
- Do not create or modify any other file.

In your final response, briefly state what you changed.
"""


def _audit_openclaw_response(
    response: dict[str, Any] | None,
    *,
    minimal_workspace: Path,
) -> dict[str, Any]:
    meta = (response or {}).get("meta", {}) if isinstance(response, dict) else {}
    report = meta.get("systemPromptReport", {}) if isinstance(meta, dict) else {}

    injected = report.get("injectedWorkspaceFiles", [])
    injected_summary = []
    forbidden_injected = []

    if isinstance(injected, list):
        for item in injected:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            missing = bool(item.get("missing", False))
            injected_chars = int(item.get("injectedChars", 0) or 0)
            entry = {
                "name": name,
                "path": item.get("path"),
                "missing": missing,
                "rawChars": item.get("rawChars"),
                "injectedChars": injected_chars,
                "truncated": item.get("truncated"),
            }
            injected_summary.append(entry)

            if name in FORBIDDEN_BOOTSTRAP_NAMES:
                forbidden_injected.append(entry)

    tools_report = report.get("tools", {})
    tools_entries = tools_report.get("entries", []) if isinstance(tools_report, dict) else []
    tool_names = []
    forbidden_tools = []

    if isinstance(tools_entries, list):
        for item in tools_entries:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not isinstance(name, str):
                continue
            tool_names.append(name)
            if (
                name not in ALLOWED_TOOLS
                or name in FORBIDDEN_TOOLS_EXACT
                or any(name.startswith(prefix) for prefix in FORBIDDEN_TOOL_PREFIXES)
            ):
                forbidden_tools.append(name)

    real_forbidden_workspace_files = []
    for rel in sorted(FORBIDDEN_WORKSPACE_FILES):
        path = minimal_workspace / rel
        if path.exists():
            real_forbidden_workspace_files.append(str(path))

    state_path = minimal_workspace / ".openclaw" / "workspace-state.json"
    if state_path.exists():
        real_forbidden_workspace_files.append(str(state_path))

    return {
        "provider": meta.get("agentMeta", {}).get("provider") if isinstance(meta.get("agentMeta"), dict) else None,
        "model": meta.get("agentMeta", {}).get("model") if isinstance(meta.get("agentMeta"), dict) else None,
        "workspaceDir": report.get("workspaceDir"),
        "injectedWorkspaceFiles": injected_summary,
        "forbiddenInjectedWorkspaceFiles": forbidden_injected,
        "toolNames": tool_names,
        "forbiddenTools": sorted(set(forbidden_tools)),
        "skills": report.get("skills"),
        "realForbiddenWorkspaceFiles": real_forbidden_workspace_files,
        "finalAssistantVisibleText": meta.get("finalAssistantVisibleText"),
        "stopReason": meta.get("stopReason"),
        "executionTrace": meta.get("executionTrace"),
        "rawSystemPromptReportPresent": bool(report),
    }


def _write_audit(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _cleanup_minimal_workspace_forbidden_files(minimal_workspace: Path) -> None:
    for rel in sorted(FORBIDDEN_WORKSPACE_FILES):
        target = minimal_workspace / rel
        if target.is_file():
            target.unlink(missing_ok=True)
    state_path = minimal_workspace / ".openclaw" / "workspace-state.json"
    if state_path.is_file():
        state_path.unlink(missing_ok=True)


def _list_files(root: Path) -> list[str]:
    if not root.exists():
        return []
    return [_safe_rel(p, root) for p in sorted(p for p in root.rglob("*") if p.is_file())]


def _copy_allowed_changes_back(
    *,
    src_codebase_post_t: Path,
    dst_codebase_post_dir: Path,
    changed_files: list[str],
) -> None:
    for rel in changed_files:
        src = src_codebase_post_t / rel
        dst = dst_codebase_post_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _extract_previous_winner(feedback_data: Any) -> str | None:
    if not isinstance(feedback_data, dict):
        return None
    scorecard = feedback_data.get("scorecard")
    if not isinstance(scorecard, dict):
        return None
    value = scorecard.get("left_right_winner")
    if value in {"left", "right", "draw"}:
        return value
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap", required=True)
    parser.add_argument("--codebase-post-dir", required=True)
    parser.add_argument("--feedback-path", required=True)
    parser.add_argument("--side", required=True)
    parser.add_argument("--game", required=True)
    parser.add_argument("--regime", required=True)
    args = parser.parse_args()

    started_at = time.time()

    bootstrap_path = Path(args.bootstrap).resolve()
    codebase_post_dir = Path(args.codebase_post_dir).resolve()
    feedback_path = Path(args.feedback_path).resolve()
    minimal_workspace = Path("/root/autodl-tmp/runtime-eval/openclaw_workspaces/minimal")
    runtime_runs_root = minimal_workspace / "runtime_eval_runs"

    audit_path = codebase_post_dir / "revision_audit.json"

    runtime_runs_root.mkdir(parents=True, exist_ok=True)
    _cleanup_minimal_workspace_forbidden_files(minimal_workspace)

    run_id = f"{int(started_at)}_{os.getpid()}_{hashlib.sha256(str(time.time_ns()).encode('utf-8')).hexdigest()[:10]}"
    run_dir = runtime_runs_root / run_id
    run_codebase_post_t = run_dir / "codebase_post_t"
    run_feedback_copy = run_dir / "feedback_package.json"
    run_backup_original = run_dir / "codebase_post_original_backup"

    errors: list[str] = []
    response: dict[str, Any] | None = None
    stdout = ""
    stderr = ""
    returncode = 127
    feedback_data: dict[str, Any] | None = None
    changed_files_temp: list[str] = []
    disallowed_changed_files: list[str] = []
    original_changed_unexpectedly: list[str] = []
    run_dir_file_list_before_cleanup: list[str] = []
    system_prompt_report: dict[str, Any] | None = None
    audit: dict[str, Any] = {}
    previous_winner: str | None = None

    try:
        bootstrap_text = bootstrap_path.read_text(encoding="utf-8")
        feedback_data = json.loads(feedback_path.read_text(encoding="utf-8"))
        previous_winner = _extract_previous_winner(feedback_data)

        run_dir.mkdir(parents=True, exist_ok=False)
        shutil.copytree(codebase_post_dir, run_codebase_post_t)
        shutil.copy2(feedback_path, run_feedback_copy)
        shutil.copytree(codebase_post_dir, run_backup_original)

        before_temp_snapshot = _snapshot_files(run_codebase_post_t)
        before_original_snapshot = _snapshot_files(codebase_post_dir)

        message = _make_revision_message(
            bootstrap_text=bootstrap_text,
            run_dir=run_dir,
            codebase_post_t_dir=run_codebase_post_t,
            feedback_copy_path=run_feedback_copy,
            side=args.side,
            game=args.game,
            regime=args.regime,
        )

        response, stdout, stderr, returncode = _run_openclaw_agent(message)

        after_temp_snapshot = _snapshot_files(run_codebase_post_t)
        changed_files_temp = _changed_files(before_temp_snapshot, after_temp_snapshot)
        disallowed_changed_files = sorted(
            [rel for rel in changed_files_temp if rel not in ALLOWED_CHANGED_FILES]
        )

        after_original_snapshot = _snapshot_files(codebase_post_dir)
        original_changed_unexpectedly = _changed_files(before_original_snapshot, after_original_snapshot)

        if original_changed_unexpectedly:
            # Restore fail-closed if OpenClaw touched original files directly.
            if codebase_post_dir.exists():
                shutil.rmtree(codebase_post_dir)
            shutil.copytree(run_backup_original, codebase_post_dir)

        audit = _audit_openclaw_response(response, minimal_workspace=minimal_workspace)
        meta = (response or {}).get("meta", {}) if isinstance(response, dict) else {}
        if isinstance(meta, dict) and isinstance(meta.get("systemPromptReport"), dict):
            system_prompt_report = meta.get("systemPromptReport")

        if returncode != 0:
            errors.append(f"openclaw agent failed with returncode={returncode}")
        if response is None:
            errors.append("openclaw agent did not return parseable JSON")
        if not audit.get("rawSystemPromptReportPresent"):
            errors.append("missing systemPromptReport in OpenClaw JSON")
        if audit.get("forbiddenInjectedWorkspaceFiles"):
            errors.append("forbidden injected workspace files present")
        if audit.get("forbiddenTools"):
            errors.append("forbidden tools present")
        if audit.get("realForbiddenWorkspaceFiles"):
            errors.append("forbidden real workspace files present")
        if disallowed_changed_files:
            errors.append("disallowed changed files present")
        if original_changed_unexpectedly:
            errors.append("original codebase_post_dir changed unexpectedly during isolated run")

        success = len(errors) == 0

        if success and changed_files_temp:
            _copy_allowed_changes_back(
                src_codebase_post_t=run_codebase_post_t,
                dst_codebase_post_dir=codebase_post_dir,
                changed_files=changed_files_temp,
            )

        changed = success and len(changed_files_temp) > 0

        run_dir_file_list_before_cleanup = _list_files(run_dir)

        final_audit = {
            "executor": "openclaw-minimal",
            "mode": "revision-executor",
            "success": success,
            "errors": errors,
            "startedAtUnix": started_at,
            "durationSeconds": round(time.time() - started_at, 3),
            "runId": run_id,
            "runDir": str(run_dir),
            "game": args.game,
            "regime": args.regime,
            "side": args.side,
            "bootstrapPath": str(bootstrap_path),
            "feedbackPath": str(feedback_path),
            "feedbackCopyPath": str(run_feedback_copy),
            "codebasePostDir": str(codebase_post_dir),
            "codebasePostTempDir": str(run_codebase_post_t),
            "feedbackRound": feedback_data.get("meta", {}).get("round_idx") if isinstance(feedback_data, dict) else None,
            "previousWinner": previous_winner,
            "scorecard": feedback_data.get("scorecard", {}) if isinstance(feedback_data, dict) else {},
            "openclawDir": str(OPENCLAW_DIR),
            "openclawReturnCode": returncode,
            "openclawStdoutTail": stdout[-4000:],
            "openclawStderrTail": stderr[-4000:],
            "systemPromptReport": system_prompt_report,
            "openclawAudit": audit,
            "allowedChangedFiles": sorted(ALLOWED_CHANGED_FILES),
            "changedFilesTemp": changed_files_temp,
            "disallowedChangedFiles": disallowed_changed_files,
            "originalChangedUnexpectedly": original_changed_unexpectedly,
            "changedFiles": changed_files_temp if success else [],
            "runDirFileListBeforeCleanup": run_dir_file_list_before_cleanup,
        }
        _write_audit(audit_path, final_audit)

        result = {
            "executor": "openclaw-minimal",
            "success": success,
            "changed": changed,
            "changed_files": changed_files_temp if success else [],
            "audit_path": str(audit_path),
            "provider": audit.get("provider"),
            "model": audit.get("model"),
            "previous_winner": previous_winner,
            "error": "; ".join(errors) if errors else None,
        }
        print(json.dumps(result, ensure_ascii=False))
        return

    except Exception as exc:
        # Fail closed on exceptions; do not copy any temporary edits back.
        run_dir_file_list_before_cleanup = _list_files(run_dir)
        final_audit = {
            "executor": "openclaw-minimal",
            "mode": "revision-executor",
            "success": False,
            "errors": [repr(exc)],
            "startedAtUnix": started_at,
            "durationSeconds": round(time.time() - started_at, 3),
            "runId": run_id,
            "runDir": str(run_dir),
            "game": args.game,
            "regime": args.regime,
            "side": args.side,
            "bootstrapPath": str(bootstrap_path),
            "feedbackPath": str(feedback_path),
            "previousWinner": previous_winner,
            "codebasePostDir": str(codebase_post_dir),
            "changedFiles": [],
            "runDirFileListBeforeCleanup": run_dir_file_list_before_cleanup,
        }
        _write_audit(audit_path, final_audit)

        print(
            json.dumps(
                {
                    "executor": "openclaw-minimal",
                    "success": False,
                    "changed": False,
                    "changed_files": [],
                    "audit_path": str(audit_path),
                    "provider": audit.get("provider"),
                    "model": audit.get("model"),
                    "previous_winner": previous_winner,
                    "error": repr(exc),
                },
                ensure_ascii=False,
            )
        )
        return
    finally:
        _cleanup_minimal_workspace_forbidden_files(minimal_workspace)
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)


if __name__ == "__main__":
    main()

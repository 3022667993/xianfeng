from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
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
    codebase_post_dir: Path,
    feedback_path: Path,
    side: str,
    game: str,
    regime: str,
) -> str:
    return f"""You are OpenClaw-Minimal running inside a controlled runtime-eval audit.

IMPORTANT:
This is an AUDIT-ONLY one-shot executor smoke.
Do not edit files.
Do not create files.
Do not run commands.
Return a concise JSON object only.

Experiment:
- game: {game}
- regime: {regime}
- side: {side}
- codebase_post_dir: {codebase_post_dir}
- feedback_path: {feedback_path}

Bootstrap contract:
{bootstrap_text}

Task:
Confirm that you understand the revision task, but do not perform the revision in this audit-only run.

Return exactly JSON:
{{"understood": true, "would_edit": false}}
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

    audit_path = codebase_post_dir / "revision_audit.json"

    before_snapshot = _snapshot_files(codebase_post_dir)

    with tempfile.TemporaryDirectory(prefix="openclaw_minimal_backup_") as tmp:
        backup_dir = Path(tmp) / "codebase_post_backup"
        shutil.copytree(codebase_post_dir, backup_dir)

        try:
            bootstrap_text = bootstrap_path.read_text(encoding="utf-8")
            feedback_data = json.loads(feedback_path.read_text(encoding="utf-8"))

            message = _make_revision_message(
                bootstrap_text=bootstrap_text,
                codebase_post_dir=codebase_post_dir,
                feedback_path=feedback_path,
                side=args.side,
                game=args.game,
                regime=args.regime,
            )

            response, stdout, stderr, returncode = _run_openclaw_agent(message)

            after_agent_snapshot = _snapshot_files(codebase_post_dir)
            model_changed_files = _changed_files(before_snapshot, after_agent_snapshot)

            audit = _audit_openclaw_response(response, minimal_workspace=minimal_workspace)

            errors = []
            if returncode != 0:
                errors.append(f"openclaw agent failed with returncode={returncode}")
            if response is None:
                errors.append("openclaw agent did not return parseable JSON")
            if not audit.get("rawSystemPromptReportPresent"):
                errors.append("missing systemPromptReport in OpenClaw JSON")
            if audit["forbiddenInjectedWorkspaceFiles"]:
                errors.append("forbidden injected workspace files present")
            if audit["forbiddenTools"]:
                errors.append("forbidden tools present")
            if audit["realForbiddenWorkspaceFiles"]:
                errors.append("forbidden real workspace files present")
            if model_changed_files:
                errors.append("audit-only run changed files unexpectedly")

            success = len(errors) == 0

            # Fail closed: never keep model-side file changes from this audit-only run.
            if codebase_post_dir.exists():
                shutil.rmtree(codebase_post_dir)
            shutil.copytree(backup_dir, codebase_post_dir)

            final_audit = {
                "executor": "openclaw-minimal",
                "mode": "audit-first-one-shot",
                "success": success,
                "errors": errors,
                "startedAtUnix": started_at,
                "durationSeconds": round(time.time() - started_at, 3),
                "game": args.game,
                "regime": args.regime,
                "side": args.side,
                "bootstrapPath": str(bootstrap_path),
                "feedbackPath": str(feedback_path),
                "codebasePostDir": str(codebase_post_dir),
                "feedbackRound": feedback_data.get("meta", {}).get("round_idx") if isinstance(feedback_data, dict) else None,
                "scorecard": feedback_data.get("scorecard", {}) if isinstance(feedback_data, dict) else {},
                "openclawDir": str(OPENCLAW_DIR),
                "openclawReturnCode": returncode,
                "openclawStdoutTail": stdout[-4000:],
                "openclawStderrTail": stderr[-4000:],
                "openclawAudit": audit,
                "changedFilesObservedBeforeFailClosedRestore": model_changed_files,
                "changedFiles": [],
                "note": (
                    "This executor intentionally fails closed until the OpenClaw tool surface "
                    "matches OpenClaw-Minimal. It does not preserve model edits from audit-only runs."
                ),
            }

            _write_audit(audit_path, final_audit)

            result = {
                "executor": "openclaw-minimal",
                "success": success,
                "changed": False,
                "changed_files": [],
                "audit_path": str(audit_path),
                "error": "; ".join(errors) if errors else None,
                "provider": audit.get("provider"),
                "model": audit.get("model"),
            }
            print(json.dumps(result, ensure_ascii=False))
            return

        except Exception as exc:
            if codebase_post_dir.exists():
                shutil.rmtree(codebase_post_dir)
            shutil.copytree(backup_dir, codebase_post_dir)

            final_audit = {
                "executor": "openclaw-minimal",
                "mode": "audit-first-one-shot",
                "success": False,
                "errors": [repr(exc)],
                "startedAtUnix": started_at,
                "durationSeconds": round(time.time() - started_at, 3),
                "game": args.game,
                "regime": args.regime,
                "side": args.side,
                "bootstrapPath": str(bootstrap_path),
                "feedbackPath": str(feedback_path),
                "codebasePostDir": str(codebase_post_dir),
                "changedFiles": [],
            }
            _write_audit(audit_path, final_audit)

            print(json.dumps({
                "executor": "openclaw-minimal",
                "success": False,
                "changed": False,
                "changed_files": [],
                "audit_path": str(audit_path),
                "error": repr(exc),
            }, ensure_ascii=False))
            return


if __name__ == "__main__":
    main()

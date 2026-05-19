from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from subprocess import TimeoutExpired
from pathlib import Path
from typing import Any


OPENCLAW_DIR = Path(os.environ.get("OPENCLAW_DIR", "/root/autodl-tmp/external/openclaw"))
OPENCLAW_TIMEOUT_SECONDS = int(os.environ.get("OPENCLAW_AGENT_TIMEOUT", "600"))
OPENCLAW_BASE_STATE_DIR = Path(
    os.environ.get("OPENCLAW_STATE_DIR", str(Path.home() / ".openclaw"))
).expanduser().resolve()

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
DEFAULT_OPENCLAW_PLACEHOLDERS = {
    "SOUL.md",
    "BOOTSTRAP.md",
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

IGNORED_GENERATED_CHANGED_SEGMENTS = {
    "__pycache__",
}

IGNORED_BOOKKEEPING_CHANGED_FILES = {
    "notes/revision_log.md",
    "revision_audit.json",
}

ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
CONTEXT_OVERFLOW_RE = re.compile(r"context\s+overflow", flags=re.IGNORECASE)
ESTIMATED_PROMPT_TOKENS_RE = re.compile(r"estimatedPromptTokens\s*(?:=|≈)\s*([0-9][0-9,]*)", flags=re.IGNORECASE)
PROMPT_BUDGET_BEFORE_RESERVE_RE = re.compile(
    r"promptBudgetBeforeReserve\s*(?:=|≈)\s*([0-9][0-9,]*)",
    flags=re.IGNORECASE,
)


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


def _is_ignored_changed_file(rel: str) -> bool:
    rel_norm = rel.replace("\\", "/")
    if rel_norm in IGNORED_BOOKKEEPING_CHANGED_FILES:
        return True
    if rel_norm.endswith(".pyc"):
        return True
    parts = Path(rel_norm).parts
    if any(part in IGNORED_GENERATED_CHANGED_SEGMENTS for part in parts):
        return True
    return False


def _classify_changed_files(changed_files_temp: list[str]) -> tuple[list[str], list[str], list[str]]:
    ignored: list[str] = []
    disallowed: list[str] = []
    copy_back: list[str] = []
    for rel in changed_files_temp:
        if _is_ignored_changed_file(rel):
            ignored.append(rel)
            continue
        if rel in ALLOWED_CHANGED_FILES:
            copy_back.append(rel)
            continue
        disallowed.append(rel)
    return sorted(copy_back), sorted(ignored), sorted(disallowed)


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


def _strip_ansi(text: str) -> str:
    if not isinstance(text, str):
        return ""
    return ANSI_ESCAPE_RE.sub("", text)


def _first_int_from_pattern(text: str, pattern: re.Pattern[str]) -> int | None:
    match = pattern.search(text)
    if match is None:
        return None
    raw = match.group(1)
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except Exception:
        return None


def _extract_context_overflow_metadata(
    response: dict[str, Any] | None,
    *,
    stdout: str,
    stderr: str,
) -> dict[str, Any]:
    meta_error_kind = None
    if isinstance(response, dict):
        meta = response.get("meta")
        if isinstance(meta, dict):
            err = meta.get("error")
            if isinstance(err, dict):
                kind = err.get("kind")
                if isinstance(kind, str) and kind.strip():
                    meta_error_kind = kind.strip()

    combined = _strip_ansi(f"{stdout}\n{stderr}")
    context_overflow_detected = bool(meta_error_kind == "context_overflow" or CONTEXT_OVERFLOW_RE.search(combined))
    prompt_estimated_tokens = _first_int_from_pattern(combined, ESTIMATED_PROMPT_TOKENS_RE)
    prompt_budget_before_reserve = _first_int_from_pattern(combined, PROMPT_BUDGET_BEFORE_RESERVE_RE)
    return {
        "context_overflow_detected": context_overflow_detected,
        "prompt_estimated_tokens": prompt_estimated_tokens,
        "prompt_budget_before_reserve": prompt_budget_before_reserve,
    }


def _resolve_source_openclaw_config_path(source_state_dir: Path) -> Path | None:
    raw = os.environ.get("OPENCLAW_CONFIG_PATH")
    if isinstance(raw, str) and raw.strip():
        candidate = Path(raw.strip()).expanduser()
        try:
            candidate = candidate.resolve()
        except Exception:
            candidate = candidate.absolute()
        if candidate.exists() and candidate.is_file():
            return candidate
    fallback = source_state_dir / "openclaw.json"
    if fallback.exists() and fallback.is_file():
        return fallback
    return None


def _seed_isolated_openclaw_state(
    *,
    isolated_state_dir: Path,
    agent_id: str,
) -> tuple[Path | None, list[str]]:
    warnings: list[str] = []
    isolated_state_dir.mkdir(parents=True, exist_ok=True)
    source_state_dir = OPENCLAW_BASE_STATE_DIR

    source_config = _resolve_source_openclaw_config_path(source_state_dir)
    isolated_config_path = isolated_state_dir / "openclaw.json"
    if source_config is not None:
        isolated_config_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_config, isolated_config_path)
    else:
        warnings.append("source_openclaw_config_missing")
        isolated_config_path = None

    src_agent_dir = source_state_dir / "agents" / agent_id / "agent"
    dst_agent_dir = isolated_state_dir / "agents" / agent_id / "agent"
    if src_agent_dir.exists() and src_agent_dir.is_dir():
        dst_agent_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src_agent_dir, dst_agent_dir, dirs_exist_ok=True)
    else:
        warnings.append(f"source_agent_dir_missing:{src_agent_dir}")

    (isolated_state_dir / "agents" / agent_id / "sessions").mkdir(parents=True, exist_ok=True)
    return isolated_config_path, warnings


def _run_openclaw_agent(
    message: str,
    *,
    agent_id: str,
    provider_model: str | None = None,
    session_id: str | None = None,
    session_state_dir: Path | None = None,
    session_config_path: Path | None = None,
) -> tuple[dict[str, Any] | None, str, str, int]:
    commands = [
        [
            "pnpm",
            "openclaw",
            "agent",
            "--agent",
            agent_id,
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
            agent_id,
            "--message",
            message,
            "--json",
            "--local",
            "--timeout",
            str(OPENCLAW_TIMEOUT_SECONDS),
        ],
    ]
    if provider_model:
        for cmd in commands:
            cmd.extend(["--model", provider_model])
    if session_id:
        for cmd in commands:
            cmd.extend(["--session-id", session_id])

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
        if session_state_dir is not None:
            env["OPENCLAW_STATE_DIR"] = str(session_state_dir.resolve())
        if session_config_path is not None:
            env["OPENCLAW_CONFIG_PATH"] = str(session_config_path.resolve())

        try:
            proc = subprocess.run(
                cmd,
                cwd=OPENCLAW_DIR,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=OPENCLAW_TIMEOUT_SECONDS + 30,
            )
        except TimeoutExpired as exc:
            last_stdout = exc.stdout or ""
            last_stderr = exc.stderr or ""
            last_code = -1
            return None, last_stdout, last_stderr, last_code

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
    feedback_copy_path: Path | None,
    feedback_package_path: Path | None = None,
    side: str,
    game: str,
    regime: str,
    retry_on_noop: bool = False,
    extra_artifact_paths: list[str] | None = None,
    prompt_variant: str = "anti_draw_coached",
) -> str:
    retry_suffix = ""
    if retry_on_noop:
        retry_suffix = (
            "\nRetry requirement:\n"
            "- Previous attempt made no submitted-code change.\n"
            "- You must edit submission/main.py.\n"
            "- Do not only write notes or audit files.\n"
        )
    extra_artifacts_block = ""
    if prompt_variant != "neutral" and isinstance(extra_artifact_paths, list) and extra_artifact_paths:
        rendered = []
        for p in extra_artifact_paths:
            if isinstance(p, str) and p.strip():
                rendered.append(f"  - {p}")
        if rendered:
            extra_artifacts_block = "  - additional round artifacts provided by runner:\n" + "\n".join(rendered) + "\n"
    feedback_copy_line = ""
    if prompt_variant != "neutral" and feedback_copy_path is not None:
        feedback_copy_line = f"- Read feedback from: {feedback_copy_path}\n"
    feedback_package_task_line = ""
    if feedback_package_path is not None:
        feedback_package_task_line = f"- Use the feedback package at: {feedback_package_path}\n"
    else:
        feedback_package_task_line = "- feedback package: unavailable\n"
    feedback_package_line = f"- feedback_package_path: {feedback_package_path}" if feedback_package_path is not None else "- feedback_package_path: unavailable"
    prefix = f"""You are OpenClaw-Minimal running inside a controlled runtime-eval revision executor.

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
{feedback_package_line}

Bootstrap contract:
{bootstrap_text}

Task:
{feedback_copy_line}{feedback_package_task_line}- Inspect the provided feedback package and the current codebase state.
{extra_artifacts_block}- Do not rely on a long list of internal artifact paths.
- Inspect bot code at: {codebase_post_t_dir / "submission/main.py"}
- For Pommerman A00, revise the bot based on the feedback.
- Only modify: {codebase_post_t_dir / "submission/main.py"}
- Do not modify: {codebase_post_t_dir / "notes/revision_log.md"}
- The runner will write revision_log.md separately.
- Do not create or modify any other file.
- You must modify submission/main.py; metadata-only edits do not count.
- notes/revision_log.md alone does not count as a valid revision.
- Keep submission runnable.
- Make a small, concrete strategy change based on feedback.
"""
    if prompt_variant == "anti_draw_coached":
        variant_block = """- Treat 800-step draw outcomes as a failure signal.
- The objective is to increase non-draw win probability, not only survival.
- If the previous round was all draws, you must make a concrete anti-draw strategy change in submission/main.py.
- Encourage safe aggression while preserving survival:
  - move toward center when safe
  - clear wood for powerups
  - use bombs when an escape path exists
  - pressure opponent when nearby and safe
  - avoid endless corner camping
  - reduce STOP usage unless unsafe
- Keep survival safeguards strict; do not add suicidal aggression.
- In your final response, explicitly state:
  - what anti-draw behavior was added
  - what safety guard prevents suicide
"""
    elif prompt_variant == "neutral":
        variant_block = """- Objective: improve expected future tournament outcome under the provided feedback package and constraints.
- Use the feedback package, public scoreboard, match replay evidence, action logs, and run logs as evidence to understand what happened in previous matches.
- Then update `submission/main.py` with a concrete strategy or behavior change intended to improve future tournament outcomes against opponents.
- Prefer wins over draws, and draws over losses.
- If the previous result was already favorable, look for ways to make the behavior more robust, consistent, or resilient in future matches.
- Treat timeout draws and cases where `submitted_pair_outcome` reports that both submitted agents lost to a dummy/background agent as unfavorable signals when better outcomes may be possible.
- The feedback package is evidence, not a hand-authored strategy script.
- Keep changes functional and behaviorally meaningful; do not submit only refactors, renames, comments, or metadata-only changes.
"""
    else:
        raise ValueError(f"unsupported prompt_variant: {prompt_variant}")
    return prefix + variant_block + f"""{retry_suffix}

In your final response, briefly state what you changed.
"""


def _make_initial_synthesis_message(
    *,
    bootstrap_text: str,
    run_dir: Path,
    codebase_post_t_dir: Path,
    game: str,
    regime: str,
    retry_on_noop: bool = False,
    strategy_profile_id: str | None = None,
    strategy_profile_text: str | None = None,
    prompt_variant: str = "anti_draw_coached",
) -> str:
    retry_suffix = ""
    if retry_on_noop:
        retry_suffix = (
            "\nRetry requirement:\n"
            "- Previous attempt made no submitted-code change.\n"
            "- You must edit submission/main.py.\n"
            "- Do not only write notes or audit files.\n"
        )
    profile_id = strategy_profile_id or "default_profile"
    profile_text = strategy_profile_text or "balanced survivability and safe progression"
    prefix = f"""You are OpenClaw-Minimal running inside a controlled runtime-eval initial synthesis executor.

IMPORTANT:
You are in a constrained one-shot initial synthesis smoke.
Do not use web tools.
Do not use subagents or session tools.
Do not run shell commands in this run.
Do not write memory notes, analysis logs, test logs, or extra artifacts.
Only modify the allowed file listed below.

Experiment:
- game: {game}
- regime: {regime}
- run_dir: {run_dir}
- codebase_post_t_dir: {codebase_post_t_dir}
- initial synthesis mode: no match feedback is available yet
- assigned strategy profile id: {profile_id}
- assigned strategy profile: {profile_text}

Bootstrap contract:
{bootstrap_text}

Task:
- You are creating the first Pommerman agent from the shared starter repo.
- The starter `submission/main.py` is intentionally minimal and only provides the required API plus a valid fallback action.
- The required API includes `make_agent()` returning an instance of a class that subclasses `pommerman.agents.BaseAgent`.
- This agent has a distinct assigned strategy profile.
- Replace the minimal fallback with a concrete strategy or behavior implementation in submission/main.py.
- Preserve a valid `make_agent()` entry point and `pommerman.agents.BaseAgent` inheritance.
- Do not copy a generic template unchanged.
- The submitted code should be meaningfully different from the starter and should reflect the assigned profile.
- Inspect bot code at: {codebase_post_t_dir / "submission/main.py"}
- Only modify: {codebase_post_t_dir / "submission/main.py"}
- Keep the public agent API unchanged and runnable.
- Implement a deterministic, survivable, non-passive strategy.
"""
    if prompt_variant == "anti_draw_coached":
        variant_block = """- Treat 800-step draw behavior as a failure mode to avoid in design.
- Maximize chance of non-draw wins while preserving survival and deterministic behavior.
- Encode explicit anti-draw behavior:
  - move toward center when safe
  - clear wood for powerups
  - use bombs when an escape path exists
  - pressure nearby opponents when safe
  - avoid endless corner camping
  - reduce STOP usage unless unsafe
- In your final response, explicitly state:
  - what anti-draw behavior was added
  - what safety guard prevents suicide
"""
    elif prompt_variant == "neutral":
        variant_block = """- Objective: improve expected future tournament outcome while preserving valid actions, determinism, and survival constraints.
- Prefer wins over draws, and draws over losses.
- Design and implement a concrete behavior or strategy in `submission/main.py` intended to improve future performance against opponents.
- A timeout draw is not a strong success signal if better outcomes are possible.
- If both submitted agents lose to a dummy/background agent, treat that as an unfavorable outcome, not as a satisfactory draw.
- Avoid obvious self-destruction and keep the submission valid.
- Do not submit only refactors, renames, comments, or metadata-only changes.
"""
    else:
        raise ValueError(f"unsupported prompt_variant: {prompt_variant}")
    suffix = f"""- Handle missing observation fields defensively.
- Avoid self-trapping.
- Use bombs only with an escape path.
- Ensure build/test/smoke compatibility.
- Do not modify scripts/run_arena.sh, scripts/build.sh, tests, configs, or metadata files.
- Do not rely on full board replay or hidden files.
- Metadata-only edits do not count.
- You must edit submission/main.py.
- In your final response, briefly state what you changed.
{retry_suffix}
"""
    return prefix + variant_block + suffix


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
    default_missing_placeholders = []

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
                if name in DEFAULT_OPENCLAW_PLACEHOLDERS and missing:
                    default_missing_placeholders.append(name)
                else:
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

    skills = report.get("skills")
    skills_prompt_chars = 0
    if isinstance(skills, dict):
        skills_prompt_chars = int(skills.get("promptChars", 0) or 0)

    return {
        "provider": meta.get("agentMeta", {}).get("provider") if isinstance(meta.get("agentMeta"), dict) else None,
        "model": meta.get("agentMeta", {}).get("model") if isinstance(meta.get("agentMeta"), dict) else None,
        "workspaceDir": report.get("workspaceDir"),
        "injectedWorkspaceFiles": injected_summary,
        "forbiddenInjectedWorkspaceFiles": forbidden_injected,
        "toolNames": tool_names,
        "forbiddenTools": sorted(set(forbidden_tools)),
        "skills": skills,
        "skillsPromptChars": skills_prompt_chars,
        "realForbiddenWorkspaceFiles": real_forbidden_workspace_files,
        "openclawDefaultMissingPlaceholders": sorted(set(default_missing_placeholders)),
        "finalAssistantVisibleText": meta.get("finalAssistantVisibleText"),
        "stopReason": meta.get("stopReason"),
        "executionTrace": meta.get("executionTrace"),
        "rawSystemPromptReportPresent": bool(report),
    }


def _provider_route_status(requested_provider_model: str | None, execution_trace: Any) -> tuple[str, str | None, str | None]:
    if not isinstance(execution_trace, dict):
        return "unknown", None, None
    actual_provider = execution_trace.get("winnerProvider")
    actual_model = execution_trace.get("winnerModel")
    if not isinstance(actual_provider, str) or not isinstance(actual_model, str):
        return "unknown", actual_provider if isinstance(actual_provider, str) else None, actual_model if isinstance(actual_model, str) else None
    if not requested_provider_model:
        return "unknown", actual_provider, actual_model
    req = requested_provider_model.lower()
    am = actual_model.lower()
    ap = actual_provider.lower()
    req_token = req.split("/", 1)[-1]
    if req_token in am or req_token in ap:
        return "matched", actual_provider, actual_model
    return "mismatch", actual_provider, actual_model


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
    parser.add_argument("--mode", choices=["revision", "initial_synthesis"], default="revision")
    parser.add_argument("--bootstrap", required=True)
    parser.add_argument("--codebase-post-dir", required=True)
    parser.add_argument("--feedback-path", required=False)
    parser.add_argument("--round-idx", required=False, type=int)
    parser.add_argument("--side", required=True)
    parser.add_argument("--game", required=True)
    parser.add_argument("--regime", required=True)
    parser.add_argument(
        "--agent-id",
        default=os.environ.get("RUNTIME_EVAL_OPENCLAW_AGENT_ID", "main"),
    )
    parser.add_argument("--model-id", required=False)
    parser.add_argument("--provider-model", required=False)
    parser.add_argument("--retry-on-noop", action="store_true")
    parser.add_argument("--prompt-variant", choices=["anti_draw_coached", "neutral"], default="anti_draw_coached")
    parser.add_argument("--artifact-path", action="append", default=[])
    parser.add_argument("--strategy-profile-id", required=False)
    parser.add_argument("--strategy-profile-text", required=False)
    args = parser.parse_args()

    started_at = time.time()

    bootstrap_path = Path(args.bootstrap).resolve()
    codebase_post_dir = Path(args.codebase_post_dir).resolve()
    feedback_path = Path(args.feedback_path).resolve() if args.feedback_path else None
    minimal_workspace = Path("/root/autodl-tmp/runtime-eval/openclaw_workspaces/minimal")
    runtime_runs_root = minimal_workspace / "runtime_eval_runs"

    audit_path = codebase_post_dir / "revision_audit.json"

    runtime_runs_root.mkdir(parents=True, exist_ok=True)
    _cleanup_minimal_workspace_forbidden_files(minimal_workspace)

    run_id = f"{int(started_at)}_{os.getpid()}_{hashlib.sha256(str(time.time_ns()).encode('utf-8')).hexdigest()[:10]}"
    agent_id = str(args.agent_id).strip() or "main"
    model_id = str(args.model_id).strip() if args.model_id is not None else None
    provider_model = str(args.provider_model).strip() if args.provider_model is not None else None
    if model_id == "":
        model_id = None
    if provider_model == "":
        provider_model = None
    run_dir = runtime_runs_root / run_id
    run_codebase_post_t = run_dir / "codebase_post_t"
    run_feedback_copy = run_dir / "feedback_package.json"
    run_backup_original = run_dir / "codebase_post_original_backup"
    openclaw_session_state_dir = run_dir / "openclaw_home"
    openclaw_session_config_path: Path | None = None
    openclaw_isolation_warnings: list[str] = []
    openclaw_session_isolated = False
    openclaw_session_id = (
        "runtime-eval-"
        + hashlib.sha256(
            f"{run_id}:{agent_id}:{time.time_ns()}".encode("utf-8")
        ).hexdigest()[:24]
    )

    errors: list[str] = []
    response: dict[str, Any] | None = None
    stdout = ""
    stderr = ""
    returncode = 127
    feedback_data: dict[str, Any] | None = None
    changed_files_temp: list[str] = []
    copy_back_changed_files: list[str] = []
    ignored_changed_files: list[str] = []
    disallowed_changed_files: list[str] = []
    original_changed_unexpectedly: list[str] = []
    run_dir_file_list_before_cleanup: list[str] = []
    system_prompt_report: dict[str, Any] | None = None
    audit: dict[str, Any] = {}
    previous_winner: str | None = None
    timeout_seconds = OPENCLAW_TIMEOUT_SECONDS + 30
    context_overflow_detected = False
    prompt_estimated_tokens: int | None = None
    prompt_budget_before_reserve: int | None = None

    try:
        bootstrap_text = bootstrap_path.read_text(encoding="utf-8")
        if args.mode == "revision":
            if feedback_path is not None:
                feedback_data = json.loads(feedback_path.read_text(encoding="utf-8"))
                previous_winner = _extract_previous_winner(feedback_data)
        else:
            feedback_data = {"meta": {"round_idx": 0}, "scorecard": {"left_right_winner": "draw"}}
            previous_winner = None

        run_dir.mkdir(parents=True, exist_ok=False)
        shutil.copytree(codebase_post_dir, run_codebase_post_t)
        if feedback_path is not None and args.prompt_variant != "neutral":
            shutil.copy2(feedback_path, run_feedback_copy)
        shutil.copytree(codebase_post_dir, run_backup_original)
        openclaw_session_config_path, openclaw_isolation_warnings = _seed_isolated_openclaw_state(
            isolated_state_dir=openclaw_session_state_dir,
            agent_id=agent_id,
        )
        openclaw_session_isolated = True

        before_temp_snapshot = _snapshot_files(run_codebase_post_t)
        before_original_snapshot = _snapshot_files(codebase_post_dir)

        if args.mode == "initial_synthesis":
            message = _make_initial_synthesis_message(
                bootstrap_text=bootstrap_text,
                run_dir=run_dir,
                codebase_post_t_dir=run_codebase_post_t,
                game=args.game,
                regime=args.regime,
                retry_on_noop=bool(args.retry_on_noop),
                strategy_profile_id=args.strategy_profile_id,
                strategy_profile_text=args.strategy_profile_text,
                prompt_variant=args.prompt_variant,
            )
        else:
            feedback_package_path = None
            if args.round_idx is not None:
                candidate = run_codebase_post_t / "feedback" / f"round_{int(args.round_idx)}"
                if candidate.exists():
                    feedback_package_path = candidate
            message = _make_revision_message(
                bootstrap_text=bootstrap_text,
                run_dir=run_dir,
                codebase_post_t_dir=run_codebase_post_t,
                feedback_copy_path=run_feedback_copy if run_feedback_copy.exists() else None,
                feedback_package_path=feedback_package_path,
                side=args.side,
                game=args.game,
                regime=args.regime,
                retry_on_noop=bool(args.retry_on_noop),
                extra_artifact_paths=[str(x) for x in (args.artifact_path or [])],
                prompt_variant=args.prompt_variant,
            )

        response, stdout, stderr, returncode = _run_openclaw_agent(
            message,
            agent_id=agent_id,
            provider_model=provider_model,
            session_id=openclaw_session_id,
            session_state_dir=openclaw_session_state_dir,
            session_config_path=openclaw_session_config_path,
        )
        overflow_meta = _extract_context_overflow_metadata(
            response,
            stdout=stdout,
            stderr=stderr,
        )
        context_overflow_detected = bool(overflow_meta.get("context_overflow_detected"))
        prompt_estimated_tokens = overflow_meta.get("prompt_estimated_tokens")
        prompt_budget_before_reserve = overflow_meta.get("prompt_budget_before_reserve")

        after_temp_snapshot = _snapshot_files(run_codebase_post_t)
        changed_files_temp = _changed_files(before_temp_snapshot, after_temp_snapshot)
        copy_back_changed_files, ignored_changed_files, disallowed_changed_files = _classify_changed_files(changed_files_temp)

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
            if returncode == -1 and "timed out" not in " ".join(errors):
                errors.append("openclaw timeout")
            else:
                errors.append(f"openclaw agent failed with returncode={returncode}")
        if context_overflow_detected:
            errors.append("openclaw context overflow")
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
        if int(audit.get("skillsPromptChars", 0) or 0) > 0:
            errors.append("skills prompt must be empty for openclaw-minimal")
        if disallowed_changed_files:
            errors.append("disallowed changed files present")
        if original_changed_unexpectedly:
            errors.append("original codebase_post_dir changed unexpectedly during isolated run")

        provider_route_status, actual_provider, actual_model = _provider_route_status(
            provider_model,
            audit.get("executionTrace"),
        )
        success = len(errors) == 0

        if success and copy_back_changed_files:
            _copy_allowed_changes_back(
                src_codebase_post_t=run_codebase_post_t,
                dst_codebase_post_dir=codebase_post_dir,
                changed_files=copy_back_changed_files,
            )

        changed = success and len(copy_back_changed_files) > 0

        run_dir_file_list_before_cleanup = _list_files(run_dir)

        final_audit = {
            "executor": "openclaw-minimal",
            "mode": "revision-executor" if args.mode == "revision" else "initial-synthesis-executor",
            "success": success,
            "errors": errors,
            "startedAtUnix": started_at,
            "durationSeconds": round(time.time() - started_at, 3),
            "runId": run_id,
            "agentId": agent_id,
            "modelId": model_id,
            "providerModel": provider_model,
            "requestedProviderModel": provider_model,
            "actualProvider": actual_provider,
            "actualModel": actual_model,
            "providerRouteStatus": provider_route_status,
            "runDir": str(run_dir),
            "openclaw_session_isolated": openclaw_session_isolated,
            "openclaw_session_state_dir": str(openclaw_session_state_dir),
            "openclaw_session_config_path": str(openclaw_session_config_path) if openclaw_session_config_path is not None else None,
            "openclaw_session_id": openclaw_session_id,
            "openclaw_isolation_warnings": openclaw_isolation_warnings,
            "context_overflow_detected": context_overflow_detected,
            "prompt_estimated_tokens": prompt_estimated_tokens,
            "prompt_budget_before_reserve": prompt_budget_before_reserve,
            "game": args.game,
            "regime": args.regime,
            "side": args.side,
            "bootstrapPath": str(bootstrap_path),
            "feedbackPath": str(feedback_path) if feedback_path is not None else None,
            "feedbackCopyPath": str(run_feedback_copy) if feedback_path is not None else None,
            "codebasePostDir": str(codebase_post_dir),
            "codebasePostTempDir": str(run_codebase_post_t),
            "feedbackRound": feedback_data.get("meta", {}).get("round_idx") if isinstance(feedback_data, dict) else None,
            "previousWinner": previous_winner,
            "scorecard": feedback_data.get("scorecard", {}) if isinstance(feedback_data, dict) else {},
            "openclawDir": str(OPENCLAW_DIR),
            "openclawReturnCode": returncode,
            "openclawTimeoutSeconds": timeout_seconds,
            "openclawTimeout": returncode == -1,
            "openclawStdoutTail": stdout[-4000:],
            "openclawStderrTail": stderr[-4000:],
            "systemPromptReport": system_prompt_report,
            "openclawAudit": audit,
            "openclawDefaultMissingPlaceholders": audit.get("openclawDefaultMissingPlaceholders", []),
            "allowedChangedFiles": sorted(ALLOWED_CHANGED_FILES),
            "changedFilesTemp": changed_files_temp,
            "ignoredChangedFiles": ignored_changed_files,
            "disallowedChangedFiles": disallowed_changed_files,
            "originalChangedUnexpectedly": original_changed_unexpectedly,
            "changedFiles": copy_back_changed_files if success else [],
            "runDirFileListBeforeCleanup": run_dir_file_list_before_cleanup,
        }
        _write_audit(audit_path, final_audit)

        result = {
            "executor": "openclaw-minimal",
            "mode": args.mode,
            "success": success,
            "changed": changed,
            "changed_files": copy_back_changed_files if success else [],
            "agent_id": agent_id,
            "model_id": model_id,
            "provider_model": provider_model,
            "requested_provider_model": provider_model,
            "audit_path": str(audit_path),
            "provider": audit.get("provider"),
            "model": audit.get("model"),
            "actual_provider": actual_provider,
            "actual_model": actual_model,
            "provider_route_status": provider_route_status,
            "openclaw_timeout": returncode == -1,
            "openclaw_timeout_seconds": timeout_seconds,
            "openclaw_session_isolated": openclaw_session_isolated,
            "openclaw_session_state_dir": str(openclaw_session_state_dir),
            "openclaw_session_id": openclaw_session_id,
            "openclaw_isolation_warnings": openclaw_isolation_warnings,
            "context_overflow_detected": context_overflow_detected,
            "prompt_estimated_tokens": prompt_estimated_tokens,
            "prompt_budget_before_reserve": prompt_budget_before_reserve,
            "openclaw_default_missing_placeholders": audit.get("openclawDefaultMissingPlaceholders", []),
            "audit_warnings": [],
            "audit_errors": errors,
            "ignored_changed_files": ignored_changed_files,
            "changed_files_temp": changed_files_temp,
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
            "mode": "revision-executor" if args.mode == "revision" else "initial-synthesis-executor",
            "success": False,
            "errors": [repr(exc)],
            "startedAtUnix": started_at,
            "durationSeconds": round(time.time() - started_at, 3),
            "runId": run_id,
            "agentId": agent_id,
            "modelId": model_id,
            "providerModel": provider_model,
            "requestedProviderModel": provider_model,
            "runDir": str(run_dir),
            "openclaw_session_isolated": openclaw_session_isolated,
            "openclaw_session_state_dir": str(openclaw_session_state_dir),
            "openclaw_session_config_path": str(openclaw_session_config_path) if openclaw_session_config_path is not None else None,
            "openclaw_session_id": openclaw_session_id,
            "openclaw_isolation_warnings": openclaw_isolation_warnings,
            "context_overflow_detected": context_overflow_detected,
            "prompt_estimated_tokens": prompt_estimated_tokens,
            "prompt_budget_before_reserve": prompt_budget_before_reserve,
            "game": args.game,
            "regime": args.regime,
            "side": args.side,
            "bootstrapPath": str(bootstrap_path),
            "feedbackPath": str(feedback_path) if feedback_path is not None else None,
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
                    "mode": args.mode,
                    "success": False,
                    "changed": False,
                    "changed_files": [],
                    "agent_id": agent_id,
                    "model_id": model_id,
                    "provider_model": provider_model,
                    "requested_provider_model": provider_model,
                    "audit_path": str(audit_path),
                    "provider": audit.get("provider"),
                    "model": audit.get("model"),
                    "actual_provider": None,
                    "actual_model": None,
                    "provider_route_status": "unknown",
                    "openclaw_timeout": True,
                    "openclaw_timeout_seconds": timeout_seconds,
                    "openclawTimeoutSeconds": timeout_seconds,
                    "openclaw_session_isolated": openclaw_session_isolated,
                    "openclaw_session_state_dir": str(openclaw_session_state_dir),
                    "openclaw_session_id": openclaw_session_id,
                    "openclaw_isolation_warnings": openclaw_isolation_warnings,
                    "context_overflow_detected": context_overflow_detected,
                    "prompt_estimated_tokens": prompt_estimated_tokens,
                    "prompt_budget_before_reserve": prompt_budget_before_reserve,
                    "openclaw_default_missing_placeholders": [],
                    "audit_warnings": [],
                    "audit_errors": [repr(exc)],
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

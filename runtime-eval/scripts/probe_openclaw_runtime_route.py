from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from runner.core import openclaw_minimal as ocm


def _tail(s: str, n: int = 4000) -> str:
    return s[-n:] if isinstance(s, str) else ""


def probe_runtime_route(provider_model: str) -> dict:
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    probe_root = logs_dir / "_runtime_route_probe_tmp"
    if probe_root.exists():
        shutil.rmtree(probe_root)
    codebase_post_dir = probe_root / "codebase_post_t"
    feedback_path = probe_root / "feedback_package.json"
    notes_dir = codebase_post_dir / "notes"
    submission_dir = codebase_post_dir / "submission"
    notes_dir.mkdir(parents=True, exist_ok=True)
    submission_dir.mkdir(parents=True, exist_ok=True)
    (submission_dir / "main.py").write_text("AGGRESSION = 0\n", encoding="utf-8")
    (notes_dir / "revision_log.md").write_text("# Revision Log\n", encoding="utf-8")
    feedback_path.write_text(
        json.dumps({"meta": {"round_idx": 1}, "scorecard": {"left_right_winner": "draw"}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    bootstrap_path = REPO_ROOT / "runner/core/openclaw_minimal_bootstrap.txt"
    bootstrap_text = bootstrap_path.read_text(encoding="utf-8")
    message = ocm._make_revision_message(
        bootstrap_text=bootstrap_text,
        run_dir=probe_root,
        codebase_post_t_dir=codebase_post_dir,
        feedback_copy_path=feedback_path,
        side="left",
        game="pommerman_1v1",
        regime="A00",
    )
    response, stdout, stderr, return_code = ocm._run_openclaw_agent(
        message,
        agent_id="main",
        provider_model=provider_model,
    )
    parseable_json = response is not None
    audit = ocm._audit_openclaw_response(response, minimal_workspace=Path("/root/autodl-tmp/runtime-eval/openclaw_workspaces/minimal"))
    provider_route_status, actual_provider, actual_model = ocm._provider_route_status(provider_model, audit.get("executionTrace"))
    errors: list[str] = []
    if return_code != 0:
        errors.append(f"openclaw_returncode={return_code}")
    if not parseable_json:
        errors.append("openclaw_json_unparseable")
    if provider_route_status != "matched":
        errors.append(f"provider_route_status={provider_route_status}")
    payload = {
        "requested_provider_model": provider_model,
        "actual_provider": actual_provider,
        "actual_model": actual_model,
        "provider_route_status": provider_route_status,
        "openclaw_return_code": return_code,
        "parseable_json": parseable_json,
        "errors": errors,
        "stderr_tail": _tail(stderr),
    }
    if errors:
        payload["stdout_tail"] = _tail(stdout)
    out = Path("logs/openclaw_runtime_route_probe.json")
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        shutil.rmtree(probe_root)
    except Exception:
        pass
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    result = probe_runtime_route(args.model)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("errors"):
        print("openclaw_runtime_route_probe=FAIL")
        return 1
    print("openclaw_runtime_route_probe=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

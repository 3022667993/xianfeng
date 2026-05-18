from __future__ import annotations

import json
from pathlib import Path


UNSUPPORTED_TICK_CLAIMS = {
    "bomb_count",
    "death_step",
    "powerups",
    "invalid_actions",
}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def audit_process_feedback(logs_root: Path = Path("logs")) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    round_dirs = sorted(p for p in logs_root.glob("round_*") if p.is_dir())
    if not round_dirs:
        errors.append("no round directories found under logs/")
        return errors, warnings

    for rd in round_dirs:
        for match_dir in sorted(p for p in rd.glob("match_*") if p.is_dir()):
            md_path = match_dir / "metadata.json"
            if not md_path.exists():
                continue
            md = _load_json(md_path)
            left = md.get("left_agent_id")
            right = md.get("right_agent_id")
            if not isinstance(left, str) or not isinstance(right, str):
                errors.append(f"{match_dir}: invalid tested agent ids in metadata")
                continue

            ts_path = match_dir / "trajectory_summary.json"
            if not ts_path.exists():
                errors.append(f"{match_dir}: missing trajectory_summary.json")
                continue
            ts = _load_json(ts_path)
            if ts.get("schema_version") != "pommerman_process_feedback_v1":
                errors.append(f"{match_dir}: trajectory summary schema_version mismatch")

            expected_agents = {left, right}
            json_files = sorted(match_dir.glob("agent_feedback_*.json"))
            md_files = sorted(match_dir.glob("agent_feedback_*.md"))
            if len(json_files) != 2:
                errors.append(f"{match_dir}: expected exactly two agent_feedback_*.json files")
            if len(md_files) != 2:
                errors.append(f"{match_dir}: expected exactly two agent_feedback_*.md files")

            for bad in ["agent_feedback_dummy2.json", "agent_feedback_dummy3.json", "agent_feedback_dummy2.md", "agent_feedback_dummy3.md"]:
                if (match_dir / bad).exists():
                    errors.append(f"{match_dir}: dummy feedback file must not exist: {bad}")

            for jf in json_files:
                payload = _load_json(jf)
                if payload.get("schema_version") != "pommerman_agent_feedback_v1":
                    errors.append(f"{jf}: schema_version mismatch")
                agent_id = payload.get("agent_id")
                if agent_id not in expected_agents:
                    errors.append(f"{jf}: agent_id must be one of tested agents")
                src = payload.get("source_files", {})
                for k in ["metadata", "scorecard", "arena_result_match_a", "arena_result_match_b", "trajectory_summary"]:
                    p = src.get(k)
                    if not isinstance(p, str) or not Path(p).exists():
                        errors.append(f"{jf}: source file missing for {k}")
                limitations = payload.get("limitations", [])
                lim_text = "\n".join(limitations).lower() if isinstance(limitations, list) else ""
                compact = payload.get("compact_trajectory_v2")
                compact_present = isinstance(compact, dict)
                mode_a_required = [
                    "process_feedback_v1 is derived from result-level arena artifacts only",
                    "tick-level actions, board states, bomb events, and death causes are not yet recorded",
                ]
                mode_b_required = [
                    "process_feedback_v1 is derived from result-level arena artifacts and compact trajectory v2 when available",
                    "compact trajectory v2 records lightweight per-step actions/rewards/alive/positions/counts when available",
                    "full board states, full observations, death causes, bomb ownership, and power-up pickup causes are not yet recorded",
                ]
                if compact_present:
                    for req in mode_b_required:
                        if req.lower() not in lim_text:
                            errors.append(f"{jf}: compact-v2 limitation text missing: {req}")
                else:
                    for req in mode_a_required:
                        if req.lower() not in lim_text:
                            errors.append(f"{jf}: v1 limitation text missing: {req}")

                md_path = match_dir / f"agent_feedback_{agent_id}.md"
                if md_path.exists():
                    md_lim_text = md_path.read_text(encoding="utf-8").lower()
                    if compact_present:
                        if "compact trajectory v2 records lightweight per-step actions/rewards/alive/positions/counts when available" not in md_lim_text:
                            errors.append(f"{md_path}: compact-v2 limitation text missing")
                        if "tick-level actions, board states, bomb events, and death causes are not yet recorded" in md_lim_text:
                            errors.append(f"{md_path}: old v1-only tick-level limitation must not appear in compact-v2 mode")
                    else:
                        if "tick-level actions, board states, bomb events, and death causes are not yet recorded" not in md_lim_text:
                            errors.append(f"{md_path}: v1 limitation text missing")
                as_text = json.dumps(payload, ensure_ascii=False).lower()
                for token in UNSUPPORTED_TICK_CLAIMS:
                    if token in as_text:
                        errors.append(f"{jf}: unsupported tick-level claim token found: {token}")
                diag = payload.get("diagnostics", {})
                if isinstance(diag, dict):
                    for k in ["bomb_action_rate", "stop_action_rate", "average_terminal_step", "non_draw_match_count"]:
                        if k not in diag:
                            errors.append(f"{jf}: missing diagnostics.{k}")
            for mf in md_files:
                txt = mf.read_text(encoding="utf-8").lower()
                for token in UNSUPPORTED_TICK_CLAIMS:
                    if token in txt:
                        errors.append(f"{mf}: unsupported tick-level claim token found: {token}")

    return errors, warnings


def main() -> int:
    errors, warnings = audit_process_feedback()
    for w in warnings:
        print(f"WARN {w}")
    if errors:
        print("pommerman_process_feedback_audit=FAIL")
        for e in errors:
            print(f"ERROR {e}")
        return 1
    print("pommerman_process_feedback_audit=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

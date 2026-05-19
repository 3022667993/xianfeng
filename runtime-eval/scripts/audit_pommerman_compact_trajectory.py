from __future__ import annotations

import json
from pathlib import Path

FORBIDDEN_KEYS = {"board", "observation", "observations", "raw_obs", "full_board"}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_jsonl(path: Path):
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except Exception as exc:
            raise ValueError(f"{path}: invalid jsonl line {i}: {exc}")
        if not isinstance(payload, dict):
            raise ValueError(f"{path}: jsonl line {i} is not an object")
        yield i, payload


def audit_compact_trajectory(logs_root: Path = Path("logs")) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    round_dirs = sorted(p for p in logs_root.glob("round_*") if p.is_dir())
    if not round_dirs:
        errors.append("no round directories found under logs/")
        return errors, warnings

    for rd in round_dirs:
        for md in sorted(p for p in rd.glob("match_*") if p.is_dir()):
            meta_path = md / "metadata.json"
            if not meta_path.exists():
                continue
            required = [
                md / "trajectory_compact_match_a.jsonl",
                md / "trajectory_events.json",
                md / "trajectory_summary.json",
            ]
            for p in required:
                if not p.exists():
                    errors.append(f"{md}: missing {p.name}")
            if errors:
                continue

            leg_path = md / "trajectory_compact_match_a.jsonl"
            try:
                for line_no, payload in _iter_jsonl(leg_path):
                    if payload.get("schema_version") != "pommerman_compact_trajectory_step_v2":
                        errors.append(f"{leg_path}: line {line_no} schema_version mismatch")
                    bad_keys = FORBIDDEN_KEYS & set(payload.keys())
                    if bad_keys:
                        errors.append(f"{leg_path}: line {line_no} contains forbidden keys: {sorted(bad_keys)}")
            except ValueError as exc:
                errors.append(str(exc))

            events = _load_json(md / "trajectory_events.json")
            if events.get("schema_version") != "pommerman_compact_trajectory_events_v2":
                errors.append(f"{md}: trajectory_events schema_version mismatch")
            lims = events.get("limitations", [])
            text = "\n".join(lims) if isinstance(lims, list) else ""
            if "does not store full board arrays" not in text:
                errors.append(f"{md}: trajectory_events limitations missing no-full-board statement")
            if "does not store full observations" not in text:
                errors.append(f"{md}: trajectory_events limitations missing no-full-observations statement")

            meta = _load_json(meta_path)
            left = meta.get("left_agent_id")
            right = meta.get("right_agent_id")
            for aid in [left, right]:
                if not isinstance(aid, str):
                    continue
                jf = md / f"agent_feedback_{aid}.json"
                mf = md / f"agent_feedback_{aid}.md"
                if not jf.exists() or not mf.exists():
                    errors.append(f"{md}: missing agent feedback artifacts for {aid}")
                    continue
                md_text = mf.read_text(encoding="utf-8")
                if "Compact Trajectory v2" not in md_text:
                    errors.append(f"{mf}: missing Compact Trajectory v2 section")
            for bad in ["agent_feedback_dummy2.json", "agent_feedback_dummy3.json", "agent_feedback_dummy2.md", "agent_feedback_dummy3.md"]:
                if (md / bad).exists():
                    errors.append(f"{md}: dummy feedback file must not exist: {bad}")

    return errors, warnings


def main() -> int:
    errors, warnings = audit_compact_trajectory()
    for w in warnings:
        print(f"WARN {w}")
    if errors:
        print("pommerman_compact_trajectory_audit=FAIL")
        for e in errors:
            print(f"ERROR {e}")
        return 1
    print("pommerman_compact_trajectory_audit=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

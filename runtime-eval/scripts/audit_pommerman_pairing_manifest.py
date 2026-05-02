from __future__ import annotations

import argparse
import json
from pathlib import Path


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_identity_ok(value: object) -> bool:
    return isinstance(value, str) and value not in {"left", "right"} and bool(value.strip())


def audit_manifest(workspace_root: Path, manifest_path: Path) -> tuple[list[str], list[str]]:
    data = _load_json(manifest_path)
    errors: list[str] = []
    warnings: list[str] = []

    if data.get("schema_version") != "pommerman_pairing_manifest_v1":
        errors.append("invalid schema_version")
    if data.get("game") != "pommerman_1v1":
        errors.append("game must be pommerman_1v1")
    if data.get("regime") != "A00":
        errors.append("regime must be A00")

    pairs = data.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        errors.append("pairs must be non-empty list")
        return errors, warnings

    for pair in pairs:
        pid = pair.get("pair_id", "pair")
        agent_a = pair.get("agent_A")
        agent_b = pair.get("agent_B")
        if not _is_identity_ok(agent_a):
            errors.append(f"{pid}: invalid agent_A identity")
        if not _is_identity_ok(agent_b):
            errors.append(f"{pid}: invalid agent_B identity")
        if pair.get("background_agents") != ["dummy2", "dummy3"]:
            errors.append(f"{pid}: background_agents must be ['dummy2','dummy3']")

        legs = pair.get("legs")
        if not isinstance(legs, list) or len(legs) != 2:
            errors.append(f"{pid}: exactly two legs required")
            continue

        leg1 = next((x for x in legs if x.get("leg") == 1), None)
        leg2 = next((x for x in legs if x.get("leg") == 2), None)
        if leg1 is None or leg2 is None:
            errors.append(f"{pid}: missing leg 1 or leg 2")
            continue

        if leg1.get("agent_A_seat") != "left" or leg1.get("agent_B_seat") != "right":
            errors.append(f"{pid}: leg_1 must be A-left/B-right")
        if leg2.get("agent_A_seat") != "right" or leg2.get("agent_B_seat") != "left":
            errors.append(f"{pid}: leg_2 must be A-right/B-left")

        for leg in [leg1, leg2]:
            label = f"{pid}:leg_{leg.get('leg')}"
            rpath = leg.get("result_path")
            apath = leg.get("arena_result_path")
            if not isinstance(rpath, str) or not (workspace_root / rpath).exists():
                errors.append(f"{label}: result_path missing on disk")
            if not isinstance(apath, str) or not (workspace_root / apath).exists():
                errors.append(f"{label}: arena_result_path missing on disk")

            seed = leg.get("seed")
            status = leg.get("seed_control_status")
            if seed is None:
                if status != "not_recorded_in_current_smoke":
                    errors.append(f"{label}: null seed requires not_recorded_in_current_smoke")
                warnings.append(f"{label}: seed not recorded (status=not_recorded_in_current_smoke)")
            elif status != "recorded":
                errors.append(f"{label}: non-null seed requires seed_control_status=recorded")

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", default=".")
    parser.add_argument("--manifest", default="logs/pairing_manifest.json")
    args = parser.parse_args()

    workspace_root = Path(args.workspace_root).resolve()
    manifest = (workspace_root / args.manifest).resolve()
    if not manifest.exists():
        print(f"FAIL missing manifest: {manifest}")
        return 1

    errors, warnings = audit_manifest(workspace_root, manifest)
    for w in warnings:
        print(f"WARN {w}")
    if errors:
        print("pairing_manifest_audit=FAIL")
        for e in errors:
            print(f"ERROR {e}")
        return 1
    print("pairing_manifest_audit=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
            requested_seed = leg.get("requested_seed")
            applied_seed = leg.get("applied_seed")
            status = leg.get("seed_control_status")
            if status == "not_recorded_in_current_smoke":
                if seed is not None or requested_seed is not None or applied_seed is not None:
                    errors.append(f"{label}: not_recorded_in_current_smoke requires all seed fields null")
                warnings.append(f"{label}: seed not recorded (status=not_recorded_in_current_smoke)")
            elif status == "requested_but_not_applied":
                if requested_seed is None:
                    errors.append(f"{label}: requested_but_not_applied requires non-null requested_seed")
                if applied_seed is not None or seed is not None:
                    errors.append(f"{label}: requested_but_not_applied requires null applied_seed and seed")
                warnings.append(f"{label}: seed requested but not applied")
            elif status == "applied":
                if applied_seed is None:
                    errors.append(f"{label}: applied status requires non-null applied_seed")
                if seed != applied_seed:
                    errors.append(f"{label}: applied status requires seed == applied_seed")
            else:
                errors.append(f"{label}: unsupported seed_control_status={status!r}")

        requested1 = leg1.get("requested_seed")
        requested2 = leg2.get("requested_seed")
        if requested1 != requested2:
            errors.append(f"{pid}: requested_seed mismatch across legs")

        applied1 = leg1.get("applied_seed")
        applied2 = leg2.get("applied_seed")
        if applied1 is not None and applied2 is not None and applied1 != applied2:
            errors.append(f"{pid}: applied_seed mismatch across legs")

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

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def audit_validation_report(path: Path) -> tuple[list[str], list[str]]:
    data = _load_json(path)
    errors: list[str] = []
    warnings: list[str] = []

    if data.get("schema_version") != "openclaw_model_route_validation_v1":
        errors.append("schema_version mismatch")
        return errors, warnings

    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        errors.append("entries must be non-empty list")
        return errors, warnings
    if data.get("model_count") != len(entries):
        errors.append("model_count mismatch")

    mode = data.get("mode")
    if mode == "static":
        static_true = 0
        static_false = 0
        static_unknown = 0
        for e in entries:
            if not e.get("valid_executor", False):
                errors.append(f"{e.get('id')}: executor must be openclaw-minimal")
                continue
            if not e.get("provider_model_nonempty", False):
                errors.append(f"{e.get('id')}: provider_model missing")
                continue
            sk = e.get("static_known")
            if sk == "true":
                static_true += 1
            elif sk == "false":
                static_false += 1
                errors.append(f"{e.get('id')}: static route not validated ({e.get('notes')})")
            elif sk == "unknown":
                static_unknown += 1
                warnings.append(f"{e.get('id')}: static route unknown ({e.get('notes')})")
            else:
                errors.append(f"{e.get('id')}: invalid static_known value {sk!r}")
        catalog_status = str(data.get("catalog_status") or "")
        if static_unknown == len(entries) and catalog_status.startswith("catalog_unavailable"):
            errors.append("static catalog unavailable for all entries")
        if static_false == 0 and static_unknown > 0:
            errors.append("static audit incomplete: unknown entries remain")
        if static_true != len(entries):
            warnings.append(
                f"static summary: true={static_true} false={static_false} unknown={static_unknown}"
            )
    elif mode == "real":
        for e in entries:
            if not e.get("valid_executor", False):
                errors.append(f"{e.get('id')}: executor must be openclaw-minimal")
                continue
            if not e.get("provider_model_nonempty", False):
                errors.append(f"{e.get('id')}: provider_model missing")
                continue
            real = e.get("real")
            if not isinstance(real, dict):
                errors.append(f"{e.get('id')}: missing real validation block")
                continue
            if int(real.get("openclaw_returncode", 1)) != 0:
                errors.append(f"{e.get('id')}: openclaw returncode != 0")
            status = real.get("provider_route_status")
            if status != "matched":
                errors.append(f"{e.get('id')}: provider_route_status={status}")
            if not real.get("success", False):
                errors.append(f"{e.get('id')}: real route validation not successful")
            req = str(real.get("requested_provider_model") or "")
            ap = str(real.get("actual_provider") or "")
            am = str(real.get("actual_model") or "")
            if req != "relay/gpt-4.1" and ap.lower() == "relay" and am.lower() == "gpt-4.1":
                errors.append(f"{e.get('id')}: fallback to relay/gpt-4.1 is not accepted")
    else:
        errors.append(f"unsupported mode: {mode!r}")

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="logs/openclaw_model_route_validation.json")
    args = parser.parse_args()

    path = Path(args.input)
    if not path.exists():
        print(f"openclaw_model_route_audit=FAIL")
        print(f"ERROR missing input report: {path}")
        return 1

    errors, warnings = audit_validation_report(path)
    for w in warnings:
        print(f"WARN {w}")
    if errors:
        print("openclaw_model_route_audit=FAIL")
        for e in errors:
            print(f"ERROR {e}")
        return 1
    print("openclaw_model_route_audit=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

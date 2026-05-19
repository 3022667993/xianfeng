from __future__ import annotations

import json
from pathlib import Path


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def audit_seed_control(logs_root: Path = Path("logs")) -> tuple[list[str], list[str]]:
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
            meta = _load_json(meta_path)
            req = meta.get("requested_seed")
            status = meta.get("seed_control_status")
            for key in [
                "seed",
                "requested_seed",
                "applied_seed",
                "seed_control_status",
                "seed_control_error",
                "seed_control_methods_attempted",
                "seed_control_method_applied",
                "seed_control_env_seed_return",
            ]:
                if key not in meta:
                    errors.append(f"{md}: {key} missing")
            if req is None:
                errors.append(f"{md}: requested_seed missing")
                continue
            if status is None:
                errors.append(f"{md}: seed_control_status missing")
                continue
            for name in [
                "scorecard.json",
                "arena_result_match_a.json",
                "trajectory_summary.json",
                "trajectory_events.json",
            ]:
                p = md / name
                if p.exists():
                    payload = _load_json(p)
                    for key in [
                        "seed",
                        "requested_seed",
                        "applied_seed",
                        "seed_control_status",
                        "seed_control_error",
                        "seed_control_methods_attempted",
                        "seed_control_method_applied",
                        "seed_control_env_seed_return",
                    ]:
                        if key not in payload:
                            errors.append(f"{p}: {key} missing")
                    if payload.get("requested_seed") is None:
                        errors.append(f"{p}: requested_seed missing")
                    payload_status = payload.get("seed_control_status")
                    if payload_status not in {
                        "applied",
                        "requested_but_not_applied",
                        "unsupported_by_environment",
                        "not_requested",
                    }:
                        errors.append(f"{p}: unsupported seed_control_status={payload_status!r}")
                        continue
                    if payload_status == "applied":
                        if payload.get("applied_seed") != payload.get("requested_seed"):
                            errors.append(f"{p}: applied_seed must equal requested_seed when applied")
                        if payload.get("seed") != payload.get("requested_seed"):
                            errors.append(f"{p}: seed must equal requested_seed when applied")
                        method = payload.get("seed_control_method_applied")
                        if not isinstance(method, str) or not method:
                            errors.append(f"{p}: seed_control_method_applied must be non-empty when applied")
                        elif method != "env.seed(...)":
                            errors.append(f"{p}: applied seed method must be env.seed(...)")
                        methods = payload.get("seed_control_methods_attempted")
                        if not isinstance(methods, list) or "env.seed(...)" not in methods:
                            errors.append(f"{p}: seed_control_methods_attempted must include env.seed(...) when applied")
                    elif payload_status in {"requested_but_not_applied", "unsupported_by_environment"}:
                        if payload.get("applied_seed") is not None:
                            errors.append(f"{p}: applied_seed must be null when not applied")
                        methods = payload.get("seed_control_methods_attempted")
                        if not isinstance(methods, list) or not methods:
                            errors.append(f"{p}: seed_control_methods_attempted must be non-empty when not applied")
                        if payload.get("requested_seed") is not None:
                            err = payload.get("seed_control_error")
                            if not isinstance(err, str) or not err.strip():
                                errors.append(f"{p}: seed_control_error must be non-empty when requested but not applied")
            if status == "applied":
                if meta.get("applied_seed") != req or meta.get("seed") != req:
                    errors.append(f"{md}: applied seed fields invalid")
                method = meta.get("seed_control_method_applied")
                if not isinstance(method, str) or not method:
                    errors.append(f"{md}: seed_control_method_applied must be non-empty when applied")
                elif method != "env.seed(...)":
                    errors.append(f"{md}: applied seed method must be env.seed(...)")
                methods = meta.get("seed_control_methods_attempted")
                if not isinstance(methods, list) or "env.seed(...)" not in methods:
                    errors.append(f"{md}: seed_control_methods_attempted must include env.seed(...) when applied")
            elif status in {"requested_but_not_applied", "unsupported_by_environment"}:
                if meta.get("applied_seed") is not None or meta.get("seed") is not None:
                    errors.append(f"{md}: non-applied seed fields invalid")
                methods = meta.get("seed_control_methods_attempted")
                if not isinstance(methods, list) or not methods:
                    errors.append(f"{md}: seed_control_methods_attempted must be non-empty when not applied")
                if req is not None:
                    err = meta.get("seed_control_error")
                    if not isinstance(err, str) or not err.strip():
                        errors.append(f"{md}: seed_control_error must be non-empty when requested but not applied")
            else:
                errors.append(f"{md}: unsupported seed_control_status={status!r}")

    return errors, warnings


def main() -> int:
    errors, warnings = audit_seed_control()
    for w in warnings:
        print(f"WARN {w}")
    if errors:
        print("pommerman_seed_control_audit=FAIL")
        for e in errors:
            print(f"ERROR {e}")
        return 1
    print("pommerman_seed_control_audit=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

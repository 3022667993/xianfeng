from __future__ import annotations

import json
import random
from typing import Any

try:
    import numpy as np
except Exception:
    np = None


def _base_seed_result(requested_seed: int | None) -> dict[str, Any]:
    return {
        "requested_seed": requested_seed,
        "applied_seed": None,
        "seed": None,
        "seed_control_status": "not_requested" if requested_seed is None else "requested_but_not_applied",
        "seed_control_error": None if requested_seed is None else "requested seed not yet applied to environment",
        "seed_control_methods_attempted": [],
        "seed_control_method_applied": None,
        "seed_control_env_seed_return": None,
    }


def _jsonable_or_none(value: Any) -> Any:
    if value is None:
        return None
    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)


def apply_pre_env_seed(requested_seed: int | None) -> dict[str, Any]:
    result = _base_seed_result(requested_seed)
    if requested_seed is None:
        return result

    methods_attempted: list[str] = []
    errors: list[str] = []

    methods_attempted.append("random.seed(...)")
    try:
        random.seed(requested_seed)
    except Exception as exc:
        errors.append(f"random.seed:{exc}")

    if np is None:
        methods_attempted.append("numpy_unavailable")
    else:
        methods_attempted.append("numpy.random.seed(...)")
        try:
            np.random.seed(requested_seed)
        except Exception as exc:
            errors.append(f"numpy.random.seed:{exc}")

    result["seed_control_methods_attempted"] = methods_attempted
    if errors:
        result["seed_control_error"] = "; ".join(errors)
    return result


def apply_env_seed(
    env: Any,
    requested_seed: int | None,
    prior_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if prior_provenance is not None and isinstance(prior_provenance, dict):
        result = dict(prior_provenance)
    else:
        result = _base_seed_result(requested_seed)

    result["requested_seed"] = requested_seed
    result.setdefault("seed_control_env_seed_return", None)
    methods_attempted = result.get("seed_control_methods_attempted")
    if not isinstance(methods_attempted, list):
        methods_attempted = []
    errors: list[str] = []

    if requested_seed is None:
        result["applied_seed"] = None
        result["seed"] = None
        result["seed_control_status"] = "not_requested"
        result["seed_control_error"] = None
        result["seed_control_method_applied"] = None
        result["seed_control_methods_attempted"] = methods_attempted
        result["seed_control_env_seed_return"] = None
        return result

    methods_attempted.append("env.seed(...)")
    if hasattr(env, "seed"):
        try:
            env_seed_ret = env.seed(requested_seed)
            result["applied_seed"] = requested_seed
            result["seed"] = requested_seed
            result["seed_control_status"] = "applied"
            result["seed_control_error"] = None
            result["seed_control_method_applied"] = "env.seed(...)"
            result["seed_control_methods_attempted"] = methods_attempted
            result["seed_control_env_seed_return"] = _jsonable_or_none(env_seed_ret)
            return result
        except Exception as exc:
            errors.append(f"env.seed(...):{exc}")
    else:
        errors.append("env.seed_missing")

    methods_attempted.append("env.reset(seed=...)")
    if hasattr(env, "reset"):
        try:
            env.reset(seed=requested_seed)
            result["applied_seed"] = requested_seed
            result["seed"] = requested_seed
            result["seed_control_status"] = "applied"
            result["seed_control_error"] = None
            result["seed_control_method_applied"] = "env.reset(seed=...)"
            result["seed_control_methods_attempted"] = methods_attempted
            return result
        except Exception as exc:
            errors.append(f"env.reset(seed=...):{exc}")
    else:
        errors.append("env.reset_missing")

    result["applied_seed"] = None
    result["seed"] = None
    result["seed_control_method_applied"] = None
    result["seed_control_methods_attempted"] = methods_attempted
    has_any_seed_api = hasattr(env, "seed") or hasattr(env, "reset")
    result["seed_control_status"] = "requested_but_not_applied" if has_any_seed_api else "unsupported_by_environment"
    if errors:
        result["seed_control_error"] = "; ".join(errors)
    elif not isinstance(result.get("seed_control_error"), str) or not str(result["seed_control_error"]).strip():
        result["seed_control_error"] = "requested seed could not be applied by environment seed APIs"
    result["seed_control_env_seed_return"] = None
    return result


def apply_seed_to_env(env: Any, requested_seed: int | None) -> dict[str, Any]:
    pre = apply_pre_env_seed(requested_seed)
    return apply_env_seed(env, requested_seed, prior_provenance=pre)

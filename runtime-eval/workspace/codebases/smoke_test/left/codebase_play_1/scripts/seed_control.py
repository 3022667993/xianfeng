from __future__ import annotations

import random
from typing import Any

import numpy as np


def apply_seed_to_env(env: Any, requested_seed: int) -> tuple[int | None, str, str | None]:
    random.seed(requested_seed)
    try:
        np.random.seed(requested_seed)
    except Exception:
        pass

    supported = False
    error: str | None = None
    applied_seed: int | None = None
    reset_supported = False
    try:
        if hasattr(env, "reset"):
            try:
                result = env.reset(seed=requested_seed)
                reset_supported = True
                supported = True
                applied_seed = requested_seed
                # Some envs return the initial observation; others ignore kwargs silently.
                # We treat a successful call as seed application support, but keep fallback available.
                _ = result
            except TypeError as exc:
                error = str(exc)
            except Exception as exc:
                error = str(exc)
        if (applied_seed is None or not reset_supported) and hasattr(env, "seed"):
            try:
                env.seed(requested_seed)
                supported = True
                applied_seed = requested_seed
                error = None
            except Exception as exc:
                error = str(exc)
        if applied_seed is None:
            if not supported and error is None:
                return None, "unsupported_by_environment", "no env.reset(seed=...) or env.seed(...) support detected"
            return None, "requested_but_not_applied", error or "seed application failed"
        return applied_seed, "applied", None
    except Exception as exc:
        return None, "requested_but_not_applied", str(exc)

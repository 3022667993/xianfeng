from __future__ import annotations

from pathlib import Path
from typing import Any
import yaml

ODD_MODEL_COUNT_ERROR = "odd model count requires BYE scheduling, which is not implemented"


def load_yaml(path: str | Path) -> dict:
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def require_keys(obj: dict, keys: list[str], name: str) -> None:
    missing = [k for k in keys if k not in obj]
    if missing:
        raise KeyError(f"{name} missing required keys: {missing}")


def _is_auto_value(value: Any) -> bool:
    return value in {"auto", "all", "auto_full_double_rr", "auto_before_final"}


def _int_field(value: Any, field: str) -> int:
    try:
        return int(value)
    except Exception as exc:
        raise ValueError(f"{field} must be an integer or supported auto value, got {value!r}") from exc


def _roster_count(roster_models: list[dict] | None) -> int | None:
    if roster_models is None:
        return None
    if not isinstance(roster_models, list):
        raise ValueError("model roster must be a list")
    return len(roster_models)


def resolve_tournament_counts(tournament: dict[str, Any], roster_models: list[dict] | None) -> dict[str, Any]:
    """Resolve auto/all tournament count fields from the supplied model roster.

    Supported auto values:
    - num_models: auto
    - matches_per_round: auto
    - revision_subset_size: all
    - num_rounds: auto_full_double_rr
    - revision_rounds: auto_before_final
    """

    resolved = dict(tournament)
    model_count = _roster_count(roster_models)
    has_auto = any(_is_auto_value(resolved.get(field)) for field in [
        "num_models",
        "matches_per_round",
        "revision_subset_size",
        "num_rounds",
        "revision_rounds",
    ])
    if has_auto and model_count is None:
        raise ValueError("auto tournament count fields require a model roster")
    if model_count is not None:
        if model_count < 2:
            raise ValueError("at least two models required")
        if model_count % 2 == 1:
            raise ValueError(ODD_MODEL_COUNT_ERROR)

    raw_num_models = resolved.get("num_models")
    if raw_num_models == "auto":
        assert model_count is not None
        resolved["num_models"] = model_count
    elif raw_num_models is None and model_count is not None:
        resolved["num_models"] = model_count
    else:
        resolved["num_models"] = _int_field(raw_num_models, "num_models")

    if model_count is not None and resolved["num_models"] != model_count:
        raise ValueError(f"num_models={resolved['num_models']} does not match model roster size {model_count}")

    n = int(resolved["num_models"])
    if n < 2:
        raise ValueError("at least two models required")
    if n % 2 == 1:
        raise ValueError(ODD_MODEL_COUNT_ERROR)

    raw_num_rounds = resolved.get("num_rounds")
    if raw_num_rounds == "auto_full_double_rr":
        resolved["num_rounds"] = 2 * (n - 1)
    else:
        resolved["num_rounds"] = _int_field(raw_num_rounds, "num_rounds")

    raw_matches_per_round = resolved.get("matches_per_round")
    if raw_matches_per_round == "auto":
        resolved["matches_per_round"] = n // 2
    elif raw_matches_per_round is None:
        resolved["matches_per_round"] = n // 2
    else:
        resolved["matches_per_round"] = _int_field(raw_matches_per_round, "matches_per_round")

    raw_revision_subset_size = resolved.get("revision_subset_size")
    if raw_revision_subset_size == "all":
        resolved["revision_subset_size"] = n
    elif raw_revision_subset_size is not None:
        resolved["revision_subset_size"] = _int_field(raw_revision_subset_size, "revision_subset_size")

    raw_revision_rounds = resolved.get("revision_rounds")
    if raw_revision_rounds == "auto_before_final":
        resolved["revision_rounds"] = list(range(1, int(resolved["num_rounds"])))
    elif raw_revision_rounds is not None:
        if not isinstance(raw_revision_rounds, list):
            raise ValueError("revision_rounds must be a list or auto_before_final")
        resolved["revision_rounds"] = [_int_field(x, "revision_rounds entry") for x in raw_revision_rounds]

    if resolved.get("schedule_mode") == "double_round_robin" and resolved.get("match_legs", "single") == "single":
        expected_matches = n // 2
        if int(resolved["matches_per_round"]) != expected_matches:
            raise ValueError(
                f"matches_per_round={resolved['matches_per_round']} does not match even-N double_round_robin "
                f"requirement {expected_matches} for num_models={n}"
            )

    if "revision_subset_size" in resolved and resolved["revision_subset_size"] is not None:
        if int(resolved["revision_subset_size"]) > n:
            raise ValueError(f"revision_subset_size={resolved['revision_subset_size']} exceeds num_models={n}")

    if int(resolved["num_rounds"]) <= 0:
        raise ValueError("num_rounds must be positive")
    for r in resolved.get("revision_rounds", []) or []:
        if int(r) >= int(resolved["num_rounds"]):
            raise ValueError("each revision_round must be strictly less than num_rounds")

    return resolved

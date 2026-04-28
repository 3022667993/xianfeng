from __future__ import annotations

from pathlib import Path
import yaml


def load_yaml(path: str | Path) -> dict:
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def require_keys(obj: dict, keys: list[str], name: str) -> None:
    missing = [k for k in keys if k not in obj]
    if missing:
        raise KeyError(f"{name} missing required keys: {missing}")

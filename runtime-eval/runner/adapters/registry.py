from __future__ import annotations

from runner.adapters.base import BaseGameAdapter
from runner.adapters.pommerman_1v1 import Pommerman1v1Adapter


def get_adapter(name: str) -> BaseGameAdapter:
    registry = {
        "pommerman_1v1": Pommerman1v1Adapter,
    }

    if name not in registry:
        raise KeyError(f"Unknown adapter: {name}")

    return registry[name]()

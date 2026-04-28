from runner.adapters.registry import get_adapter
from runner.adapters.pommerman_1v1 import Pommerman1v1Adapter


def test_registry_returns_pommerman_adapter():
    adapter = get_adapter("pommerman_1v1")
    assert isinstance(adapter, Pommerman1v1Adapter)

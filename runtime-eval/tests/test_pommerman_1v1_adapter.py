from pathlib import Path

from runner.adapters.pommerman_1v1 import Pommerman1v1Adapter


def test_pommerman_contract_valid():
    adapter = Pommerman1v1Adapter()
    ok, msg = adapter.validate_submission(Path("starter_repos/pommerman_1v1"))
    assert ok, msg

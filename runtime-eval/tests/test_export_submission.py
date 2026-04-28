from pathlib import Path

from runner.adapters.pommerman_1v1 import Pommerman1v1Adapter


def test_export_submission(tmp_path):
    adapter = Pommerman1v1Adapter()
    dst = tmp_path / "submission_export"
    ok, msg = adapter.export_submission(Path("starter_repos/pommerman_1v1"), dst)
    assert ok, msg
    assert (dst / "main.py").exists()

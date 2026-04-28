from pathlib import Path

from runner.adapters.pommerman_1v1 import Pommerman1v1Adapter


def test_pommerman_run_match_smoke(tmp_path):
    adapter = Pommerman1v1Adapter()
    round_dir = tmp_path / "round_1"
    result = adapter.run_match(
        Path("starter_repos/pommerman_1v1"),
        Path("starter_repos/pommerman_1v1"),
        round_dir,
        {},
    )
    assert "winner" in result
    assert "result" in result
    assert "runtime_diagnostics" in result
    assert (round_dir / "build.log").exists()
    assert (round_dir / "test.log").exists()
    assert (round_dir / "stderr.log").exists()

from pathlib import Path

def test_layout():
    required = [
        "configs/regimes/A00.yaml",
        "configs/tournaments/smoke.yaml",
        "docs/naming.md",
        "runner/main.py",
        "scripts/run_smoke.sh",
    ]
    missing = [p for p in required if not Path(p).exists()]
    assert not missing, f"Missing files: {missing}"

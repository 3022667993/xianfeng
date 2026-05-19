from pathlib import Path

from runner.adapters.pommerman_1v1 import Pommerman1v1Adapter


def test_pommerman_contract_valid():
    adapter = Pommerman1v1Adapter()
    ok, msg = adapter.validate_submission(Path("starter_repos/pommerman_1v1"))
    assert ok, msg


def test_starter_readme_objective_clarifies_tournament_outcome():
    readme = Path("starter_repos/pommerman_1v1/README.md").read_text(encoding="utf-8")
    objective_intro = readme.split("## 4. Objective", 1)[1].split("Practical priorities:", 1)[0]
    objective_lower = objective_intro.lower()

    assert "prefer wins over draws, and draws over losses" in objective_lower
    assert "dummy/background-agent win is unfavorable" in objective_lower
    assert "feedback packages from later rounds provide match evidence" in objective_lower
    assert "revise strategy or behavior" in objective_lower
    assert "already winning" in objective_lower
    assert "improve robustness and consistency" in objective_lower
    assert "this readme defines the rules, action meanings, objective, and submission api" in objective_lower
    for forbidden in [
        "center movement",
        "wood clearing",
        "powerups",
        "opponent pressure",
        "reduce stop",
        "safe aggression",
        "bomb more",
        "go to center",
        "chase opponent",
    ]:
        assert forbidden not in objective_lower

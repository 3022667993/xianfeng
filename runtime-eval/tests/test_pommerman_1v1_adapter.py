import ast
import importlib.util
import sys
import types
from pathlib import Path

import pytest

from runner.adapters.pommerman_1v1 import Pommerman1v1Adapter


class _FakeBaseAgent:
    pass


def _load_starter_module(monkeypatch):
    fake_pommerman = types.ModuleType("pommerman")
    fake_pommerman.agents = types.SimpleNamespace(BaseAgent=_FakeBaseAgent)
    monkeypatch.setitem(sys.modules, "pommerman", fake_pommerman)

    path = Path("starter_repos/pommerman_1v1/submission/main.py").resolve()
    spec = importlib.util.spec_from_file_location("starter_submission_main", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, fake_pommerman


def test_pommerman_contract_valid():
    adapter = Pommerman1v1Adapter()
    ok, msg = adapter.validate_submission(Path("starter_repos/pommerman_1v1"))
    assert ok, msg


def test_starter_readme_objective_clarifies_tournament_outcome():
    readme = Path("starter_repos/pommerman_1v1/README.md").read_text(encoding="utf-8")
    objective_intro = readme.split("## 4. Objective", 1)[1].split("## 5. Action Space", 1)[0]
    objective_lower = objective_intro.lower()

    assert "prefer wins over draws, and draws over losses" in objective_lower
    assert "dummy/background-agent win is unfavorable" in objective_lower
    assert "feedback packages from later rounds provide match evidence" in objective_lower
    assert "revise strategy or behavior" in objective_lower
    assert "already winning" in objective_lower
    assert "improve robustness and consistency" in objective_lower
    assert "starter implementation is intentionally weak" in objective_lower
    assert "initial synthesis should implement a complete behavior" in objective_lower
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


def test_starter_submission_is_minimal_valid_skeleton():
    path = Path("starter_repos/pommerman_1v1/submission/main.py")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    class_names = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    function_names = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}

    assert class_names == {"Agent"}
    assert function_names == {"make_agent"}
    assert "from pommerman import agents" in source
    assert "class Agent(agents.BaseAgent):" in source
    assert "return 0" in source
    assert len(source.splitlines()) <= 17
    for forbidden in [
        "ConservativeAgent",
        "ProactiveSafeAgent",
        "MOVE_DELTAS",
        "POWERUPS",
        "_threatened_cells",
        "_best_move",
        "_bomb_useful",
        "danger",
        "pathfinding",
        "center",
        "wood",
        "powerup",
        "opponent",
        "bomb_life",
        "bomb_blast",
    ]:
        assert forbidden not in source


def test_starter_submission_make_agent_returns_baseagent_and_valid_action(monkeypatch):
    module, fake_pommerman = _load_starter_module(monkeypatch)
    agent = module.make_agent()
    assert isinstance(agent, fake_pommerman.agents.BaseAgent)
    assert hasattr(agent, "act")
    action = agent.act({}, None)
    assert isinstance(action, int)
    assert 0 <= action <= 5


def test_starter_readme_documents_baseagent_contract():
    readme = Path("starter_repos/pommerman_1v1/README.md").read_text(encoding="utf-8")
    lower = readme.lower()
    assert "pommerman.agents.baseagent" in lower
    assert "make_agent()" in readme
    assert "must return an instance of a class that subclasses `pommerman.agents.BaseAgent`" in readme
    assert "act(self, obs, action_space=None)" in readme
    assert "from pommerman import agents" in readme
    assert "class Agent(agents.BaseAgent)" in readme
    assert "act(...)` returns one integer action in `[0, 5]`" in readme


def test_starter_baseagent_is_accepted_by_real_pommerman_env():
    pommerman = pytest.importorskip("pommerman")
    agents = pytest.importorskip("pommerman.agents")

    path = Path("starter_repos/pommerman_1v1/submission/main.py").resolve()
    spec = importlib.util.spec_from_file_location("starter_submission_main_real", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    left = module.make_agent()
    right = module.make_agent()
    assert isinstance(left, agents.BaseAgent)
    assert isinstance(right, agents.BaseAgent)

    env = pommerman.make("PommeFFACompetition-v0", [left, right, agents.RandomAgent(), agents.RandomAgent()])
    try:
        assert env is not None
    finally:
        env.close()

import ast
import importlib.util
import os
import shutil
import subprocess
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


def test_starter_readme_is_local_rules_source_without_external_links():
    readme = Path("starter_repos/pommerman_1v1/README.md").read_text(encoding="utf-8")
    lower = readme.lower()

    assert "benchmark-facing local rules and api guide" in lower
    assert "local source of rules and api details" in lower
    assert "should not rely on external websites, internet access, hidden files, private workspaces" in lower
    assert "if a detail is not specified here" in lower
    assert "returns a valid action in `[0, 5]`" in lower
    assert "## 25. Local Source Of Truth" in readme
    assert "Official References" not in readme
    assert "http://" not in readme
    assert "https://" not in readme
    assert "pommerman.readthedocs" not in lower
    assert "github.com/MultiAgentLearning/playground".lower() not in lower


def test_starter_readme_objective_clarifies_tournament_outcome():
    readme = Path("starter_repos/pommerman_1v1/README.md").read_text(encoding="utf-8")
    objective_intro = readme.split("## 4. Objective", 1)[1].split("## 5. Action Space", 1)[0]
    objective_lower = objective_intro.lower()

    assert "prefer robust wins over draws, and draws over losses" in objective_lower
    assert "timeout draw is a weak outcome when no submitted opponent is eliminated" in objective_lower
    assert "early self-elimination is unfavorable, even if the environment-level result is later reported as a draw" in objective_lower
    assert "dummy/background-agent win is unfavorable" in objective_lower
    assert "opponent's self-destruction" in objective_lower
    assert "not strong evidence of a robust strategy" in objective_lower
    assert "feedback packages from later rounds provide match evidence" in objective_lower
    assert "revise strategy or behavior" in objective_lower
    assert "already winning" in objective_lower
    assert "improve robustness, consistency, and resilience" in objective_lower
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


def test_starter_readme_what_to_optimize_clarifies_neutral_objective():
    readme = Path("starter_repos/pommerman_1v1/README.md").read_text(encoding="utf-8")
    section = readme.split("## 22. What To Optimize", 1)[1].split("## 23. Common Failure Modes", 1)[0]
    section_lower = section.lower()

    assert "prefer robust wins over draws" in section_lower
    assert "prefer draws over losses" in section_lower
    assert "treat timeout draws as weak outcomes when no submitted opponent is eliminated" in section_lower
    assert "treat early self-elimination as unfavorable, even if the environment-level result is later reported as a draw" in section_lower
    assert "treat dummy/background-agent wins as unfavorable" in section_lower
    assert "wins caused mainly by opponent self-destruction" in section_lower
    assert "not strong evidence of robust strategy" in section_lower
    assert "favor future decisive outcomes while preserving valid actions and avoiding obvious self-destruction" in section_lower
    assert "improve robustness, consistency, or resilience" in section_lower
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
        assert forbidden not in section_lower


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
    assert "`submission/main.py` is intentionally minimal" in readme
    assert "pommerman.agents.baseagent" in lower
    assert "make_agent()" in readme
    assert "must return an instance of a class that subclasses `pommerman.agents.BaseAgent`" in readme
    assert "act(self, obs, action_space=None)" in readme
    assert "from pommerman import agents" in readme
    assert "class Agent(agents.BaseAgent)" in readme
    assert "act(...)` returns one integer action in `[0, 5]`" in readme
    assert "`action_space` may be `None`" in readme
    assert "Return quickly." in readme


def test_starter_readme_documents_current_benchmark_mode():
    readme = Path("starter_repos/pommerman_1v1/README.md").read_text(encoding="utf-8")
    lower = readme.lower()

    assert "PommeFFACompetition-v0" in readme
    assert "1v1 proxy inside a four-agent FFA board" in readme
    assert "seat 0 = left_agent" in readme
    assert "seat 1 = right_agent" in readme
    assert "seat 2 = dummy2" in readme
    assert "seat 3 = dummy3" in readme
    assert "valid `pommerman.agents.BaseAgent` instances" in readme
    assert "first `act(...)` returns `5` (`Bomb`)" in readme
    assert "later `act(...)` calls return `0` (`Stop`)" in readme
    assert "single game named `match_a`" in readme
    assert "no paired `match_b` game" in lower
    assert "stops a match after 800 environment steps" in readme
    assert "Timeout/tie/draw interpretation is recorded by the runner scorecard fields." in readme
    assert "game_state.state[t]` and `game_state.state[t+1]`" in readme
    assert "`actions.jsonl` rows in feedback packages use `step=t`" in readme


def test_starter_readme_documents_scorecard_result_fields():
    readme = Path("starter_repos/pommerman_1v1/README.md").read_text(encoding="utf-8")
    lower = readme.lower()

    assert "### Scorecard and Result Interpretation" in readme
    assert "`scorecard.json` is the runner's per-match result summary" in readme
    assert "`left_right_winner` is the pairwise submitted-agent result" in readme
    assert "`submitted_pair_outcome` is the model-visible pair outcome label" in readme
    assert "`draw_type` explains why a pairwise draw occurred" in readme
    assert "`environment_winners` contains raw environment winner ids" in readme
    assert "`environment_winner_labels` maps environment winners to labels" in readme
    assert "`reward` is the raw environment reward vector for seats `[left, right, dummy2, dummy3]`" in readme
    assert "`steps` is the number of environment steps executed" in readme
    assert "`arena_fallback_or_invalid` is true only when the arena failed or produced an invalid fallback result" in readme
    assert "`timeout_draw` means the match reached the configured step limit without a submitted pairwise winner" in readme
    assert "timeout draw is a weak outcome when no submitted opponent was eliminated" in lower
    assert "submitted agent can die early even if the final environment-level result is later reported as a draw" in lower
    assert "early self-elimination is unfavorable evidence for later revisions" in lower
    assert "dummy/background-agent wins are unfavorable for submitted agents" in lower
    assert "environment is done when the step count reaches `800`" in readme
    assert "exactly one agent remains alive" in readme
    assert "raw FFA rewards are `[+1, -1, -1, -1]`" in readme
    assert "At max-step timeout, raw FFA rewards are `[-1, -1, -1, -1]`" in readme
    assert "If zero agents remain alive at termination, `info[\"result\"]` is `Tie`" in readme
    assert "raw FFA rewards are `0` for alive seats and `-1` for dead seats" in readme
    assert "runner/reporting layer handles result aggregation" in lower


def test_starter_readme_documents_suicidal_filler_background_agents():
    readme = Path("starter_repos/pommerman_1v1/README.md").read_text(encoding="utf-8").lower()
    assert "seat 2 = dummy2      = suicidal filler background agent" in readme
    assert "seat 3 = dummy3      = suicidal filler background agent" in readme
    assert "background filler agents exist to satisfy the four-agent ffa environment" in readme
    assert "attempt to remove themselves early through legal actions" in readme
    assert "not intended as competitive opponents" in readme
    assert "evaluated as left vs right under the runner's pairwise result logic" in readme


def test_starter_readme_documents_action_mapping_and_current_rules():
    readme = Path("starter_repos/pommerman_1v1/README.md").read_text(encoding="utf-8")
    lower = readme.lower()

    for line in [
        "0 = Stop",
        "1 = Up",
        "2 = Down",
        "3 = Left",
        "4 = Right",
        "5 = Bomb",
    ]:
        assert line in readme
    assert "integer-like scalar" in readme
    assert "Invalid or non-integer output can fail validation" in readme
    assert "(row, column)" in readme
    assert "Always check board bounds before reading a cell." in readme
    assert "Passages / empty cells" in readme
    assert "Rigid walls" in readme
    assert "Wooden walls" in readme
    assert "Bombs: occupied cells with a remaining life/timer and blast strength." in readme
    assert "Flames / explosions: lethal cells" in readme
    assert "Fog: unknown or not-visible cells" in readme
    assert "Powerup cells" in readme
    assert "Agent cells" in readme
    assert "Movement actions request a move to an adjacent cell" in readme
    assert "Bomb action requests bomb placement" in readme
    assert "ammo is normally restored after that bomb is processed as exploded" in readme
    assert "row and column rays" in readme
    assert "Chain Reactions" in readme
    assert "Kick" in readme


def test_starter_readme_documents_verified_engine_boundary_semantics():
    readme = Path("starter_repos/pommerman_1v1/README.md").read_text(encoding="utf-8")

    for line in [
        "Passage   = 0",
        "Rigid     = 1",
        "Wood      = 2",
        "Bomb      = 3",
        "Flames    = 4",
        "Fog       = 5",
        "ExtraBomb = 6",
        "IncrRange = 7",
        "Kick      = 8",
        "Agent0    = 10",
        "Agent1    = 11",
        "Agent2    = 12",
        "Agent3    = 13",
    ]:
        assert line in readme

    assert "Local engine boundary notes verified from the installed Pommerman package used by this benchmark" in readme
    assert "Hidden item types are `ExtraBomb`, `IncrRange`, and `Kick`." in readme
    assert "When a flame on a destroyed wooden wall expires, the board cell becomes the hidden item value" in readme
    assert "move into a rigid wall, wooden wall, or off-board location is not accepted" in readme
    assert "multiple agents try to occupy the same target cell" in readme
    assert "try to swap cells across the same border" in readme
    assert "Collision resolution is simultaneous and iterative" in readme
    assert "`can_kick` is a boolean observation field and agent attribute" in readme
    assert "moving into a bomb attempts to push that bomb one cell" in readme
    assert "Kicked bomb movement can be blocked by board bounds, walls, powerup cells, agents, other bombs, or collision resolution." in readme
    assert "Agents start with `ammo = 1`, `blast_strength = 2`, and `can_kick = False`." in readme
    assert "ammo decreases immediately" in readme
    assert "A local probe observed ammo restoration even when the bomb owner died in the explosion." in readme
    assert "Ammo is capped at `10`" in readme
    assert "`DEFAULT_BOMB_LIFE` is `9`" in readme
    assert "visible `bomb_life` value is typically `9.0`" in readme
    assert "Visible `bomb_life` values decrease by `1.0` per environment step" in readme
    assert "Cells with no visible bomb use `0.0` in `bomb_life`." in readme
    assert "Flames appear on the board with item value `4`." in readme
    assert "Observations include a `flame_life` NumPy array." in readme
    assert "observed `flame_life` values appear as `3.0`, then `2.0`, then `1.0`, then disappear" in readme
    assert "A local probe observed flame board cells for three observations after the explosion transition." in readme
    assert "bombs whose position is reached by the current explosion map have their life set to `0`" in readme
    assert "continues processing newly exploded bombs in the same environment step" in readme


def test_starter_readme_documents_observation_api_pitfalls():
    readme = Path("starter_repos/pommerman_1v1/README.md").read_text(encoding="utf-8")
    lower = readme.lower()
    assert '`obs["board"]`' in readme
    assert '`obs["bomb_life"]`' in readme
    assert "may be NumPy arrays" in readme
    assert "do not use numpy arrays directly as booleans" in lower
    assert "`if board:`" in readme
    assert "`if not board:`" in readme
    assert "`if board[0]:`" in readme
    assert '`if obs["bomb_life"] == 0:`' in readme
    assert '`obs` may not contain `"agent_id"`' in readme
    assert "`self.agent_id`" in readme
    assert "return a valid fallback action such as `0`" in readme


def _conda_bin_or_skip() -> str:
    conda_bin = os.environ.get("CONDA_BIN") or str(Path.home() / "miniconda3" / "bin" / "conda")
    if not Path(conda_bin).exists():
        pytest.skip("conda binary unavailable for Pommerman starter smoke")
    return conda_bin


def _run_starter_smoke(codebase_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "tests/smoke.sh"],
        cwd=codebase_dir,
        env={**os.environ, "CONDA_BIN": _conda_bin_or_skip()},
        capture_output=True,
        text=True,
        check=False,
        timeout=240,
    )


def test_starter_smoke_validates_minimal_baseagent_on_real_observation():
    proc = _run_starter_smoke(Path("starter_repos/pommerman_1v1"))
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "[smoke] starter repo contract OK" in proc.stdout


def test_starter_smoke_rejects_numpy_truthiness_on_real_observation(tmp_path):
    src = Path("starter_repos/pommerman_1v1")
    dst = tmp_path / "bad_codebase"
    shutil.copytree(src, dst)
    (dst / "submission" / "main.py").write_text(
        """from pommerman import agents


class Agent(agents.BaseAgent):
    def act(self, obs, action_space=None):
        board = obs.get("board")
        if not board:
            return 0
        return 0


def make_agent():
    return Agent()
""",
        encoding="utf-8",
    )

    proc = _run_starter_smoke(dst)
    combined = f"{proc.stdout}\n{proc.stderr}"
    assert proc.returncode != 0
    assert "submission contract validation failed on real Pommerman observation" in combined
    assert "truth value of an array" in combined or "truth value of a numpy array" in combined


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

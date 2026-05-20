import importlib.util
import shutil
import sys
import types
from pathlib import Path


class _FakeBaseAgent:
    pass


def test_probe_imports_local_seed_control_from_copied_codebase(tmp_path, monkeypatch):
    repo = Path(__file__).resolve().parents[1]
    src = repo / "starter_repos" / "pommerman_1v1"
    dst = tmp_path / "codebase_play_1"
    shutil.copytree(src, dst)

    # Stub pommerman imports so module import doesn't require real package.
    fake_pommerman = types.ModuleType("pommerman")
    fake_pommerman.agents = types.SimpleNamespace(BaseAgent=_FakeBaseAgent)
    monkeypatch.setitem(sys.modules, "pommerman", fake_pommerman)

    probe_path = dst / "scripts" / "pommerman_ffa_probe.py"
    spec = importlib.util.spec_from_file_location("copied_probe", probe_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert hasattr(module, "apply_pre_env_seed")
    assert callable(module.apply_pre_env_seed)
    assert hasattr(module, "apply_env_seed")
    assert callable(module.apply_env_seed)


def test_probe_background_dummies_are_suicidal_filler_baseagents(tmp_path, monkeypatch):
    repo = Path(__file__).resolve().parents[1]
    src = repo / "starter_repos" / "pommerman_1v1"
    dst = tmp_path / "codebase_play_1"
    shutil.copytree(src, dst)

    fake_pommerman = types.ModuleType("pommerman")
    fake_pommerman.agents = types.SimpleNamespace(BaseAgent=_FakeBaseAgent)
    monkeypatch.setitem(sys.modules, "pommerman", fake_pommerman)

    probe_path = dst / "scripts" / "pommerman_ffa_probe.py"
    spec = importlib.util.spec_from_file_location("copied_probe_suicide", probe_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    dummy = module.SuicideDummyAgent()
    assert isinstance(dummy, fake_pommerman.agents.BaseAgent)
    assert dummy.act({}, None) == 5
    assert dummy.act({}, None) == 0
    assert dummy.act({}, None) == 0
    assert module.RECORD_AGENT_LABELS == ["left", "right", "dummy2", "dummy3"]

    source = probe_path.read_text(encoding="utf-8")
    assert "SuicideDummyAgent()" in source
    assert "PassiveDummyAgent" not in source
    assert "agents.SimpleAgent()" not in source

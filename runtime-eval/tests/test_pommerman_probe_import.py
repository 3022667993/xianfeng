import importlib.util
import shutil
import sys
import types
from pathlib import Path


def test_probe_imports_local_seed_control_from_copied_codebase(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    src = repo / "starter_repos" / "pommerman_1v1"
    dst = tmp_path / "codebase_play_1"
    shutil.copytree(src, dst)

    # Stub pommerman imports so module import doesn't require real package.
    fake_pommerman = types.ModuleType("pommerman")
    fake_pommerman.agents = types.SimpleNamespace(SimpleAgent=object)
    sys.modules["pommerman"] = fake_pommerman

    probe_path = dst / "scripts" / "pommerman_ffa_probe.py"
    spec = importlib.util.spec_from_file_location("copied_probe", probe_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert hasattr(module, "apply_pre_env_seed")
    assert callable(module.apply_pre_env_seed)
    assert hasattr(module, "apply_env_seed")
    assert callable(module.apply_env_seed)

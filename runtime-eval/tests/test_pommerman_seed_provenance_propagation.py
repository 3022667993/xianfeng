import json
from pathlib import Path
from typing import Any

from runner.adapters.pommerman_1v1 import Pommerman1v1Adapter


class _FakeResult:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_run_match_propagates_seed_provenance_into_trajectory_events(tmp_path, monkeypatch):
    round_dir = tmp_path / "round_1" / "match_1"
    left_codebase = tmp_path / "left"
    right_codebase = tmp_path / "right"
    (left_codebase / "submission").mkdir(parents=True, exist_ok=True)
    (right_codebase / "submission").mkdir(parents=True, exist_ok=True)
    (left_codebase / "submission" / "main.py").write_text("def make_agent():\n    return None\n", encoding="utf-8")
    (right_codebase / "submission" / "main.py").write_text("def make_agent():\n    return None\n", encoding="utf-8")

    adapter = Pommerman1v1Adapter()

    calls = {"arena": 0}
    original_run_cmd = Pommerman1v1Adapter._run_cmd

    def fake_run_cmd(self, codebase_dir: Path, cmd: list[str]):
        if cmd[:2] == ["bash", "scripts/build.sh"]:
            return _FakeResult(0, "", "")
        if cmd[:2] == ["bash", "tests/smoke.sh"]:
            return _FakeResult(0, "", "")
        if cmd[:2] == ["bash", "scripts/run_arena.sh"]:
            calls["arena"] += 1
            out_json = Path(cmd[2])
            compact_path = Path(cmd[5])
            payload = {
                "env_id": "PommeFFACompetition-v0",
                "done": True,
                "steps": 3,
                "reward": [1, -1, -1, -1],
                "info": {"winners": [0], "result": "Win"},
                "left_score": 1,
                "right_score": -1,
                "left_right_winner": "left",
                "requested_seed": 4242,
                "applied_seed": 4242,
                "seed": 4242,
                "seed_control_status": "applied",
                "seed_control_error": None,
                "seed_control_methods_attempted": ["random.seed(...)", "env.seed(...)"],
                "seed_control_method_applied": "env.seed(...)",
                "seed_control_env_seed_return": [4242],
            }
            out_json.parent.mkdir(parents=True, exist_ok=True)
            out_json.write_text(json.dumps(payload), encoding="utf-8")
            row = {
                "schema_version": "pommerman_compact_trajectory_step_v2",
                "leg_label": None,
                "step": 0,
                "actions": {"seat_0": 0, "seat_1": 0, "seat_2": 0, "seat_3": 0},
                "reward": [0, 0, 0, 0],
                "done": False,
                "alive": {"seat_0": True, "seat_1": True, "seat_2": True, "seat_3": True},
                "positions": {"seat_0": [1, 1], "seat_1": [1, 2], "seat_2": [2, 1], "seat_3": [2, 2]},
                "compact_counts": {"bomb_count": 0, "flame_count": 0, "powerup_count": 0},
                "event_flags": {"terminal": False, "alive_changed": False, "reward_changed": False},
            }
            compact_path.parent.mkdir(parents=True, exist_ok=True)
            compact_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            return _FakeResult(0, "", "")
        return original_run_cmd(self, codebase_dir, cmd)

    monkeypatch.setattr(Pommerman1v1Adapter, "_run_cmd", fake_run_cmd)
    adapter.run_match(left_codebase, right_codebase, round_dir, {"requested_seed": 4242})

    events = _json(round_dir / "trajectory_events.json")
    for key in [
        "seed",
        "requested_seed",
        "applied_seed",
        "seed_control_status",
        "seed_control_error",
        "seed_control_methods_attempted",
        "seed_control_method_applied",
        "seed_control_env_seed_return",
    ]:
        assert key in events
    assert events["requested_seed"] == 4242
    assert events["applied_seed"] == 4242
    assert events["seed"] == 4242
    assert events["seed_control_status"] == "applied"
    assert events["seed_control_method_applied"] == "env.seed(...)"
    assert events["seed_control_env_seed_return"] == [4242]
    assert calls["arena"] == 1


def test_run_match_failed_arena_records_non_applied_details(tmp_path, monkeypatch):
    round_dir = tmp_path / "round_1" / "match_1"
    left_codebase = tmp_path / "left"
    right_codebase = tmp_path / "right"
    (left_codebase / "submission").mkdir(parents=True, exist_ok=True)
    (right_codebase / "submission").mkdir(parents=True, exist_ok=True)
    (left_codebase / "submission" / "main.py").write_text("def make_agent():\n    return None\n", encoding="utf-8")
    (right_codebase / "submission" / "main.py").write_text("def make_agent():\n    return None\n", encoding="utf-8")

    adapter = Pommerman1v1Adapter()

    def fake_run_cmd(self, codebase_dir: Path, cmd: list[str]):
        if cmd[:2] == ["bash", "scripts/build.sh"]:
            return _FakeResult(0, "", "")
        if cmd[:2] == ["bash", "tests/smoke.sh"]:
            return _FakeResult(0, "", "")
        if cmd[:2] == ["bash", "scripts/run_arena.sh"]:
            return _FakeResult(1, "", "arena failed")
        return _FakeResult(1, "", "unexpected command")

    monkeypatch.setattr(Pommerman1v1Adapter, "_run_cmd", fake_run_cmd)
    result = adapter.run_match(left_codebase, right_codebase, round_dir, {"requested_seed": 31337})
    assert result["result"] == "arena_probe_failed"
    assert result["runtime_diagnostics"]["seed_control_status"] == "requested_but_not_applied"

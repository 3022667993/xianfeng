import threading
import time
from pathlib import Path

import pytest

from runner import main as runner_main


def test_openclaw_concurrency_defaults_to_serial():
    assert runner_main._openclaw_concurrency({}) == 1
    assert runner_main._openclaw_concurrency({"openclaw_concurrency": "3"}) == 3
    with pytest.raises(ValueError, match="openclaw_concurrency must be >= 1"):
        runner_main._openclaw_concurrency({"openclaw_concurrency": 0})


def test_ordered_agent_jobs_serial_preserves_call_order():
    calls = []

    def worker(agent_id: str) -> str:
        calls.append(agent_id)
        return f"result:{agent_id}"

    results = runner_main._run_ordered_agent_jobs(
        ["a1", "a2", "a3"],
        worker,
        concurrency=1,
        stage_name="initial synthesis",
    )

    assert calls == ["a1", "a2", "a3"]
    assert results == ["result:a1", "result:a2", "result:a3"]


def test_initial_synthesis_style_jobs_return_roster_order_with_bounded_parallelism(tmp_path):
    active = 0
    max_active = 0
    lock = threading.Lock()

    def worker(agent_id: str) -> dict:
        nonlocal active, max_active
        run_dir = tmp_path / "runs" / agent_id / "codebase_post_t"
        run_dir.mkdir(parents=True)
        with lock:
            active += 1
            max_active = max(max_active, active)
        if agent_id == "a1":
            time.sleep(0.03)
        try:
            return {
                "agent_id": agent_id,
                "run_dir": str(run_dir),
                "initial_synthesis_ok": True,
            }
        finally:
            with lock:
                active -= 1

    results = runner_main._run_ordered_agent_jobs(
        ["a1", "a2", "a3"],
        worker,
        concurrency=2,
        stage_name="initial synthesis",
    )

    assert [item["agent_id"] for item in results] == ["a1", "a2", "a3"]
    assert max_active <= 2
    assert max_active > 1
    run_dirs = [Path(item["run_dir"]) for item in results]
    assert len(set(run_dirs)) == len(run_dirs)
    assert all(path.name == "codebase_post_t" for path in run_dirs)


def test_revision_style_jobs_return_roster_order_despite_out_of_order_completion():
    def worker(agent_id: str) -> tuple[str, dict]:
        if agent_id == "a1":
            time.sleep(0.03)
        return agent_id, {"agent_id": agent_id, "revision_ok": True}

    results = runner_main._run_ordered_agent_jobs(
        ["a1", "a2", "a3"],
        worker,
        concurrency=3,
        stage_name="round_1 revision",
    )

    assert [agent_id for agent_id, _entry in results] == ["a1", "a2", "a3"]
    assert [entry["agent_id"] for _agent_id, entry in results] == ["a1", "a2", "a3"]


def test_ordered_agent_jobs_aggregates_failures_in_stable_roster_order():
    def worker(agent_id: str) -> str:
        if agent_id in {"a1", "a3"}:
            if agent_id == "a1":
                time.sleep(0.03)
            raise RuntimeError(f"failed-{agent_id}")
        return f"ok-{agent_id}"

    with pytest.raises(RuntimeError) as excinfo:
        runner_main._run_ordered_agent_jobs(
            ["a1", "a2", "a3"],
            worker,
            concurrency=3,
            stage_name="round_1 revision",
        )

    message = str(excinfo.value)
    assert "round_1 revision parallel jobs failed" in message
    assert message.index("a1:") < message.index("a3:")
    assert "failed-a1" in message
    assert "failed-a3" in message

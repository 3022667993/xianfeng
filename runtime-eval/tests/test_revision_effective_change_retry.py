import json
from pathlib import Path

from runner.core import revision as rev


def _mk_play(tmp_path: Path) -> tuple[Path, Path]:
    play = tmp_path / "play"
    post = tmp_path / "post"
    (play / "submission").mkdir(parents=True, exist_ok=True)
    (play / "submission" / "main.py").write_text("AGGRESSION = 0\n", encoding="utf-8")
    return play, post


def test_require_effective_change_retries_and_fails_when_still_noop(tmp_path, monkeypatch):
    play, post = _mk_play(tmp_path)
    calls = []

    def fake_apply(*args, **kwargs):
        calls.append(bool(kwargs.get("retry_on_noop")))
        submission = kwargs["submission_main_path"]
        # no-op both attempts
        return True, "openclaw-minimal revision applied: AGGRESSION unchanged"

    monkeypatch.setattr(rev, "_apply_openclaw_minimal_revision", fake_apply)

    ok, msg = rev.apply_minimal_revision(
        play,
        post,
        2,
        "left",
        model_id="m1",
        executor="openclaw-minimal",
        openclaw_agent_id="main",
        require_effective_submission_change=True,
        revision_retry_on_noop=1,
    )
    assert not ok
    assert "no effective submission/main.py change" in msg
    assert calls == [False, True]


def test_require_effective_change_retries_and_passes_when_retry_changes(tmp_path, monkeypatch):
    play, post = _mk_play(tmp_path)
    calls = []

    def fake_apply(*args, **kwargs):
        calls.append(bool(kwargs.get("retry_on_noop")))
        submission = kwargs["submission_main_path"]
        if kwargs.get("retry_on_noop"):
            submission.write_text("AGGRESSION = 1\n", encoding="utf-8")
            return True, "openclaw-minimal revision applied: AGGRESSION 0->1"
        return True, "openclaw-minimal revision applied: AGGRESSION unchanged"

    monkeypatch.setattr(rev, "_apply_openclaw_minimal_revision", fake_apply)

    ok, msg = rev.apply_minimal_revision(
        play,
        post,
        2,
        "left",
        model_id="m1",
        executor="openclaw-minimal",
        openclaw_agent_id="main",
        require_effective_submission_change=True,
        revision_retry_on_noop=1,
    )
    assert ok
    assert "applied" in msg
    assert calls == [False, True]
    assert (post / "submission" / "main.py").read_text(encoding="utf-8").strip() == "AGGRESSION = 1"


def test_no_retry_when_effective_change_not_required(tmp_path, monkeypatch):
    play, post = _mk_play(tmp_path)
    calls = []

    def fake_apply(*args, **kwargs):
        calls.append(bool(kwargs.get("retry_on_noop")))
        return True, "openclaw-minimal revision applied: AGGRESSION unchanged"

    monkeypatch.setattr(rev, "_apply_openclaw_minimal_revision", fake_apply)

    ok, _msg = rev.apply_minimal_revision(
        play,
        post,
        2,
        "left",
        model_id="m1",
        executor="openclaw-minimal",
        openclaw_agent_id="main",
        require_effective_submission_change=False,
        revision_retry_on_noop=1,
    )
    assert ok
    assert calls == [False]


def test_timeout_is_retryable_and_returns_clear_failure(tmp_path, monkeypatch):
    play, post = _mk_play(tmp_path)
    calls = []

    def fake_apply(*args, **kwargs):
        calls.append(bool(kwargs.get("retry_on_noop")))
        if len(calls) == 1:
            return False, "openclaw timeout"
        return False, "openclaw timeout"

    monkeypatch.setattr(rev, "_apply_openclaw_minimal_revision", fake_apply)

    ok, msg = rev.apply_minimal_revision(
        play,
        post,
        2,
        "left",
        model_id="m1",
        executor="openclaw-minimal",
        openclaw_agent_id="main",
        require_effective_submission_change=True,
        revision_retry_on_noop=1,
        revision_retry_on_timeout=1,
    )
    assert not ok
    assert "openclaw timeout" in msg
    assert calls == [False, True]


def test_context_overflow_is_retryable_and_returns_distinct_failure(tmp_path, monkeypatch):
    play, post = _mk_play(tmp_path)
    calls = []

    def fake_apply(*args, **kwargs):
        calls.append(bool(kwargs.get("retry_on_noop")))
        return False, "openclaw context overflow"

    monkeypatch.setattr(rev, "_apply_openclaw_minimal_revision", fake_apply)

    ok, msg = rev.apply_minimal_revision(
        play,
        post,
        2,
        "left",
        model_id="m1",
        executor="openclaw-minimal",
        openclaw_agent_id="main",
        require_effective_submission_change=True,
        revision_retry_on_noop=1,
        revision_retry_on_timeout=1,
    )
    assert not ok
    assert msg == "openclaw context overflow"
    assert calls == [False, True]


def test_revision_retries_contract_validation_failure_when_retry_budget_exists(tmp_path, monkeypatch):
    play, post = _mk_play(tmp_path)
    calls = []

    def fake_apply(*args, **kwargs):
        calls.append(bool(kwargs.get("retry_on_noop")))
        if len(calls) == 1:
            return (
                False,
                "openclaw-minimal revision failed: submission contract validation failed on "
                "real Pommerman observation: ValueError",
            )
        kwargs["submission_main_path"].write_text("AGGRESSION = 1\n", encoding="utf-8")
        return True, "openclaw-minimal revision applied: submission/main.py changed"

    monkeypatch.setattr(rev, "_apply_openclaw_minimal_revision", fake_apply)

    ok, msg = rev.apply_minimal_revision(
        play,
        post,
        2,
        "left",
        model_id="m1",
        executor="openclaw-minimal",
        openclaw_agent_id="main",
        require_effective_submission_change=True,
        revision_retry_on_noop=1,
    )
    assert ok
    assert "submission/main.py changed" in msg
    assert calls == [False, True]


def test_initial_synthesis_retries_contract_validation_failure_when_retry_budget_exists(tmp_path, monkeypatch):
    starter = tmp_path / "starter"
    post = tmp_path / "post"
    (starter / "submission").mkdir(parents=True, exist_ok=True)
    (starter / "submission" / "main.py").write_text("AGGRESSION = 0\n", encoding="utf-8")
    calls = []

    def fake_apply(*args, **kwargs):
        calls.append(bool(kwargs.get("retry_on_noop")))
        if len(calls) == 1:
            return (
                False,
                "openclaw-minimal initial synthesis failed: submission contract validation failed on "
                "real Pommerman observation: KeyError: 'agent_id'",
            )
        kwargs["submission_main_path"].write_text("AGGRESSION = 1\n", encoding="utf-8")
        return True, "openclaw-minimal initial synthesis applied: submission/main.py changed"

    monkeypatch.setattr(rev, "_apply_openclaw_minimal_initial_synthesis", fake_apply)

    ok, msg = rev.apply_minimal_initial_synthesis(
        starter,
        post,
        model_id="m1",
        executor="openclaw-minimal",
        openclaw_agent_id="main",
        require_effective_submission_change=True,
        initial_synthesis_retry_on_noop=1,
    )
    assert ok
    assert "submission/main.py changed" in msg
    assert calls == [False, True]

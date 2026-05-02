from pathlib import Path

from runner.core.revision import apply_minimal_revision


def _make_play_dir(tmp_path: Path) -> Path:
    play = tmp_path / "play"
    (play / "submission").mkdir(parents=True)
    (play / "submission" / "main.py").write_text(
        "AGGRESSION = 0\n", encoding="utf-8"
    )
    return play


def test_model_revision_fails_without_executor(tmp_path):
    play = _make_play_dir(tmp_path)
    post = tmp_path / "post"

    ok, msg = apply_minimal_revision(
        play,
        post,
        1,
        "left",
        model_id="model-a",
    )

    assert not ok
    assert "missing executor" in msg


def test_model_revision_fails_with_unsupported_executor(tmp_path):
    play = _make_play_dir(tmp_path)
    post = tmp_path / "post"

    ok, msg = apply_minimal_revision(
        play,
        post,
        1,
        "left",
        model_id="model-a",
        executor="rule-minimal",
    )

    assert not ok
    assert "unsupported executor" in msg


def test_smoke_revision_uses_rule_minimal_without_model(tmp_path):
    play = _make_play_dir(tmp_path)
    post = tmp_path / "post"

    ok, msg = apply_minimal_revision(
        play,
        post,
        1,
        "left",
    )

    assert ok, msg
    log_text = (post / "notes" / "revision_log.md").read_text(encoding="utf-8")
    assert "executor=rule-minimal" in log_text

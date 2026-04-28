from pathlib import Path

from runner.core.revision import apply_noop_revision


def test_noop_revision_creates_post(tmp_path):
    src = tmp_path / "play"
    src.mkdir()
    (src / "notes").mkdir()
    (src / "notes" / "revision_log.md").write_text("# Revision Log\n", encoding="utf-8")

    post = tmp_path / "post"
    ok, msg = apply_noop_revision(src, post, 1, "left")

    assert ok, msg
    assert (post / "notes" / "revision_log.md").exists()
    content = (post / "notes" / "revision_log.md").read_text(encoding="utf-8")
    assert "round_1" in content

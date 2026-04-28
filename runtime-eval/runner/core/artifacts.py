from __future__ import annotations

import json
from pathlib import Path


ROUND_FILES = [
    "scorecard.json",
    "stderr.log",
    "build.log",
    "test.log",
    "diff.patch",
    "feedback_package.json",
    "metadata.json",
]


def ensure_round_dir(round_idx: int) -> Path:
    round_dir = Path("logs") / f"round_{round_idx}"
    round_dir.mkdir(parents=True, exist_ok=True)

    for name in ROUND_FILES:
        path = round_dir / name
        if not path.exists():
            if path.suffix == ".json":
                path.write_text("{}", encoding="utf-8")
            else:
                path.touch()

    return round_dir


def write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

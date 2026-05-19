from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runner.core.pommerman_tournament_report import write_tournament_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tournament", required=False)
    parser.add_argument("--logs-root", default="logs")
    parser.add_argument("--posts-root", default="workspace/posts")
    args = parser.parse_args()

    logs_root = Path(args.logs_root)
    posts_root = Path(args.posts_root)
    write_tournament_report(
        tournament_name=args.tournament,
        logs_root=logs_root,
        posts_root=posts_root,
    )
    print(str(logs_root / "tournament_report.md"))
    print(str(logs_root / "tournament_report.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

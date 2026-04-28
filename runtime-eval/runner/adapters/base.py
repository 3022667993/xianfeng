from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class BaseGameAdapter(ABC):
    name: str = "base"

    @abstractmethod
    def validate_submission(self, codebase_dir: Path) -> tuple[bool, str]:
        raise NotImplementedError

    @abstractmethod
    def export_submission(self, codebase_dir: Path, submission_dir: Path) -> tuple[bool, str]:
        """
        从完整 codebase 导出真正参赛的 submission_t。
        """
        raise NotImplementedError

    @abstractmethod
    def run_match(
        self,
        left_codebase: Path,
        right_codebase: Path,
        round_dir: Path,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError

"""Execution context for zen_mode phases."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


@dataclass
class Context:
    """Execution context passed to all phases. Enables testing."""
    work_dir: Path
    task_file: str
    project_root: Path = field(default_factory=lambda: Path.cwd())
    flags: Set[str] = field(default_factory=set)
    costs: List[Dict[str, Any]] = field(default_factory=list)
    tokens: int = 0

    # Derived paths (computed on first access)
    _scout_file: Optional[Path] = field(default=None, repr=False)
    _plan_file: Optional[Path] = field(default=None, repr=False)
    _log_file: Optional[Path] = field(default=None, repr=False)
    _notes_file: Optional[Path] = field(default=None, repr=False)
    _backup_dir: Optional[Path] = field(default=None, repr=False)
    _test_output_file: Optional[Path] = field(default=None, repr=False)
    _baseline_file: Optional[Path] = field(default=None, repr=False)

    @property
    def scout_file(self) -> Path:
        if self._scout_file is None:
            self._scout_file = self.work_dir / "scout.md"
        return self._scout_file

    @property
    def plan_file(self) -> Path:
        if self._plan_file is None:
            self._plan_file = self.work_dir / "plan.md"
        return self._plan_file

    @property
    def log_file(self) -> Path:
        if self._log_file is None:
            self._log_file = self.work_dir / "log.md"
        return self._log_file

    @property
    def notes_file(self) -> Path:
        if self._notes_file is None:
            self._notes_file = self.work_dir / "final_notes.md"
        return self._notes_file

    @property
    def backup_dir(self) -> Path:
        if self._backup_dir is None:
            self._backup_dir = self.work_dir / "backup"
        return self._backup_dir

    @property
    def test_output_file(self) -> Path:
        if self._test_output_file is None:
            self._test_output_file = self.work_dir / "test_output.txt"
        return self._test_output_file

    @property
    def baseline_file(self) -> Path:
        if self._baseline_file is None:
            self._baseline_file = self.work_dir / "lint_baseline.json"
        return self._baseline_file

    def record_cost(self, phase: str, cost: float, tokens: Dict[str, int]) -> None:
        """Record cost and tokens for a phase."""
        self.costs.append({
            "phase": phase,
            "cost": cost,
            "tokens": tokens,
        })
        self.tokens += tokens.get("in", 0) + tokens.get("out", 0)

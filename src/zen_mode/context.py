"""Execution context for zen_mode phases."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from zen_mode.exceptions import CostBudgetExceeded


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
        """Record cost and tokens for a phase.

        Args:
            phase: Phase name (scout, plan, implement, etc.)
            cost: Cost in USD for this call
            tokens: Token counts dict with 'in', 'out', 'cache_read' keys

        Raises:
            CostBudgetExceeded: If total cost exceeds MAX_COST_PER_TASK (when > 0)
        """
        self.costs.append({
            "phase": phase,
            "cost": cost,
            "tokens": tokens,
        })
        self.tokens += tokens.get("in", 0) + tokens.get("out", 0)

        # Check budget if configured (MAX_COST_PER_TASK > 0)
        # Import dynamically to pick up any runtime changes to config
        from zen_mode.config import MAX_COST_PER_TASK
        if MAX_COST_PER_TASK > 0:
            total_cost = sum(entry["cost"] for entry in self.costs)
            if total_cost > MAX_COST_PER_TASK:
                raise CostBudgetExceeded(
                    f"Cost budget exceeded: ${total_cost:.4f} > ${MAX_COST_PER_TASK:.4f}\n"
                    f"  Phase: {phase}\n"
                    f"  Set ZEN_MAX_COST env var to increase limit or set to 0 to disable"
                )

    def log(self, msg: str) -> None:
        """Log a message to the context's log file.

        This consolidates the _log_ctx pattern used across phases.
        """
        from zen_mode.files import log as file_log
        file_log(msg, self.log_file, self.work_dir)

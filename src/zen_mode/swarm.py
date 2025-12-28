"""
Zen Swarm: Parallel task execution with cost aggregation and
conflict detection.
"""
from __future__ import annotations
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from uuid import uuid4

logger = logging.getLogger(__name__)

from zen_mode.claude import run_claude
from zen_mode.config import TIMEOUT_EXEC, MODEL_EYES
from zen_mode.files import write_file
from zen_mode.scout import build_scout_prompt

# Configuration
TIMEOUT_WORKER = TIMEOUT_EXEC  # Use same timeout as core
STATUS_UPDATE_INTERVAL = 5  # seconds between status line updates


# ============================================================================
# News Ticker: Log Parsing and Status Display
# ============================================================================
def parse_worker_log(log_path: Path) -> Tuple[str, int, int, float]:
    """
    Parse worker log file to extract current status.

    Args:
        log_path: Path to worker's log.md file

    Returns:
        Tuple of (phase, current_step, total_steps, cost)
        phase: "scout", "plan", "step", "verify", "done", "error"
    """
    if not log_path.exists():
        return ("starting", 0, 0, 0.0)

    try:
        content = log_path.read_text(encoding="utf-8", errors="replace")
    except (IOError, OSError):
        return ("starting", 0, 0, 0.0)

    phase = "starting"
    current_step = 0
    total_steps = 0
    cost = 0.0

    # Parse total steps from [PLAN] Done. N steps.
    plan_match = re.search(r"\[PLAN\] Done\. (\d+) steps?\.", content)
    if plan_match:
        total_steps = int(plan_match.group(1))
        phase = "plan"

    # Parse current step from [STEP N] or [COMPLETE] Step N
    step_matches = re.findall(r"\[STEP (\d+)\]", content)
    if step_matches:
        current_step = int(step_matches[-1])  # Last step mentioned
        phase = "step"

    complete_matches = re.findall(r"\[COMPLETE\] Step (\d+)", content)
    if complete_matches:
        current_step = int(complete_matches[-1])

    # Check for verify phase
    if "[VERIFY]" in content:
        phase = "verify"

    # Check for errors
    if "[ERROR]" in content:
        phase = "error"

    # Sum up all costs
    cost_matches = re.findall(r"\[COST\].*?\$(\d+\.?\d*)", content)
    for c in cost_matches:
        try:
            cost += float(c)
        except ValueError:
            pass

    return (phase, current_step, total_steps, cost)


def format_status_block(
    completed: int,
    total: int,
    active: int,
    total_cost: float,
    worker_statuses: List[Tuple[int, str, int, int]]
) -> List[str]:
    """
    Format the news ticker as multiple lines.

    Args:
        completed: Number of completed tasks
        total: Total number of tasks
        active: Number of currently active workers
        total_cost: Aggregated cost so far
        worker_statuses: List of (task_num, phase, current_step, total_steps)

    Returns:
        List of lines to display
    """
    lines = []

    # Task status lines
    for task_num, phase, current, total_steps in worker_statuses:
        if phase == "step" and total_steps > 0:
            lines.append(f"  Task {task_num}: {current}/{total_steps}")
        elif phase == "verify":
            lines.append(f"  Task {task_num}: verify")
        elif phase == "error":
            lines.append(f"  Task {task_num}: ERROR")  # Show errors, don't hide
        elif phase == "done":
            pass  # Don't show completed (they're removed from list anyway)
        elif phase == "starting":
            lines.append(f"  Task {task_num}: starting")
        else:
            lines.append(f"  Task {task_num}: {phase}")

    # Summary line
    lines.append(f"[SWARM] {completed}/{total} done | Active: {active} | ${total_cost:.2f}")

    return lines


def print_status_block(lines: List[str], prev_line_count: int = 0, is_tty: bool = True) -> int:
    """Print status block, clearing previous output.

    Args:
        lines: Lines to print
        prev_line_count: Number of lines from previous call (for clearing)
        is_tty: Whether output is a TTY (enables ANSI escape codes)

    Returns:
        Number of lines printed (pass to next call as prev_line_count)
    """
    if is_tty:
        # Move up and clear previous lines
        if prev_line_count > 0:
            sys.stdout.write(f"\033[{prev_line_count}A")

        # Print new lines
        for line in lines:
            sys.stdout.write(f"\r{line}\033[K\n")
        sys.stdout.flush()

        return len(lines)
    else:
        # Non-TTY: just print summary line
        if lines:
            logger.info(lines[-1])
        return 0


# ============================================================================
# TARGETS Parsing
# ============================================================================
def parse_targets_header(task_path: Path) -> List[str]:
    """
    Extract and parse TARGETS header from task file.

    Reads task file, looks for first line starting with 'TARGETS:',
    parses comma-separated paths/globs, and returns list of target patterns.

    Args:
        task_path: Path to task markdown file

    Returns:
        List of target patterns (empty list if no TARGETS header found)
    """
    try:
        with open(task_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("TARGETS:"):
                    # Extract targets part after "TARGETS:"
                    targets_str = line[8:].strip()
                    # Split by comma and strip whitespace from each
                    targets = [t.strip() for t in targets_str.split(",") if t.strip()]
                    return targets
    except (FileNotFoundError, IOError):
        pass

    return []


def _normalize_path_for_comparison(path: Path) -> str:
    """
    Normalize path for comparison, handling Windows-specific issues.

    - Converts to lowercase on Windows (case-insensitive filesystem)
    - Normalizes path separators to forward slashes
    - Resolves to canonical absolute path
    """
    resolved = str(path.resolve())
    normalized = resolved.replace("\\", "/")
    if sys.platform == "win32":
        normalized = normalized.lower()
    return normalized


def _is_safe_path(target_path: Path, project_root: Path) -> bool:
    """
    Check if a path is safely within the project root.

    Handles Windows-specific path traversal attempts:
    - Case insensitivity
    - Both forward and backslash separators
    - UNC paths
    - Drive letter changes
    """
    try:
        resolved_target = target_path.resolve()
        resolved_root = project_root.resolve()

        target_str = _normalize_path_for_comparison(resolved_target)
        root_str = _normalize_path_for_comparison(resolved_root)

        # On Windows, block UNC paths and ensure same drive
        if sys.platform == "win32":
            if target_str.startswith("//"):
                return False
            if len(target_str) > 1 and len(root_str) > 1:
                if target_str[0].isalpha() and root_str[0].isalpha():
                    if target_str[0] != root_str[0]:
                        return False

        if not resolved_target.is_relative_to(resolved_root):
            return False

        if not target_str.startswith(root_str):
            return False

        return True
    except (ValueError, OSError):
        return False


def expand_targets(targets: List[str], project_root: Path) -> Set[Path]:
    """
    Expand glob patterns and literal paths into a set of resolved files.

    Args:
        targets: List of target patterns (globs or literal paths)
        project_root: Root directory to resolve paths against

    Returns:
        Set of expanded Path objects for all matched files
    """
    expanded: Set[Path] = set()

    for target in targets:
        # Normalize separators for Windows
        normalized_target = target.replace("\\", "/")

        # Skip absolute paths
        if Path(target).is_absolute() or Path(normalized_target).is_absolute():
            continue

        # Block path traversal patterns
        if ".." in normalized_target:
            logger.warning(f"[SWARM] Blocked path traversal attempt: {target}")
            continue

        pattern_path = project_root / normalized_target

        try:
            matches = list(project_root.glob(normalized_target))
            if matches:
                for m in matches:
                    if _is_safe_path(m, project_root):
                        expanded.add(m)
            elif pattern_path.exists():
                if _is_safe_path(pattern_path, project_root):
                    expanded.add(pattern_path)
        except (NotImplementedError, ValueError, OSError):
            continue

    return expanded


def detect_preflight_conflicts(task_paths: List[str], project_root: Path) -> Dict[str, List[str]]:
    """
    Detect TARGETS overlaps between tasks before execution.

    Expands all TARGETS headers and returns mapping of conflicting files
    to the tasks that target them.

    Args:
        task_paths: List of task file paths
        project_root: Root directory for path resolution

    Returns:
        Dict mapping file path to list of task paths that target it (conflicts only)
    """
    file_to_tasks: Dict[str, List[str]] = {}

    for task_path in task_paths:
        # Parse TARGETS from task file
        targets = parse_targets_header(Path(task_path))
        if not targets:
            continue

        # Expand glob patterns
        expanded = expand_targets(targets, project_root)

        # Record which tasks target each file
        for file_path in expanded:
            file_str = str(file_path.relative_to(project_root))
            if file_str not in file_to_tasks:
                file_to_tasks[file_str] = []
            file_to_tasks[file_str].append(task_path)

    # Return only files targeted by multiple tasks
    return {
        file: tasks for file, tasks in file_to_tasks.items()
        if len(tasks) > 1
    }


# ============================================================================
# Configuration
# ============================================================================
@dataclass
class SwarmConfig:
    """Configuration for swarm execution."""
    tasks: List[str]  # List of task file paths
    workers: int = 1  # Number of parallel workers
    project_root: Optional[Path] = None  # Project root directory
    work_dir_base: str = ".zen"  # Base directory for work folders
    verbose: bool = False  # Show full streaming logs instead of ticker

    def __post_init__(self):
        """Validate and normalize configuration."""
        if self.workers < 1:
            raise ValueError("workers must be >= 1")
        if not self.project_root:
            self.project_root = Path.cwd()


# ============================================================================
# Worker Execution
# ============================================================================
@dataclass
class WorkerResult:
    """Result from a single task execution."""
    task_path: str
    work_dir: str  # Path to .zen_<uuid> folder
    returncode: int
    cost: float = 0.0
    stdout: str = ""
    stderr: str = ""
    modified_files: List[str] = field(default_factory=list)

    def is_success(self) -> bool:
        """Check if task completed successfully."""
        return self.returncode == 0


def execute_worker_task(task_path: str, work_dir: str, project_root: Path,
                        scout_context: Optional[str] = None) -> WorkerResult:
    """
    Execute a single task in isolation.

    Args:
        task_path: Path to task markdown file
        work_dir: Working directory for this task (.zen_<uuid>)
        project_root: Root directory for the project
        scout_context: Optional path to shared scout context file

    Returns:
        WorkerResult with execution outcome
    """
    result = WorkerResult(
        task_path=task_path,
        work_dir=work_dir,
        returncode=0,
        modified_files=[]
    )

    # Build zen command - use 'zen' CLI directly
    cmd = [
        "zen",
        task_path,
    ]

    # Parse TARGETS from task file and add --allowed-files if present
    targets = parse_targets_header(Path(task_path))
    if targets:
        expanded = expand_targets(targets, project_root)
        if expanded:
            # Build glob pattern from expanded files
            # Use relative paths and join with comma
            rel_paths = [str(f.relative_to(project_root)) for f in expanded]
            allowed_files = ",".join(rel_paths)
            cmd.extend(["--allowed-files", allowed_files])

    # Add scout context if provided
    if scout_context:
        cmd.extend(["--scout-context", scout_context])

    try:
        # Create work directory
        work_path = project_root / work_dir
        work_path.mkdir(parents=True, exist_ok=True)

        # Override .zen folder via environment variable
        env = {**os.environ}
        env["ZEN_WORK_DIR"] = work_dir

        # Use file-based output to avoid pipe buffer deadlocks
        log_file = work_path / "log.md"

        with open(log_file, "a", encoding="utf-8") as log_f:
            proc = subprocess.run(
                cmd,
                cwd=project_root,
                stdin=subprocess.DEVNULL,
                stdout=log_f,
                stderr=log_f,
                timeout=TIMEOUT_WORKER,
                env=env,
            )

        result.returncode = proc.returncode
        result.stdout = log_file.read_text(encoding="utf-8") if log_file.exists() else ""
        result.stderr = ""

        # Extract cost from output
        result.cost = _extract_cost_from_output(result.stdout)

        # Detect modified files from work directory
        result.modified_files = _get_modified_files(work_path)

    except subprocess.TimeoutExpired:
        result.returncode = 124
        # Read partial output from log file on timeout
        result.stdout = log_file.read_text(encoding="utf-8") if log_file.exists() else ""
        result.stderr = f"Task timed out ({TIMEOUT_WORKER}s)"
    except Exception as e:
        result.returncode = 1
        result.stderr = str(e)

    return result


def _extract_cost_from_output(output: str) -> float:
    """
    Extract total cost from zen task output.
    Looks for patterns like: [COST] Total: $X.XXX or $X
    """
    match = re.search(r"\[COST\]\s+Total:\s+\$(\d+\.?\d*)", output)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return 0.0


def _get_modified_files(work_dir: Path) -> List[str]:
    """
    Extract list of modified files from work directory.
    Returns paths relative to work_dir (e.g., "src/file.py").
    Excludes zen's internal files (log.md, plan.md, backup/, etc.)
    """
    # Zen internal files to exclude (these live alongside modified source files in work_dir)
    EXCLUDED_FILES = {
        "log.md", "plan.md", "scout.md", "final_notes.md",
        "test_output.txt", "test_output_1.txt", "test_output_2.txt",
    }
    EXCLUDED_DIRS = {"backup"}

    modified = []
    if not work_dir.exists():
        return modified

    # Scan work directory for any files that exist
    # These represent modifications that occurred during task execution
    for item in work_dir.rglob("*"):
        if item.is_file():
            rel_path = item.relative_to(work_dir)
            rel_str = str(rel_path).replace("\\", "/")

            # Skip zen internal files
            if rel_path.name in EXCLUDED_FILES:
                continue

            # Skip files in excluded directories
            if any(part in EXCLUDED_DIRS for part in rel_path.parts):
                continue

            modified.append(str(rel_path))

    return modified


# ============================================================================
# Conflict Detection
# ============================================================================
def detect_file_conflicts(results: List[WorkerResult]) -> Dict[str, List[str]]:
    """
    Detect file overlaps between task executions.
    Returns mapping of file path to list of task indices that modified it.
    """
    file_to_tasks: Dict[str, List[str]] = {}

    for result in results:
        for file_path in result.modified_files:
            # Normalize path separators for cross-platform consistency
            normalized = file_path.replace("\\", "/")
            if normalized not in file_to_tasks:
                file_to_tasks[normalized] = []
            file_to_tasks[normalized].append(result.task_path)

    # Return only files with conflicts (modified by multiple tasks)
    return {
        file: tasks for file, tasks in file_to_tasks.items()
        if len(tasks) > 1
    }


# ============================================================================
# SwarmDispatcher
# ============================================================================
@dataclass
class SwarmSummary:
    """Summary of swarm execution results."""
    total_tasks: int
    succeeded: int
    failed: int
    total_cost: float
    task_results: List[WorkerResult]
    conflicts: Dict[str, List[str]] = field(default_factory=dict)

    def pass_fail_report(self) -> str:
        """Generate pass/fail summary report with visual formatting and conflict analysis."""
        lines = []

        # Title with box drawing
        lines.append("┌─ Swarm Execution Summary ─────────────────────────────┐")
        lines.append("│                                                        │")

        # Summary stats section with aligned columns
        passed_symbol = "✓" if self.succeeded > 0 else "✗"
        failed_symbol = "✗" if self.failed > 0 else "✓"

        lines.append(f"│  Total Tasks:    {self.total_tasks:<35} │")
        lines.append(f"│  {passed_symbol} Passed:        {self.succeeded:<35} │")
        lines.append(f"│  {failed_symbol} Failed:        {self.failed:<35} │")
        lines.append(f"│  Total Cost:     ${self.total_cost:<34.4f} │")

        lines.append("│                                                        │")

        # Failed tasks section
        if self.failed > 0:
            lines.append("├─ Failed Tasks ────────────────────────────────────────┤")
            for result in self.task_results:
                if not result.is_success():
                    lines.append(f"│  ✗ {result.task_path:<44} │")
                    lines.append(f"│    Exit Code: {result.returncode:<38} │")
                    if result.stderr:
                        error_msg = result.stderr[:46]
                        lines.append(f"│    {error_msg:<47} │")

        # Conflicts section
        if self.conflicts:
            if self.failed > 0:
                lines.append("├─ File Conflicts ──────────────────────────────────────┤")
            else:
                lines.append("├─ File Conflicts Detected ─────────────────────────────┤")
            for file_path, tasks in sorted(self.conflicts.items()):
                # Truncate long file paths to fit in box
                truncated_file = file_path if len(file_path) <= 46 else file_path[:43] + "..."
                lines.append(f"│  {truncated_file:<47} │")
                for task in tasks:
                    truncated_task = task if len(task) <= 45 else task[:42] + "..."
                    lines.append(f"│    → {truncated_task:<44} │")

        # Closing box
        lines.append("└────────────────────────────────────────────────────────┘")

        return "\n".join(lines)


class SwarmDispatcher:
    """
    Dispatches task execution across multiple worker processes.
    Aggregates results and costs.
    """

    def __init__(self, config: SwarmConfig):
        """
        Initialize dispatcher with configuration.

        Args:
            config: SwarmConfig instance with task list and worker count
        """
        self.config = config
        self.results: List[WorkerResult] = []

    def _run_shared_scout(self, task_path: str, scout_dir: Path, scout_file: Path) -> Optional[str]:
        """
        Run scout once for all tasks using the first task as reference.

        Args:
            task_path: Path to first task file (for context)
            scout_dir: Directory to create for shared scout output
            scout_file: Path where scout.md should be written

        Returns:
            Absolute path to scout context file, or None on failure
        """
        # Create scout directory
        scout_dir.mkdir(parents=True, exist_ok=True)

        # Build and run scout prompt
        prompt = build_scout_prompt(task_path, str(scout_file))
        output = run_claude(
            prompt,
            model=MODEL_EYES,
            phase="swarm_scout",
            project_root=self.config.project_root,
        )
        if not output:
            return None

        # Write output to scout file if Claude didn't
        if not scout_file.exists():
            write_file(scout_file, output, scout_dir)

        # Return absolute path to scout file
        return str(scout_file.resolve())

    def execute(self) -> SwarmSummary:
        """
        Execute all tasks in parallel using ProcessPoolExecutor.
        Runs scout once with the first task and shares the context.
        Shows news ticker status updates during execution.

        Returns:
            SwarmSummary with aggregated results and cost
        """
        self.results = []

        # Pre-flight check: detect TARGETS conflicts before execution
        conflicts = detect_preflight_conflicts(self.config.tasks, self.config.project_root)
        if conflicts:
            conflict_msg = "Preflight conflict detection failed:\n"
            for file_path, tasks in sorted(conflicts.items()):
                conflict_msg += f"[CONFLICT] {file_path} targeted by: {', '.join(tasks)}\n"
            raise ValueError(conflict_msg.rstrip())

        # Status display state (used by monitor thread via nonlocal)
        status_line_count = 0

        # Show startup message
        logger.info(f"[SWARM] Starting {len(self.config.tasks)} tasks with {self.config.workers} workers...")

        # Run scout once for all tasks using the first task as reference
        scout_context = None
        swarm_id = uuid4().hex[:8]
        base_dir = self.config.project_root / self.config.work_dir_base
        swarm_scout_dir = base_dir / f"swarm_{swarm_id}"
        scout_file = swarm_scout_dir / "scout.md"

        logger.info("[SWARM] Running shared scout...")
        first_task = self.config.tasks[0]
        scout_context = self._run_shared_scout(first_task, swarm_scout_dir, scout_file)

        # Generate unique work directories for each task (inside .zen/)
        task_configs = [
            (task, f"{self.config.work_dir_base}/worker_{uuid4().hex[:8]}", self.config.project_root,
             scout_context)
            for task in self.config.tasks
        ]

        # Track work directories for status monitoring
        # Map: work_dir -> (task_path, task_num)
        work_dir_map: Dict[str, Tuple[str, int]] = {}
        for idx, (task, work_dir, _, _) in enumerate(task_configs):
            work_dir_map[work_dir] = (task, idx + 1)  # 1-indexed task numbers

        # Status monitoring state - shared between main thread and monitor
        stop_monitoring = threading.Event()
        is_tty = sys.stdout.isatty()
        completed_tasks: Dict[str, bool] = {}  # work_dir -> completed (shared state)
        completed_lock = threading.Lock()
        total_tasks = len(self.config.tasks)
        max_completed_seen = 0  # Track high-water mark to prevent backwards display

        def status_monitor():
            """Background thread that polls worker logs and updates status."""
            nonlocal max_completed_seen, status_line_count
            while not stop_monitoring.wait(STATUS_UPDATE_INTERVAL):
                # Collect status from all workers
                worker_statuses = []
                total_cost = 0.0

                with completed_lock:
                    completed_count = len(completed_tasks)
                    completed_set = set(completed_tasks.keys())

                # Never show backwards progress (defensive fix for edge cases)
                max_completed_seen = max(max_completed_seen, completed_count)
                completed_count = max_completed_seen

                for work_dir, (task_path, task_num) in work_dir_map.items():
                    # Skip tasks that main thread marked as completed
                    if work_dir in completed_set:
                        continue

                    log_path = self.config.project_root / work_dir / "log.md"
                    phase, current, total, cost = parse_worker_log(log_path)
                    total_cost += cost
                    worker_statuses.append((task_num, phase, current, total))

                # Sort by task number for consistent display
                worker_statuses.sort(key=lambda x: x[0])

                active = len(worker_statuses)
                lines = format_status_block(
                    completed_count, total_tasks, active, total_cost, worker_statuses
                )
                status_line_count = print_status_block(lines, status_line_count, is_tty)

        # Start monitoring thread (unless verbose mode)
        monitor_thread = None
        if not self.config.verbose:
            monitor_thread = threading.Thread(target=status_monitor, daemon=True)
            monitor_thread.start()

        # Execute with ProcessPoolExecutor (manually managed to control shutdown)
        executor = ProcessPoolExecutor(max_workers=self.config.workers)
        timed_out = False
        try:
            # Submit all tasks
            futures = {
                executor.submit(execute_worker_task, task, work_dir, project_root,
                                scout_context): (task, work_dir)
                for task, work_dir, project_root, scout_context in task_configs
            }

            # Collect results as they complete (with timeout to prevent infinite hang)
            try:
                for future in as_completed(futures, timeout=TIMEOUT_WORKER):
                    task, work_dir = futures[future]
                    try:
                        result = future.result()
                    except Exception as e:
                        # Worker crashed - create failed result instead of crashing swarm
                        result = WorkerResult(
                            task_path=task,
                            work_dir=work_dir,
                            returncode=1,
                            stderr=f"Worker exception: {e}",
                        )
                    self.results.append(result)
                    # Mark task as completed for the monitor thread
                    with completed_lock:
                        completed_tasks[work_dir] = True
            except TimeoutError:
                # Swarm-level timeout - some workers didn't complete
                timed_out = True
                logger.error(f"[SWARM] Timeout after {TIMEOUT_WORKER}s waiting for workers")
                for future, (task, work_dir) in futures.items():
                    if not future.done():
                        logger.error(f"  - {task} still running")
                        future.cancel()
                        self.results.append(WorkerResult(
                            task_path=task,
                            work_dir=work_dir,
                            returncode=124,
                            stderr=f"Swarm timeout: worker did not complete within {TIMEOUT_WORKER}s",
                        ))
        finally:
            # Shutdown executor - don't wait if we timed out
            if timed_out:
                executor.shutdown(wait=False, cancel_futures=True)
            else:
                executor.shutdown(wait=True)

        # Stop monitoring thread
        if monitor_thread:
            stop_monitoring.set()
            monitor_thread.join(timeout=1)
            # Print final newline to move past status line
            if is_tty:
                logger.info("")

        # Preserve worker logs in .zen/workers/ before cleanup
        workers_log_dir = self.config.project_root / self.config.work_dir_base / "workers"
        workers_log_dir.mkdir(parents=True, exist_ok=True)

        for result in self.results:
            if result.work_dir:
                work_path = self.config.project_root / result.work_dir
                if work_path.exists():
                    # Copy log.md to workers/ with task name
                    src_log = work_path / "log.md"
                    if src_log.exists():
                        task_name = Path(result.task_path).stem
                        dst_log = workers_log_dir / f"{task_name}.log.md"
                        shutil.copy2(src_log, dst_log)

                    # Delete work directory for successful tasks
                    if result.is_success():
                        shutil.rmtree(work_path, ignore_errors=True)

        # Append worker summaries to main log
        main_log = self.config.project_root / self.config.work_dir_base / "log.md"
        with main_log.open("a", encoding="utf-8") as f:
            f.write(f"\n[SWARM] Completed {len(self.results)} tasks\n")
            for result in self.results:
                status = "✓" if result.is_success() else "✗"
                f.write(f"  {status} {result.task_path} (${result.cost:.4f})\n")
            f.write(f"[SWARM] Worker logs saved to {workers_log_dir}\n")

        # Cleanup scout directory
        if swarm_scout_dir.exists():
            shutil.rmtree(swarm_scout_dir, ignore_errors=True)

        return self._build_summary()

    def _build_summary(self) -> SwarmSummary:
        """Build summary from collected results with conflict detection."""
        succeeded = sum(1 for r in self.results if r.is_success())
        failed = len(self.results) - succeeded
        total_cost = sum(r.cost for r in self.results)
        conflicts = detect_file_conflicts(self.results)

        return SwarmSummary(
            total_tasks=len(self.results),
            succeeded=succeeded,
            failed=failed,
            total_cost=total_cost,
            task_results=self.results,
            conflicts=conflicts
        )

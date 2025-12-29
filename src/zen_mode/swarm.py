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
import signal
import atexit
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import uuid4

logger = logging.getLogger(__name__)

# Global tracking for atexit cleanup
_active_workers: Dict[int, subprocess.Popen] = {}
_active_workers_lock = threading.Lock()


def _cleanup_workers():
    """Kill any remaining worker processes on exit."""
    with _active_workers_lock:
        for pid, proc in list(_active_workers.items()):
            try:
                _kill_process_tree(proc, timeout=2.0)
            except Exception:
                pass


atexit.register(_cleanup_workers)

from zen_mode.config import TIMEOUT_EXEC
from zen_mode.files import write_file

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
    except (FileNotFoundError, IOError, UnicodeDecodeError, PermissionError):
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


# Sentinel for tasks without TARGETS (must run sequentially)
_NO_TARGETS_SENTINEL = "__NO_TARGETS__"


def _partition_tasks_by_conflict(
    task_paths: List[str],
    project_root: Path
) -> Tuple[List[List[str]], List[str]]:
    """
    Partition tasks into conflict groups based on overlapping targets.

    Uses connected components algorithm: if A overlaps B and B overlaps C,
    then A, B, C are all in the same conflict group (transitive).

    Args:
        task_paths: List of task file paths
        project_root: Root directory for path resolution

    Returns:
        (conflict_groups, parallel_tasks)
        - conflict_groups: Lists of tasks that must run sequentially within group
        - parallel_tasks: Tasks with no conflicts, can run fully parallel
    """
    # Build task -> files mapping
    task_to_files: Dict[str, Set[str]] = {}
    for task_path in task_paths:
        targets = parse_targets_header(Path(task_path))
        if not targets:
            # Tasks without TARGETS use sentinel (forces sequential)
            task_to_files[task_path] = {_NO_TARGETS_SENTINEL}
        else:
            # Expand targets relative to task file's directory, not project root
            task_dir = Path(task_path).parent.resolve()
            expanded = expand_targets(targets, task_dir)
            # Normalize to project-relative paths for comparison
            normalized: Set[str] = set()
            for f in expanded:
                try:
                    normalized.add(str(f.resolve().relative_to(project_root.resolve())))
                except ValueError:
                    # File outside project root - use absolute path
                    normalized.add(str(f.resolve()))
            task_to_files[task_path] = normalized
            if not task_to_files[task_path]:
                # TARGETS specified but no files matched - treat as no targets
                task_to_files[task_path] = {_NO_TARGETS_SENTINEL}

    # Build file -> tasks mapping
    file_to_tasks: Dict[str, List[str]] = {}
    for task_path, files in task_to_files.items():
        for file_path in files:
            if file_path not in file_to_tasks:
                file_to_tasks[file_path] = []
            file_to_tasks[file_path].append(task_path)

    # Find connected components using union-find
    parent: Dict[str, str] = {t: t for t in task_paths}

    def find(x: str) -> str:
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(a: str, b: str) -> None:
        pa, pb = find(a), find(b)
        if pa != pb:
            parent[pa] = pb

    # Union tasks that share files
    for tasks in file_to_tasks.values():
        for i in range(1, len(tasks)):
            union(tasks[0], tasks[i])

    # Group tasks by their root
    groups: Dict[str, List[str]] = {}
    for task in task_paths:
        root = find(task)
        if root not in groups:
            groups[root] = []
        groups[root].append(task)

    # Separate conflict groups (size > 1) from parallel tasks (size == 1)
    conflict_groups: List[List[str]] = []
    parallel_tasks: List[str] = []
    for group in groups.values():
        if len(group) > 1:
            conflict_groups.append(group)
        else:
            parallel_tasks.append(group[0])

    return conflict_groups, parallel_tasks


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
def _kill_process_tree(proc: subprocess.Popen, timeout: float = 5.0) -> None:
    """Kill process and all children. Cross-platform."""
    try:
        if sys.platform == "win32":
            # Windows: use taskkill to kill entire process tree
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=timeout,
            )
        else:
            # Unix: kill entire process group
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, OSError):
                pass  # Process already dead
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    pass
        # Reap zombie
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
    except (ProcessLookupError, OSError, subprocess.TimeoutExpired):
        pass  # Process already dead


def _run_worker_popen(
    cmd: List[str],
    cwd: Path,
    env: dict,
    log_file: Path,
    timeout: float,
) -> Tuple[int, bool]:
    """
    Run command with Popen, kill on timeout.
    Returns (returncode, was_killed).
    """
    kwargs: Dict[str, Any] = {
        "cwd": cwd,
        "stdin": subprocess.DEVNULL,
        "env": env,
    }
    # Create process group for tree killing
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    with open(log_file, "a", encoding="utf-8") as log_f:
        kwargs["stdout"] = log_f
        kwargs["stderr"] = log_f
        proc = subprocess.Popen(cmd, **kwargs)

        try:
            proc.wait(timeout=timeout)
            return (proc.returncode, False)
        except subprocess.TimeoutExpired:
            # Race window: process might have exited
            if proc.poll() is not None:
                return (proc.returncode, False)
            logger.warning(f"[SWARM] Killing worker PID {proc.pid} after {timeout}s timeout")
            _kill_process_tree(proc)
            return (124, True)


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

        returncode, was_killed = _run_worker_popen(
            cmd=cmd,
            cwd=project_root,
            env=env,
            log_file=log_file,
            timeout=TIMEOUT_WORKER,
        )
        result.returncode = returncode
        if was_killed:
            result.stderr = f"Task killed after timeout ({TIMEOUT_WORKER}s)"

        try:
            result.stdout = log_file.read_text(encoding="utf-8", errors="replace")
        except (OSError, FileNotFoundError):
            result.stdout = ""

        # Extract cost from output
        result.cost = _extract_cost_from_output(result.stdout)

        # Detect modified files from work directory
        result.modified_files = _get_modified_files(work_path)

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


def _worker_thread_target(
    task_config: Tuple[str, Path, Path, Optional[str]],
    results_dict: Dict[str, "WorkerResult"],
    results_lock: threading.Lock,
    semaphore: threading.Semaphore,
    completed_tasks: Dict[str, bool],
    completed_lock: threading.Lock,
) -> None:
    """
    Thread target that executes a worker task.

    Note: Daemon thread - will be killed on Ctrl+C. Results may be incomplete
    on interrupt, but worker logs are preserved in .zen/worker_*/log.md
    """
    task, work_dir, project_root, scout_context = task_config

    try:
        with semaphore:
            result = execute_worker_task(task, str(work_dir), project_root, scout_context)
    except BaseException as e:
        logger.error(f"[SWARM] Worker thread crashed: {e}")
        result = WorkerResult(
            task_path=task,
            work_dir=str(work_dir),
            returncode=1,
            stderr=f"Worker thread crashed: {type(e).__name__}: {e}",
        )

    with results_lock:
        results_dict[str(work_dir)] = result
    with completed_lock:
        completed_tasks[str(work_dir)] = True


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
        """Generate pass/fail summary report with visual formatting and conflict analysis.

        Uses ASCII characters for Windows compatibility (cp1252 can't encode Unicode box-drawing).
        """
        lines = []

        # Title with ASCII box drawing (Windows compatible)
        lines.append("+-- Swarm Execution Summary ----------------------------+")
        lines.append("|                                                        |")

        # Summary stats section with aligned columns
        passed_symbol = "[OK]" if self.succeeded > 0 else "[X]"
        failed_symbol = "[X]" if self.failed > 0 else "[OK]"

        lines.append(f"|  Total Tasks:    {self.total_tasks:<35} |")
        lines.append(f"|  {passed_symbol} Passed:      {self.succeeded:<35} |")
        lines.append(f"|  {failed_symbol} Failed:      {self.failed:<35} |")
        lines.append(f"|  Total Cost:     ${self.total_cost:<34.4f} |")

        lines.append("|                                                        |")

        # Failed tasks section
        if self.failed > 0:
            lines.append("+-- Failed Tasks ---------------------------------------+")
            for result in self.task_results:
                if not result.is_success():
                    lines.append(f"|  [X] {result.task_path:<42} |")
                    lines.append(f"|      Exit Code: {result.returncode:<36} |")
                    if result.stderr:
                        error_msg = result.stderr[:44]
                        lines.append(f"|      {error_msg:<45} |")

        # Conflicts section
        if self.conflicts:
            if self.failed > 0:
                lines.append("+-- File Conflicts -------------------------------------+")
            else:
                lines.append("+-- File Conflicts Detected ----------------------------+")
            for file_path, tasks in sorted(self.conflicts.items()):
                # Truncate long file paths to fit in box
                truncated_file = file_path if len(file_path) <= 46 else file_path[:43] + "..."
                lines.append(f"|  {truncated_file:<47} |")
                for task in tasks:
                    truncated_task = task if len(task) <= 45 else task[:42] + "..."
                    lines.append(f"|    -> {truncated_task:<43} |")

        # Closing box
        lines.append("+--------------------------------------------------------+")

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

    def _run_tasks_parallel(
        self,
        tasks: List[str],
        task_num_offset: int,
        work_dir_map: Dict[str, Tuple[str, int]],
        results_dict: Dict[str, WorkerResult],
        results_lock: threading.Lock,
        completed_tasks: Dict[str, bool],
        completed_lock: threading.Lock,
    ) -> List[Tuple[str, str]]:
        """
        Run a batch of tasks in parallel with the configured worker count.

        Returns list of (task, work_dir) tuples for tracking.
        """
        scout_context = None
        task_configs = [
            (task, f"{self.config.work_dir_base}/worker_{uuid4().hex[:8]}",
             self.config.project_root, scout_context)
            for task in tasks
        ]

        # Update work_dir_map for status monitoring
        for idx, (task, work_dir, _, _) in enumerate(task_configs):
            work_dir_map[work_dir] = (task, task_num_offset + idx)

        # Thread-based execution with Popen
        semaphore = threading.Semaphore(self.config.workers)
        worker_threads: List[threading.Thread] = []

        for task_config in task_configs:
            t = threading.Thread(
                target=_worker_thread_target,
                args=(task_config, results_dict, results_lock, semaphore,
                      completed_tasks, completed_lock),
                daemon=True,
            )
            t.start()
            worker_threads.append(t)

        # Wait for all threads with overall timeout
        deadline = time.time() + TIMEOUT_WORKER + 30
        for t in worker_threads:
            remaining = max(0.1, deadline - time.time())
            t.join(timeout=remaining)

        # Check for stragglers
        for idx, t in enumerate(worker_threads):
            if t.is_alive():
                task, work_dir, _, _ = task_configs[idx]
                logger.error(f"[SWARM] Worker thread for {task} did not complete")
                with results_lock:
                    if work_dir not in results_dict:
                        results_dict[work_dir] = WorkerResult(
                            task_path=task,
                            work_dir=work_dir,
                            returncode=124,
                            stderr="Worker thread did not complete within timeout",
                        )

        return [(tc[0], tc[1]) for tc in task_configs]

    def execute(self) -> SwarmSummary:
        """
        Execute all tasks with conflict-aware scheduling.

        Tasks with overlapping targets run sequentially within their conflict group.
        Tasks with no conflicts run in parallel.
        Tasks without TARGETS run sequentially (conservative fallback).

        Returns:
            SwarmSummary with aggregated results and cost
        """
        self.results = []

        # Partition tasks by conflict
        conflict_groups, parallel_tasks = _partition_tasks_by_conflict(
            self.config.tasks, self.config.project_root
        )

        # Log partitioning results
        total_tasks = len(self.config.tasks)
        if conflict_groups:
            conflict_count = sum(len(g) for g in conflict_groups)
            logger.info(f"[SWARM] {conflict_count} tasks have conflicts, will run sequentially in {len(conflict_groups)} group(s)")
            for i, group in enumerate(conflict_groups):
                task_names = [Path(t).name for t in group]
                logger.info(f"[SWARM]   Group {i+1}: {', '.join(task_names)}")

        logger.info(f"[SWARM] Starting {total_tasks} tasks with {self.config.workers} workers...")

        # Status display state
        status_line_count = 0
        work_dir_map: Dict[str, Tuple[str, int]] = {}
        stop_monitoring = threading.Event()
        is_tty = sys.stdout.isatty()
        completed_tasks: Dict[str, bool] = {}
        completed_lock = threading.Lock()
        max_completed_seen = 0
        results_dict: Dict[str, WorkerResult] = {}
        results_lock = threading.Lock()
        task_num_counter = 1

        def status_monitor():
            """Background thread that polls worker logs and updates status."""
            nonlocal max_completed_seen, status_line_count
            while not stop_monitoring.wait(STATUS_UPDATE_INTERVAL):
                worker_statuses = []
                total_cost = 0.0

                with completed_lock:
                    completed_count = len(completed_tasks)
                    completed_set = set(completed_tasks.keys())

                max_completed_seen = max(max_completed_seen, completed_count)
                completed_count = max_completed_seen

                for work_dir, (task_path, task_num) in work_dir_map.items():
                    if work_dir in completed_set:
                        continue
                    log_path = self.config.project_root / work_dir / "log.md"
                    phase, current, total, cost = parse_worker_log(log_path)
                    total_cost += cost
                    worker_statuses.append((task_num, phase, current, total))

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

        # Phase 1: Run conflict groups sequentially (tasks within each group run one at a time)
        for group in conflict_groups:
            for task in group:
                self._run_tasks_parallel(
                    [task], task_num_counter, work_dir_map, results_dict,
                    results_lock, completed_tasks, completed_lock
                )
                task_num_counter += 1

        # Phase 2: Run parallel tasks (all at once, respecting worker limit)
        if parallel_tasks:
            self._run_tasks_parallel(
                parallel_tasks, task_num_counter, work_dir_map, results_dict,
                results_lock, completed_tasks, completed_lock
            )

        # Collect all results
        with results_lock:
            self.results = list(results_dict.values())

        # Stop monitoring thread
        if monitor_thread:
            stop_monitoring.set()
            monitor_thread.join(timeout=1)
            if is_tty:
                logger.info("")

        # Preserve worker logs in .zen/workers/ before cleanup
        workers_log_dir = self.config.project_root / self.config.work_dir_base / "workers"
        workers_log_dir.mkdir(parents=True, exist_ok=True)

        for result in self.results:
            if result.work_dir:
                work_path = self.config.project_root / result.work_dir
                if work_path.exists():
                    src_log = work_path / "log.md"
                    if src_log.exists():
                        task_name = Path(result.task_path).stem
                        dst_log = workers_log_dir / f"{task_name}.log.md"
                        shutil.copy2(src_log, dst_log)
                    if result.is_success():
                        shutil.rmtree(work_path, ignore_errors=True)

        # Append worker summaries to main log
        main_log = self.config.project_root / self.config.work_dir_base / "log.md"
        with main_log.open("a", encoding="utf-8") as f:
            f.write(f"\n[SWARM] Completed {len(self.results)} tasks\n")
            for result in self.results:
                status = "+" if result.is_success() else "x"
                f.write(f"  {status} {result.task_path} (${result.cost:.4f})\n")
            f.write(f"[SWARM] Worker logs saved to {workers_log_dir}\n")

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

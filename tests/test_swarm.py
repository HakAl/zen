"""
Tests for swarm dispatcher functionality.
"""
import subprocess
import sys
import os
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# Import from package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from zen_mode.swarm import (  # noqa: E402
    SwarmConfig,
    SwarmDispatcher,
    SwarmSummary,
    WorkerResult,
    execute_worker_task,
    detect_file_conflicts,
    parse_targets_header,
    expand_targets,
    detect_preflight_conflicts,
    _extract_cost_from_output,
    _partition_tasks_by_conflict,
    _NO_TARGETS_SENTINEL,
)
from zen_mode.swarm import _get_modified_files


class TestSwarmDispatcher:
    """Tests for SwarmDispatcher class."""

    def test_execute_success_path(self):
        """Test successful execution with all tasks passing."""
        config = SwarmConfig(
            tasks=["task1.md", "task2.md"],
            workers=2,
            project_root=Path.cwd(),
        )
        dispatcher = SwarmDispatcher(config)

        # Mock worker results - test _build_summary directly
        mock_results = [
            WorkerResult(task_path="task1.md", work_dir=".zen_abc1", returncode=0, cost=0.01),
            WorkerResult(task_path="task2.md", work_dir=".zen_abc2", returncode=0, cost=0.02),
        ]

        # Manually set results and test _build_summary
        dispatcher.results = mock_results

        summary = dispatcher._build_summary()

        assert summary.total_tasks == 2
        assert summary.succeeded == 2
        assert summary.failed == 0
        assert summary.total_cost == 0.03

    def test_execute_with_failures(self):
        """Test execution with some tasks failing."""
        config = SwarmConfig(
            tasks=["task1.md", "task2.md"],
            workers=1,
            project_root=Path.cwd(),
        )
        dispatcher = SwarmDispatcher(config)

        # Mock results with one failure
        mock_results = [
            WorkerResult(task_path="task1.md", work_dir=".zen_abc1", returncode=0, cost=0.01),
            WorkerResult(
                task_path="task2.md",
                work_dir=".zen_abc2",
                returncode=1,
                cost=0.0,
                stderr="Task failed",
            ),
        ]
        dispatcher.results = mock_results

        summary = dispatcher._build_summary()

        assert summary.total_tasks == 2
        assert summary.succeeded == 1
        assert summary.failed == 1
        assert summary.total_cost == 0.01

    def test_pass_fail_report_formatting(self):
        """Test pass/fail report generation with failures and new formatting elements."""
        results = [
            WorkerResult(task_path="task1.md", work_dir=".zen_abc1", returncode=0, cost=0.01),
            WorkerResult(
                task_path="task2.md",
                work_dir=".zen_abc2",
                returncode=1,
                cost=0.0,
                stderr="Connection timeout",
            ),
        ]

        summary = SwarmSummary(
            total_tasks=2,
            succeeded=1,
            failed=1,
            total_cost=0.01,
            task_results=results,
        )

        report = summary.pass_fail_report()

        # Verify title and box-drawing characters (ASCII for Windows compatibility)
        assert "Swarm Execution Summary" in report
        assert "+--" in report  # ASCII box corners
        assert "|" in report    # ASCII box sides

        # Verify summary stats section with correct labels
        assert "Total Tasks:" in report
        assert "Passed:" in report
        assert "Failed:" in report
        assert "Total Cost:" in report

        # Verify stat values
        assert "2" in report  # Total tasks
        assert "1" in report  # Passed count
        assert "$0.0100" in report  # Cost formatted with 4 decimals

        # Verify status indicators (ASCII for Windows compatibility)
        assert "[OK]" in report
        assert "[X]" in report

        # Verify failed tasks section header and content
        assert "Failed Tasks" in report
        assert "task2.md" in report
        assert "Connection timeout" in report
        assert "Exit Code:" in report


class TestWorkerExecution:
    """Tests for worker execution function."""

    def test_execute_worker_task_timeout_error(self, tmp_path):
        """Test timeout handling for long-running tasks."""
        with patch("zen_mode.swarm.subprocess.Popen") as mock_popen:
            mock_proc = Mock()
            mock_proc.wait.side_effect = subprocess.TimeoutExpired("cmd", 600)
            mock_proc.poll.return_value = None  # Process still running
            mock_proc.pid = 12345
            mock_proc.returncode = None
            mock_popen.return_value = mock_proc

            with patch("zen_mode.swarm._kill_process_tree"):
                result = execute_worker_task(
                    task_path="task.md",
                    work_dir=".zen_test",
                    project_root=tmp_path,
                )

            assert result.returncode == 124
            assert "timeout" in result.stderr.lower()

    def test_execute_worker_task_cost_extraction(self, tmp_path):
        """Test cost extraction from subprocess output."""
        log_content = "Running task...\n[COST] Total: $0.0456\nTask complete"

        with patch("zen_mode.swarm.subprocess.Popen") as mock_popen:
            mock_proc = Mock()
            mock_proc.wait.return_value = None  # No timeout
            mock_proc.returncode = 0
            mock_proc.pid = 12345
            mock_popen.return_value = mock_proc

            # Write log content when Popen is created (simulating stdout write)
            def setup_popen(cmd, **kwargs):
                stdout_file = kwargs.get("stdout")
                if stdout_file and hasattr(stdout_file, "write"):
                    stdout_file.write(log_content)
                return mock_proc

            mock_popen.side_effect = setup_popen

            with patch("zen_mode.swarm._get_modified_files") as mock_files:
                mock_files.return_value = []

                result = execute_worker_task(
                    task_path="task.md",
                    work_dir=".zen_test",
                    project_root=tmp_path,
                )

                assert result.cost == 0.0456
                assert result.returncode == 0


class TestConflictDetection:
    """Tests for file conflict detection."""

    def test_detect_file_conflicts_with_overlaps(self):
        """Test detection of conflicting file modifications."""
        results = [
            WorkerResult(
                task_path="task1.md",
                work_dir=".zen_1",
                returncode=0,
                modified_files=["src/file.py", "config.yaml"]
            ),
            WorkerResult(
                task_path="task2.md",
                work_dir=".zen_2",
                returncode=0,
                modified_files=["src/file.py", "data.json"]
            ),
        ]

        conflicts = detect_file_conflicts(results)

        assert "src/file.py" in conflicts
        assert len(conflicts["src/file.py"]) == 2
        assert "task1.md" in conflicts["src/file.py"]
        assert "task2.md" in conflicts["src/file.py"]

    def test_detect_file_conflicts_no_overlaps(self):
        """Test no conflicts when tasks modify different files."""
        results = [
            WorkerResult(
                task_path="task1.md",
                work_dir=".zen_1",
                returncode=0,
                modified_files=[".zen_1/file_a.py"]
            ),
            WorkerResult(
                task_path="task2.md",
                work_dir=".zen_2",
                returncode=0,
                modified_files=[".zen_2/file_b.py"]
            ),
        ]

        conflicts = detect_file_conflicts(results)

        assert len(conflicts) == 0

    def test_detect_file_conflicts_empty_results(self):
        """Test conflict detection with empty results list."""
        conflicts = detect_file_conflicts([])
        assert conflicts == {}


class TestSwarmConfig:
    """Tests for SwarmConfig dataclass."""

    def test_swarm_config_validation_invalid_workers(self):
        """Test validation rejects invalid worker count."""
        with pytest.raises(ValueError, match="workers must be >= 1"):
            SwarmConfig(tasks=["task.md"], workers=0)

    def test_swarm_config_default_project_root(self):
        """Test default project root is set to current directory."""
        config = SwarmConfig(tasks=["task.md"])
        assert config.project_root == Path.cwd()

    def test_swarm_config_with_explicit_root(self):
        """Test explicit project root is preserved."""
        custom_root = Path("/custom/root")
        config = SwarmConfig(tasks=["task.md"], project_root=custom_root)
        assert config.project_root == custom_root


class TestCostExtraction:
    """Tests for cost extraction helper function."""

    def test_extract_cost_standard_format(self):
        """Test extraction of standard cost format."""
        output = "Task running...\n[COST] Total: $1.2345\nDone"
        cost = _extract_cost_from_output(output)
        assert cost == 1.2345

    def test_extract_cost_missing_pattern(self):
        """Test returns 0.0 when cost pattern not found."""
        output = "Task running...\nNo cost information"
        cost = _extract_cost_from_output(output)
        assert cost == 0.0

    def test_extract_cost_malformed_value(self):
        """Test handles malformed cost values gracefully."""
        output = "[COST] Total: $invalid"
        cost = _extract_cost_from_output(output)
        assert cost == 0.0


class TestTargetsParsing:
    """Tests for TARGETS header parsing."""

    def test_parse_targets_valid_header(self, tmp_path):
        """Test parsing valid TARGETS header with comma-separated paths."""
        task_file = tmp_path / "task.md"
        task_file.write_text("TARGETS: src/file1.py, src/file2.py, tests/*.py\n\nTask content")

        targets = parse_targets_header(task_file)

        assert targets == ["src/file1.py", "src/file2.py", "tests/*.py"]

    def test_parse_targets_missing_header(self, tmp_path):
        """Test returns empty list when TARGETS header not found."""
        task_file = tmp_path / "task.md"
        task_file.write_text("# Task Title\n\nNo targets here")

        targets = parse_targets_header(task_file)

        assert targets == []

    def test_parse_targets_whitespace_variations(self, tmp_path):
        """Test handles whitespace variations in comma-separated list."""
        task_file = tmp_path / "task.md"
        task_file.write_text("TARGETS:src/a.py,  src/b.py  , src/c.py")

        targets = parse_targets_header(task_file)

        assert targets == ["src/a.py", "src/b.py", "src/c.py"]


class TestGlobExpansion:
    """Tests for glob expansion functionality."""

    def test_expand_targets_glob_pattern(self, tmp_path):
        """Test glob expansion with wildcard patterns."""
        # Create test files
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "file1.py").touch()
        (tmp_path / "src" / "file2.py").touch()

        targets = ["src/*.py"]
        expanded = expand_targets(targets, tmp_path)

        assert len(expanded) == 2
        assert tmp_path / "src" / "file1.py" in expanded
        assert tmp_path / "src" / "file2.py" in expanded

    def test_expand_targets_literal_path(self, tmp_path):
        """Test expansion with literal file paths."""
        test_file = tmp_path / "test.py"
        test_file.touch()

        targets = ["test.py"]
        expanded = expand_targets(targets, tmp_path)

        assert len(expanded) == 1
        assert test_file in expanded

    def test_expand_targets_missing_files(self, tmp_path):
        """Test returns empty set for non-existent files."""
        targets = ["nonexistent/*.py", "missing.txt"]
        expanded = expand_targets(targets, tmp_path)

        assert len(expanded) == 0


class TestPreflightConflictDetection:
    """Tests for pre-flight conflict detection."""

    def test_detect_preflight_conflicts_overlapping(self, tmp_path):
        """Test detection of overlapping TARGETS between tasks."""
        # Create test files
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "shared.py").touch()

        # Create task files with overlapping targets
        task1 = tmp_path / "task1.md"
        task1.write_text("TARGETS: src/shared.py, src/file1.py\n")

        task2 = tmp_path / "task2.md"
        task2.write_text("TARGETS: src/shared.py\n")

        # Only create shared.py to match targets
        conflicts = detect_preflight_conflicts(
            [str(task1), str(task2)],
            tmp_path
        )

        # Normalize path to forward slashes for cross-platform compatibility
        conflict_files = [k.replace("\\", "/") for k in conflicts.keys()]
        assert "src/shared.py" in conflict_files

        # Get the actual conflict key and verify count
        actual_key = [k for k in conflicts.keys() if k.replace("\\", "/") == "src/shared.py"][0]
        assert len(conflicts[actual_key]) == 2

    def test_detect_preflight_conflicts_no_overlap(self, tmp_path):
        """Test no conflicts when tasks have different targets."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "file1.py").touch()
        (tmp_path / "src" / "file2.py").touch()

        task1 = tmp_path / "task1.md"
        task1.write_text("TARGETS: src/file1.py\n")

        task2 = tmp_path / "task2.md"
        task2.write_text("TARGETS: src/file2.py\n")

        conflicts = detect_preflight_conflicts(
            [str(task1), str(task2)],
            tmp_path
        )

        assert len(conflicts) == 0


class TestSwarmDispatcherPreflight:
    """Tests for pre-flight conflict detection in SwarmDispatcher.execute()."""

    def test_execute_handles_conflicts_with_sequential_fallback(self, tmp_path):
        """Test execute() runs conflicting tasks sequentially instead of failing."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "shared.py").touch()

        task1 = tmp_path / "task1.md"
        task1.write_text("TARGETS: src/shared.py\n")

        task2 = tmp_path / "task2.md"
        task2.write_text("TARGETS: src/shared.py\n")

        config = SwarmConfig(
            tasks=[str(task1), str(task2)],
            workers=2,
            project_root=tmp_path,
        )
        dispatcher = SwarmDispatcher(config)

        with patch("zen_mode.swarm.execute_worker_task") as mock_execute:
            mock_execute.side_effect = [
                WorkerResult(task_path=str(task1), work_dir=".zen_1", returncode=0),
                WorkerResult(task_path=str(task2), work_dir=".zen_2", returncode=0),
            ]

            # Should NOT raise - conflicts are handled via sequential fallback
            summary = dispatcher.execute()
            assert summary.total_tasks == 2
            assert summary.succeeded == 2

    def test_execute_succeeds_with_no_preflight_conflicts(self, tmp_path):
        """Test execute() proceeds when no TARGETS conflicts exist."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "file1.py").touch()
        (tmp_path / "src" / "file2.py").touch()

        task1 = tmp_path / "task1.md"
        task1.write_text("TARGETS: src/file1.py\n")

        task2 = tmp_path / "task2.md"
        task2.write_text("TARGETS: src/file2.py\n")

        config = SwarmConfig(
            tasks=[str(task1), str(task2)],
            workers=2,
            project_root=tmp_path,
        )
        dispatcher = SwarmDispatcher(config)

        # No shared scout anymore - each worker runs its own scout
        with patch("zen_mode.swarm.execute_worker_task") as mock_execute:
            # Mock execute_worker_task to return successful WorkerResults
            mock_execute.side_effect = [
                WorkerResult(task_path=str(task1), work_dir=".zen_1", returncode=0),
                WorkerResult(task_path=str(task2), work_dir=".zen_2", returncode=0),
            ]

            # Should not raise - preflight check passes
            summary = dispatcher.execute()
            assert summary.total_tasks == 2


class TestScoutContext:
    """Tests for shared scout context functionality."""

    def test_execute_worker_task_with_scout_context(self, tmp_path):
        """Test that execute_worker_task passes scout context to subprocess."""
        task_path = "task.md"
        work_dir = ".zen_test"
        scout_context = str(tmp_path / "scout.md")

        # Create scout context file
        Path(scout_context).write_text("## Targeted Files\n- src/main.py")

        captured_cmd = []

        with patch("zen_mode.swarm.subprocess.Popen") as mock_popen:
            mock_proc = Mock()
            mock_proc.wait.return_value = None
            mock_proc.returncode = 0
            mock_proc.pid = 12345

            def capture_popen(cmd, **kwargs):
                captured_cmd.extend(cmd)
                return mock_proc

            mock_popen.side_effect = capture_popen

            with patch("zen_mode.swarm._get_modified_files") as mock_files:
                mock_files.return_value = []

                result = execute_worker_task(
                    task_path,
                    work_dir,
                    tmp_path,
                    scout_context=scout_context
                )

                # Verify subprocess was called with --scout-context
                assert "--scout-context" in captured_cmd
                assert scout_context in captured_cmd
                assert result.returncode == 0

    def test_execute_worker_task_without_scout_context(self, tmp_path):
        """Test that execute_worker_task works without scout context (backward compatibility)."""
        task_path = "task.md"
        work_dir = ".zen_test"

        captured_cmd = []

        with patch("zen_mode.swarm.subprocess.Popen") as mock_popen:
            mock_proc = Mock()
            mock_proc.wait.return_value = None
            mock_proc.returncode = 0
            mock_proc.pid = 12345

            def capture_popen(cmd, **kwargs):
                captured_cmd.extend(cmd)
                return mock_proc

            mock_popen.side_effect = capture_popen

            with patch("zen_mode.swarm._get_modified_files") as mock_files:
                mock_files.return_value = []

                result = execute_worker_task(
                    task_path,
                    work_dir,
                    tmp_path,
                    scout_context=None
                )

                # Verify subprocess was called without --scout-context
                assert "--scout-context" not in captured_cmd
                assert result.returncode == 0

    def test_swarm_dispatcher_no_shared_scout(self, tmp_path):
        """Test that SwarmDispatcher passes scout_context=None so each worker runs own scout."""
        # Create task files
        task1 = tmp_path / "task1.md"
        task1.write_text("TARGETS: src/file1.py\n")

        task2 = tmp_path / "task2.md"
        task2.write_text("TARGETS: src/file2.py\n")

        config = SwarmConfig(
            tasks=[str(task1), str(task2)],
            workers=2,
            project_root=tmp_path,
        )
        dispatcher = SwarmDispatcher(config)

        with patch("zen_mode.swarm.execute_worker_task") as mock_execute:
            # Mock execute_worker_task to return successful WorkerResults
            mock_execute.side_effect = [
                WorkerResult(task_path=str(task1), work_dir=".zen_1", returncode=0),
                WorkerResult(task_path=str(task2), work_dir=".zen_2", returncode=0),
            ]

            summary = dispatcher.execute()

            # Verify both workers were called
            assert mock_execute.call_count == 2

            # Verify scout_context=None passed to all workers (each runs own scout)
            for call in mock_execute.call_args_list:
                # scout_context is the 4th positional arg
                assert call[0][3] is None

            # Verify summary
            assert summary.total_tasks == 2
            assert summary.succeeded == 2


class TestKnownIssues:
    """Tests demonstrating known bugs - these should FAIL until fixed."""

    def test_cost_regex_whole_dollar(self):
        """BUG: Cost regex requires decimal, fails on whole dollar amounts."""
        # Current regex: \$(\d+\.\d+) requires decimal point
        output = "[COST] Total: $1"
        cost = _extract_cost_from_output(output)
        # This SHOULD be 1.0, but currently returns 0.0
        assert cost == 1.0, "Regex should handle whole dollar amounts"

    def test_modified_files_relative_path(self, tmp_path):
        """BUG: _get_modified_files returns paths with work_dir prefix."""

        # Create work_dir with a file inside
        work_dir = tmp_path / ".zen_test"
        work_dir.mkdir()
        (work_dir / "src").mkdir()
        (work_dir / "src" / "file.py").touch()

        modified = _get_modified_files(work_dir)
        # Normalize path separators for cross-platform
        modified = [p.replace(os.sep, "/") for p in modified]

        # Should return relative paths like "src/file.py"
        assert modified == ["src/file.py"], f"Got {modified}, expected relative to work_dir"

    def test_executor_exception_handling(self):
        """Worker exceptions should be caught, not crash entire swarm."""
        config = SwarmConfig(
            tasks=["task.md"],
            workers=1,
        )
        dispatcher = SwarmDispatcher(config)

        # No shared scout anymore - just mock execute_worker_task
        with patch("zen_mode.swarm.execute_worker_task") as mock_execute:
            # Simulate worker raising exception
            mock_execute.side_effect = RuntimeError("Worker exploded")

            # Should return a summary with failed task, not crash
            summary = dispatcher.execute()
            assert summary.failed == 1, "Should handle worker exception gracefully"
            assert summary.succeeded == 0
            assert "Worker exploded" in summary.task_results[0].stderr


class TestStatusMonitorSync:
    """Tests for status monitor thread synchronization with main thread."""

    def test_completed_tasks_not_shown_in_status(self):
        """Completed tasks should be removed from status display."""
        from zen_mode.swarm import format_status_block

        # Simulate 3 tasks: 1 completed (not in list), 2 active
        worker_statuses = [
            (2, "step", 3, 5),   # Task 2: step 3/5
            (3, "verify", 0, 0),  # Task 3: verify
            # Task 1 is completed, not in list
        ]

        lines = format_status_block(
            completed=1,
            total=3,
            active=2,
            total_cost=1.50,
            worker_statuses=worker_statuses
        )

        # Should show only active tasks
        output = "\n".join(lines)
        assert "Task 1" not in output, "Completed task should not appear"
        assert "Task 2: 3/5" in output
        assert "Task 3: verify" in output
        assert "1/3 done" in output

    def test_parse_worker_log_phases(self):
        """Test log parsing detects different phases."""
        from zen_mode.swarm import parse_worker_log
        import tempfile
        import os

        # Create temp file in current directory to avoid Windows permission issues
        fd, log_path = tempfile.mkstemp(suffix=".md", dir=".")
        try:
            log_file = Path(log_path)

            # Test plan phase
            log_file.write_text("[PLAN] Done. 5 steps.\n")
            phase, current, total, cost = parse_worker_log(log_file)
            assert phase == "plan"
            assert total == 5

            # Test step phase
            log_file.write_text("[PLAN] Done. 3 steps.\n[STEP 2] Doing something\n")
            phase, current, total, cost = parse_worker_log(log_file)
            assert phase == "step"
            assert current == 2
            assert total == 3

            # Test verify phase
            log_file.write_text("[PLAN] Done. 3 steps.\n[VERIFY] Running tests\n")
            phase, current, total, cost = parse_worker_log(log_file)
            assert phase == "verify"

            # Test error phase
            log_file.write_text("[ERROR] Something went wrong\n")
            phase, current, total, cost = parse_worker_log(log_file)
            assert phase == "error"
        finally:
            os.close(fd)
            os.unlink(log_path)

    def test_shared_state_thread_safety(self):
        """Test that completed_tasks dict is properly synchronized."""
        import threading

        # Simulate the shared state pattern from execute()
        completed_tasks = {}
        completed_lock = threading.Lock()

        def mark_complete(work_dir):
            with completed_lock:
                completed_tasks[work_dir] = True

        def read_completed():
            with completed_lock:
                return set(completed_tasks.keys())

        # Simulate concurrent updates
        threads = []
        for i in range(10):
            t = threading.Thread(target=mark_complete, args=(f"worker_{i}",))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # All should be marked
        completed = read_completed()
        assert len(completed) == 10
        for i in range(10):
            assert f"worker_{i}" in completed


class TestPartitionTasksByConflict:
    """Tests for task partitioning based on overlapping targets."""

    def test_partition_overlapping_targets(self, tmp_path):
        """Tasks with overlapping TARGETS go into same conflict group."""
        # Create test files
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "shared.py").touch()
        (tmp_path / "src" / "file1.py").touch()

        # Create tasks with overlapping targets
        task1 = tmp_path / "task1.md"
        task1.write_text("TARGETS: src/shared.py, src/file1.py\n")

        task2 = tmp_path / "task2.md"
        task2.write_text("TARGETS: src/shared.py\n")  # overlaps with task1

        conflict_groups, parallel_tasks = _partition_tasks_by_conflict(
            [str(task1), str(task2)], tmp_path
        )

        # Both tasks should be in the same conflict group
        assert len(conflict_groups) == 1
        assert len(conflict_groups[0]) == 2
        assert len(parallel_tasks) == 0

    def test_partition_no_overlap(self, tmp_path):
        """Tasks with non-overlapping TARGETS can run in parallel."""
        # Create test files
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "file1.py").touch()
        (tmp_path / "src" / "file2.py").touch()

        task1 = tmp_path / "task1.md"
        task1.write_text("TARGETS: src/file1.py\n")

        task2 = tmp_path / "task2.md"
        task2.write_text("TARGETS: src/file2.py\n")

        conflict_groups, parallel_tasks = _partition_tasks_by_conflict(
            [str(task1), str(task2)], tmp_path
        )

        # Both should be parallel (no conflicts)
        assert len(conflict_groups) == 0
        assert len(parallel_tasks) == 2

    def test_partition_no_targets_uses_sentinel(self, tmp_path):
        """Tasks without TARGETS use sentinel and conflict with each other."""
        task1 = tmp_path / "task1.md"
        task1.write_text("# Task 1\nNo targets header\n")

        task2 = tmp_path / "task2.md"
        task2.write_text("# Task 2\nAlso no targets\n")

        conflict_groups, parallel_tasks = _partition_tasks_by_conflict(
            [str(task1), str(task2)], tmp_path
        )

        # Both should be in same conflict group (sentinel collision)
        assert len(conflict_groups) == 1
        assert len(conflict_groups[0]) == 2
        assert len(parallel_tasks) == 0

    def test_partition_transitive_conflicts(self, tmp_path):
        """Transitive conflicts: A-B overlap, B-C overlap -> A,B,C in same group."""
        # Create test files
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.py").touch()
        (tmp_path / "src" / "ab.py").touch()  # shared by A and B
        (tmp_path / "src" / "bc.py").touch()  # shared by B and C
        (tmp_path / "src" / "c.py").touch()

        task_a = tmp_path / "task_a.md"
        task_a.write_text("TARGETS: src/a.py, src/ab.py\n")

        task_b = tmp_path / "task_b.md"
        task_b.write_text("TARGETS: src/ab.py, src/bc.py\n")

        task_c = tmp_path / "task_c.md"
        task_c.write_text("TARGETS: src/bc.py, src/c.py\n")

        conflict_groups, parallel_tasks = _partition_tasks_by_conflict(
            [str(task_a), str(task_b), str(task_c)], tmp_path
        )

        # All three should be in same group due to transitive conflicts
        assert len(conflict_groups) == 1
        assert len(conflict_groups[0]) == 3
        assert len(parallel_tasks) == 0

    def test_partition_mixed_conflict_and_parallel(self, tmp_path):
        """Mix of conflicting and non-conflicting tasks."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "shared.py").touch()
        (tmp_path / "src" / "isolated.py").touch()

        # task1 and task2 conflict
        task1 = tmp_path / "task1.md"
        task1.write_text("TARGETS: src/shared.py\n")

        task2 = tmp_path / "task2.md"
        task2.write_text("TARGETS: src/shared.py\n")

        # task3 is independent
        task3 = tmp_path / "task3.md"
        task3.write_text("TARGETS: src/isolated.py\n")

        conflict_groups, parallel_tasks = _partition_tasks_by_conflict(
            [str(task1), str(task2), str(task3)], tmp_path
        )

        # task1+task2 in conflict group, task3 parallel
        assert len(conflict_groups) == 1
        assert len(conflict_groups[0]) == 2
        assert len(parallel_tasks) == 1
        assert "task3.md" in parallel_tasks[0]

    def test_partition_empty_targets_matches_treated_as_no_targets(self, tmp_path):
        """TARGETS header with no matching files treated as no-targets."""
        task1 = tmp_path / "task1.md"
        task1.write_text("TARGETS: nonexistent/*.py\n")  # No matches

        task2 = tmp_path / "task2.md"
        task2.write_text("# No targets header\n")  # No TARGETS

        conflict_groups, parallel_tasks = _partition_tasks_by_conflict(
            [str(task1), str(task2)], tmp_path
        )

        # Both should conflict via sentinel
        assert len(conflict_groups) == 1
        assert len(conflict_groups[0]) == 2


class TestSwarmDispatcherSequentialFallback:
    """Tests for sequential fallback when tasks conflict."""

    def test_execute_runs_conflicting_tasks_sequentially(self, tmp_path):
        """Conflicting tasks should run sequentially, not raise error."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "shared.py").touch()

        task1 = tmp_path / "task1.md"
        task1.write_text("TARGETS: src/shared.py\n")

        task2 = tmp_path / "task2.md"
        task2.write_text("TARGETS: src/shared.py\n")

        config = SwarmConfig(
            tasks=[str(task1), str(task2)],
            workers=2,
            project_root=tmp_path,
        )
        dispatcher = SwarmDispatcher(config)

        # Track execution order
        execution_order = []

        def mock_execute(task_path, work_dir, project_root, scout_context=None):
            execution_order.append(task_path)
            return WorkerResult(task_path=task_path, work_dir=work_dir, returncode=0)

        with patch("zen_mode.swarm.execute_worker_task", side_effect=mock_execute):
            # Should NOT raise - should run sequentially instead
            summary = dispatcher.execute()

        assert summary.total_tasks == 2
        assert summary.succeeded == 2
        # Verify tasks ran (order may vary due to dict iteration)
        assert len(execution_order) == 2

    def test_execute_runs_non_conflicting_tasks_parallel(self, tmp_path):
        """Non-conflicting tasks should run in parallel."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "file1.py").touch()
        (tmp_path / "src" / "file2.py").touch()

        task1 = tmp_path / "task1.md"
        task1.write_text("TARGETS: src/file1.py\n")

        task2 = tmp_path / "task2.md"
        task2.write_text("TARGETS: src/file2.py\n")

        config = SwarmConfig(
            tasks=[str(task1), str(task2)],
            workers=2,
            project_root=tmp_path,
        )
        dispatcher = SwarmDispatcher(config)

        with patch("zen_mode.swarm.execute_worker_task") as mock_execute:
            mock_execute.side_effect = [
                WorkerResult(task_path=str(task1), work_dir=".zen_1", returncode=0),
                WorkerResult(task_path=str(task2), work_dir=".zen_2", returncode=0),
            ]

            summary = dispatcher.execute()

        assert summary.total_tasks == 2
        assert summary.succeeded == 2

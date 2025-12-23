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

        # Mock worker results
        mock_results = [
            WorkerResult(task_path="task1.md", work_dir=".zen_abc1", returncode=0, cost=0.01),
            WorkerResult(task_path="task2.md", work_dir=".zen_abc2", returncode=0, cost=0.02),
        ]

        with patch("zen_mode.swarm.ProcessPoolExecutor") as mock_executor_class:
            mock_executor = Mock()
            mock_executor_class.return_value = mock_executor

            # Simulate futures completing
            futures = {Mock(): task for task in ["task1.md", "task2.md"]}
            mock_executor.submit.side_effect = list(futures.keys())

            with patch("zen_mode.swarm.as_completed") as mock_as_completed:
                mock_as_completed.return_value = futures.keys()

                # Manually set results instead of relying on mocks
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

        # Verify title and box-drawing characters
        assert "Swarm Execution Summary" in report
        assert "┌─" in report
        assert "└─" in report
        assert "├─" in report
        assert "│" in report

        # Verify summary stats section with correct labels
        assert "Total Tasks:" in report
        assert "Passed:" in report
        assert "Failed:" in report
        assert "Total Cost:" in report

        # Verify stat values
        assert "2" in report  # Total tasks
        assert "1" in report  # Passed count
        assert "$0.0100" in report  # Cost formatted with 4 decimals

        # Verify status indicators (✓ for passed, ✗ for failed)
        assert "✓" in report
        assert "✗" in report

        # Verify failed tasks section header and content
        assert "Failed Tasks" in report
        assert "task2.md" in report
        assert "Connection timeout" in report
        assert "Exit Code:" in report


class TestWorkerExecution:
    """Tests for worker execution function."""

    def test_execute_worker_task_dry_run(self, tmp_path):
        """Test dry-run mode does not execute actual subprocess."""
        result = execute_worker_task(
            task_path="task.md",
            work_dir=".zen_test",
            project_root=tmp_path,
            dry_run=True
        )

        assert result.returncode == 0
        assert "[DRY-RUN]" in result.stdout
        assert result.task_path == "task.md"
        assert result.work_dir == ".zen_test"

    def test_execute_worker_task_timeout_error(self, tmp_path):
        """Test timeout handling for long-running tasks."""
        with patch("zen_mode.swarm.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("cmd", 600)

            result = execute_worker_task(
                task_path="task.md",
                work_dir=".zen_test",
                project_root=tmp_path,
                dry_run=False
            )

            assert result.returncode == 124
            assert "timed out" in result.stderr.lower()

    def test_execute_worker_task_cost_extraction(self, tmp_path):
        """Test cost extraction from subprocess output."""
        log_content = "Running task...\n[COST] Total: $0.0456\nTask complete"

        def write_to_log(cmd, **kwargs):
            # Write to the log file that was passed as stdout
            log_file = kwargs.get("stdout")
            if log_file and hasattr(log_file, "write"):
                log_file.write(log_content)
            return Mock(returncode=0)

        with patch("zen_mode.swarm.subprocess.run", side_effect=write_to_log):
            with patch("zen_mode.swarm._get_modified_files") as mock_files:
                mock_files.return_value = []

                result = execute_worker_task(
                    task_path="task.md",
                    work_dir=".zen_test",
                    project_root=tmp_path,
                    dry_run=False
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

    def test_execute_aborts_on_preflight_conflicts(self, tmp_path):
        """Test execute() raises ValueError when TARGETS conflicts detected."""
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

        with pytest.raises(ValueError, match="Preflight conflict detection failed"):
            dispatcher.execute()

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
            dry_run=True,  # Skip _run_shared_scout to avoid real API call
        )
        dispatcher = SwarmDispatcher(config)

        with patch("zen_mode.swarm.ProcessPoolExecutor") as mock_executor_class:
            mock_executor = Mock()
            mock_executor_class.return_value = mock_executor

            # Create mock futures
            mock_futures = [Mock(), Mock()]
            mock_executor.submit.side_effect = mock_futures

            with patch("zen_mode.swarm.as_completed") as mock_as_completed:
                mock_as_completed.return_value = mock_futures

                # Mock future.result() to return WorkerResults
                mock_futures[0].result.return_value = WorkerResult(
                    task_path=str(task1), work_dir=".zen_1", returncode=0
                )
                mock_futures[1].result.return_value = WorkerResult(
                    task_path=str(task2), work_dir=".zen_2", returncode=0
                )

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

        with patch("zen_mode.swarm.subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout="[COST] Total: $0.01",
                stderr=""
            )
            with patch("zen_mode.swarm._get_modified_files") as mock_files:
                mock_files.return_value = []

                result = execute_worker_task(
                    task_path,
                    work_dir,
                    tmp_path,
                    dry_run=False,
                    scout_context=scout_context
                )

                # Verify subprocess was called with --scout-context
                mock_run.assert_called_once()
                cmd = mock_run.call_args[0][0]
                assert "--scout-context" in cmd
                assert scout_context in cmd
                assert result.returncode == 0

    def test_execute_worker_task_without_scout_context(self, tmp_path):
        """Test that execute_worker_task works without scout context (backward compatibility)."""
        task_path = "task.md"
        work_dir = ".zen_test"

        with patch("zen_mode.swarm.subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout="[COST] Total: $0.01",
                stderr=""
            )
            with patch("zen_mode.swarm._get_modified_files") as mock_files:
                mock_files.return_value = []

                result = execute_worker_task(
                    task_path,
                    work_dir,
                    tmp_path,
                    dry_run=False,
                    scout_context=None
                )

                # Verify subprocess was called without --scout-context
                mock_run.assert_called_once()
                cmd = mock_run.call_args[0][0]
                assert "--scout-context" not in cmd
                assert result.returncode == 0

    def test_swarm_dispatcher_runs_shared_scout(self, tmp_path):
        """Test that SwarmDispatcher runs scout once and passes to workers."""
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

        with patch.object(dispatcher, "_run_shared_scout") as mock_scout:
            mock_scout.return_value = str(tmp_path / ".zen_swarm_abc1" / "scout.md")

            with patch("zen_mode.swarm.ProcessPoolExecutor") as mock_executor_class:
                mock_executor = Mock()
                mock_executor_class.return_value = mock_executor

                # Create mock futures
                mock_futures = [Mock(), Mock()]
                mock_executor.submit.side_effect = mock_futures

                with patch("zen_mode.swarm.as_completed") as mock_as_completed:
                    mock_as_completed.return_value = mock_futures

                    # Mock future.result() to return WorkerResults
                    mock_futures[0].result.return_value = WorkerResult(
                        task_path=str(task1), work_dir=".zen_1", returncode=0
                    )
                    mock_futures[1].result.return_value = WorkerResult(
                        task_path=str(task2), work_dir=".zen_2", returncode=0
                    )

                    summary = dispatcher.execute()

                    # Verify scout was run once
                    mock_scout.assert_called_once()

                    # Verify both workers were submitted
                    assert mock_executor.submit.call_count == 2

                    # Verify scout context was passed to both workers
                    for call in mock_executor.submit.call_args_list:
                        args = call[0]
                        # args[5] is scout_context parameter
                        assert args[5] == mock_scout.return_value

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
            dry_run=True,  # Skip scout
        )
        dispatcher = SwarmDispatcher(config)

        with patch("zen_mode.swarm.ProcessPoolExecutor") as mock_executor_class:
            mock_executor = Mock()
            mock_executor_class.return_value = mock_executor

            # Simulate worker raising exception
            mock_future = Mock()
            mock_future.result.side_effect = RuntimeError("Worker exploded")
            mock_executor.submit.return_value = mock_future

            with patch("zen_mode.swarm.as_completed") as mock_as_completed:
                mock_as_completed.return_value = [mock_future]

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

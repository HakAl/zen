"""
Tests for swarm system issues that don't require Claude API calls.
These tests mock Claude interactions and focus on:
- Subprocess/timeout handling
- File system edge cases
- Coordination/race conditions
- Cost extraction edge cases
- Worker error recovery
"""
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from zen_mode.swarm import (
    SwarmConfig,
    SwarmDispatcher,
    WorkerResult,
    execute_worker_task,
    detect_file_conflicts,
    parse_targets_header,
    expand_targets,
    detect_preflight_conflicts,
    _extract_cost_from_output,
    _get_modified_files,
    parse_worker_log,
    format_status_block,
)


# ============================================================================
# Cost Extraction Edge Cases
# ============================================================================
class TestCostExtractionEdgeCases:
    """Tests for cost regex patterns and edge cases."""

    def test_cost_with_no_decimal(self):
        """Cost regex should handle whole dollar amounts like '$1'."""
        output = "[COST] Total: $1"
        cost = _extract_cost_from_output(output)
        # Current regex may fail on this - test documents the issue
        assert cost == 1.0, f"Expected 1.0, got {cost}"

    def test_cost_with_single_decimal(self):
        """Cost regex should handle single decimal like '$1.5'."""
        output = "[COST] Total: $1.5"
        cost = _extract_cost_from_output(output)
        assert cost == 1.5, f"Expected 1.5, got {cost}"

    def test_cost_with_many_decimals(self):
        """Cost regex should handle high precision like '$0.0001234'."""
        output = "[COST] Total: $0.0001234"
        cost = _extract_cost_from_output(output)
        assert cost == 0.0001234, f"Expected 0.0001234, got {cost}"

    def test_cost_zero_dollars(self):
        """Cost regex should handle $0."""
        output = "[COST] Total: $0"
        cost = _extract_cost_from_output(output)
        assert cost == 0.0, f"Expected 0.0, got {cost}"

    def test_cost_with_extra_whitespace(self):
        """Cost regex should handle extra whitespace."""
        output = "[COST]   Total:   $1.23"
        cost = _extract_cost_from_output(output)
        assert cost == 1.23, f"Expected 1.23, got {cost}"

    def test_cost_extraction_multiple_costs_takes_first(self):
        """When multiple cost lines exist, extract from [COST] Total line."""
        output = """
[COST] haiku scout: $0.01
[COST] opus plan: $0.50
[COST] Total: $0.51
"""
        cost = _extract_cost_from_output(output)
        assert cost == 0.51, f"Expected 0.51, got {cost}"

    def test_cost_extraction_negative_number(self):
        """Negative costs should not be extracted (invalid)."""
        output = "[COST] Total: $-1.23"
        cost = _extract_cost_from_output(output)
        assert cost == 0.0, "Negative costs should be rejected"


# ============================================================================
# Subprocess Timeout Handling
# ============================================================================
class TestSubprocessTimeout:
    """Tests for subprocess timeout and error handling."""

    def test_timeout_returns_code_124(self, tmp_path):
        """Timeout should set returncode to 124 (standard timeout code)."""
        with patch("zen_mode.swarm.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("zen", 600)

            result = execute_worker_task(
                task_path="task.md",
                work_dir=".zen_test",
                project_root=tmp_path,
                dry_run=False
            )

            assert result.returncode == 124
            assert "timed out" in result.stderr.lower()

    def test_subprocess_oserror_handled(self, tmp_path):
        """OSError from subprocess should be caught and reported."""
        with patch("zen_mode.swarm.subprocess.run") as mock_run:
            mock_run.side_effect = OSError("No such file or directory: 'zen'")

            result = execute_worker_task(
                task_path="task.md",
                work_dir=".zen_test",
                project_root=tmp_path,
                dry_run=False
            )

            assert result.returncode == 1
            assert "No such file" in result.stderr

    def test_subprocess_permission_error_handled(self, tmp_path):
        """Permission denied errors should be caught and reported."""
        with patch("zen_mode.swarm.subprocess.run") as mock_run:
            mock_run.side_effect = PermissionError("Permission denied")

            result = execute_worker_task(
                task_path="task.md",
                work_dir=".zen_test",
                project_root=tmp_path,
                dry_run=False
            )

            assert result.returncode == 1
            assert "Permission denied" in result.stderr

    def test_subprocess_nonzero_exit_preserved(self, tmp_path):
        """Non-zero exit codes from subprocess should be preserved."""
        with patch("zen_mode.swarm.subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=42,
                stdout="Some output",
                stderr="Some error"
            )
            with patch("zen_mode.swarm._get_modified_files", return_value=[]):
                result = execute_worker_task(
                    task_path="task.md",
                    work_dir=".zen_test",
                    project_root=tmp_path,
                    dry_run=False
                )

                assert result.returncode == 42


# ============================================================================
# File System Edge Cases
# ============================================================================
class TestFileSystemEdgeCases:
    """Tests for file system operations and edge cases."""

    def test_modified_files_excludes_log_files(self, tmp_path):
        """Modified files should potentially filter system files like log.md."""
        work_dir = tmp_path / ".zen_test"
        work_dir.mkdir()
        (work_dir / "log.md").write_text("log content")
        (work_dir / "src").mkdir()
        (work_dir / "src" / "real_file.py").write_text("code")

        modified = _get_modified_files(work_dir)

        # Current implementation returns all files - document behavior
        # This could be considered a bug if log.md shows up as "modified"
        assert "src/real_file.py" in [p.replace(os.sep, "/") for p in modified]

    def test_modified_files_handles_nested_dirs(self, tmp_path):
        """Modified files should handle deeply nested directories."""
        work_dir = tmp_path / ".zen_test"
        deep_path = work_dir / "a" / "b" / "c" / "d"
        deep_path.mkdir(parents=True)
        (deep_path / "file.py").write_text("code")

        modified = _get_modified_files(work_dir)
        normalized = [p.replace(os.sep, "/") for p in modified]

        assert "a/b/c/d/file.py" in normalized

    def test_modified_files_empty_dir(self, tmp_path):
        """Empty work directory should return empty list."""
        work_dir = tmp_path / ".zen_test"
        work_dir.mkdir()

        modified = _get_modified_files(work_dir)
        assert modified == []

    def test_modified_files_nonexistent_dir(self, tmp_path):
        """Non-existent work directory should return empty list."""
        work_dir = tmp_path / "does_not_exist"

        modified = _get_modified_files(work_dir)
        assert modified == []

    def test_work_dir_creation_with_parents(self, tmp_path):
        """Work directory should be created with parents."""
        nested_work_dir = ".zen/deeply/nested/worker_abc"

        with patch("zen_mode.swarm.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
            with patch("zen_mode.swarm._get_modified_files", return_value=[]):
                result = execute_worker_task(
                    task_path="task.md",
                    work_dir=nested_work_dir,
                    project_root=tmp_path,
                    dry_run=False
                )

        work_path = tmp_path / nested_work_dir
        assert work_path.exists()


# ============================================================================
# TARGETS Parsing Edge Cases
# ============================================================================
class TestTargetsParsingEdgeCases:
    """Tests for TARGETS header parsing edge cases."""

    def test_targets_with_path_traversal(self, tmp_path):
        """TARGETS should not allow path traversal outside project."""
        task_file = tmp_path / "task.md"
        task_file.write_text("TARGETS: ../../../etc/passwd\n")

        targets = parse_targets_header(task_file)

        # Documents current behavior - targets are parsed as-is
        # Expansion should fail to find ../../../etc/passwd
        assert targets == ["../../../etc/passwd"]

        # Verify expansion doesn't resolve to real file
        expanded = expand_targets(targets, tmp_path)
        assert len(expanded) == 0  # File shouldn't exist relative to tmp_path

    def test_targets_with_absolute_path(self, tmp_path):
        """Absolute paths in TARGETS should be skipped (security)."""
        task_file = tmp_path / "task.md"
        task_file.write_text("TARGETS: /etc/passwd, C:\\Windows\\System32\n")

        targets = parse_targets_header(task_file)
        expanded = expand_targets(targets, tmp_path)

        # Absolute paths are skipped for security - no files outside project
        assert len(expanded) == 0

    def test_targets_empty_after_colon(self, tmp_path):
        """TARGETS with nothing after colon should return empty list."""
        task_file = tmp_path / "task.md"
        task_file.write_text("TARGETS:\n")

        targets = parse_targets_header(task_file)
        assert targets == []

    def test_targets_only_whitespace(self, tmp_path):
        """TARGETS with only whitespace should return empty list."""
        task_file = tmp_path / "task.md"
        task_file.write_text("TARGETS:   ,  ,  \n")

        targets = parse_targets_header(task_file)
        assert targets == []

    def test_targets_file_read_error(self, tmp_path):
        """TARGETS should handle file read errors gracefully."""
        task_file = tmp_path / "nonexistent.md"

        targets = parse_targets_header(task_file)
        assert targets == []

    def test_targets_glob_recursive(self, tmp_path):
        """TARGETS should support recursive glob patterns."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a").mkdir()
        (tmp_path / "src" / "a" / "deep.py").write_text("")
        (tmp_path / "src" / "shallow.py").write_text("")

        targets = ["src/**/*.py"]
        expanded = expand_targets(targets, tmp_path)

        assert len(expanded) >= 2
        paths = [str(p) for p in expanded]
        assert any("deep.py" in p for p in paths)
        assert any("shallow.py" in p for p in paths)


# ============================================================================
# Worker Exception Handling
# ============================================================================
class TestWorkerExceptionHandling:
    """Tests for worker process exception handling."""

    def test_future_exception_creates_failed_result(self):
        """Worker exceptions should create failed WorkerResult, not crash."""
        config = SwarmConfig(
            tasks=["task.md"],
            workers=1,
            dry_run=True,
        )
        dispatcher = SwarmDispatcher(config)

        with patch("zen_mode.swarm.ProcessPoolExecutor") as mock_executor_class:
            mock_executor = Mock()
            mock_executor_class.return_value = mock_executor

            mock_future = Mock()
            mock_future.result.side_effect = RuntimeError("Pickle error: can't serialize")
            mock_executor.submit.return_value = mock_future

            with patch("zen_mode.swarm.as_completed") as mock_as_completed:
                mock_as_completed.return_value = [mock_future]

                summary = dispatcher.execute()

                assert summary.failed == 1
                assert summary.succeeded == 0
                assert "Pickle error" in summary.task_results[0].stderr

    def test_multiple_worker_failures(self):
        """Multiple worker failures should all be reported."""
        config = SwarmConfig(
            tasks=["task1.md", "task2.md", "task3.md"],
            workers=3,
            dry_run=True,
        )
        dispatcher = SwarmDispatcher(config)

        with patch("zen_mode.swarm.ProcessPoolExecutor") as mock_executor_class:
            mock_executor = Mock()
            mock_executor_class.return_value = mock_executor

            mock_futures = []
            for i, task in enumerate(["task1.md", "task2.md", "task3.md"]):
                f = Mock()
                if i == 1:  # task2 succeeds
                    f.result.return_value = WorkerResult(
                        task_path=task, work_dir=f".zen_{i}", returncode=0
                    )
                else:  # task1 and task3 fail
                    f.result.side_effect = Exception(f"Error in task {i+1}")
                mock_futures.append(f)

            mock_executor.submit.side_effect = mock_futures

            # Map futures to tasks
            futures_map = {
                mock_futures[i]: (task, f".zen_{i}")
                for i, task in enumerate(["task1.md", "task2.md", "task3.md"])
            }

            with patch("zen_mode.swarm.as_completed") as mock_as_completed:
                mock_as_completed.return_value = mock_futures

                # We need to patch the futures dict creation
                original_submit = mock_executor.submit

                def patched_submit(fn, task, work_dir, *args):
                    for f, (t, w) in futures_map.items():
                        if t == task:
                            return f
                    return Mock()

                mock_executor.submit = patched_submit

                summary = dispatcher.execute()

                assert summary.total_tasks == 3
                assert summary.failed == 2
                assert summary.succeeded == 1


# ============================================================================
# Status Monitor Edge Cases
# ============================================================================
class TestStatusMonitorEdgeCases:
    """Tests for status monitor thread edge cases."""

    def test_log_file_partial_write(self, tmp_path):
        """Status monitor should handle partially written log files."""
        log_path = tmp_path / "log.md"

        # Write incomplete line (simulating mid-write)
        log_path.write_text("[PLAN] Done. 5 ste")  # Truncated

        phase, current, total, cost = parse_worker_log(log_path)

        # Should not crash, may not parse correctly
        assert phase in ("starting", "plan", "step", "verify", "error", "done")

    def test_log_file_encoding_error(self, tmp_path):
        """Status monitor should handle encoding errors in log files."""
        log_path = tmp_path / "log.md"

        # Write binary content that's not valid UTF-8
        log_path.write_bytes(b"[PLAN] Done. 5 steps.\xff\xfe invalid bytes")

        # Should not crash - invalid bytes replaced with replacement char
        phase, current, total, cost = parse_worker_log(log_path)
        assert phase == "plan"
        assert total == 5

    def test_log_file_deleted_during_read(self, tmp_path):
        """Status monitor should handle log file deletion."""
        log_path = tmp_path / "log.md"
        log_path.write_text("[PLAN] Done. 5 steps.\n")

        # Delete file
        log_path.unlink()

        phase, current, total, cost = parse_worker_log(log_path)
        assert phase == "starting"  # Default when file doesn't exist

    def test_format_status_block_empty_workers(self):
        """Status block should handle zero active workers."""
        lines = format_status_block(
            completed=5,
            total=5,
            active=0,
            total_cost=1.50,
            worker_statuses=[]
        )

        output = "\n".join(lines)
        assert "5/5 done" in output
        assert "Active: 0" in output

    def test_format_status_block_many_workers(self):
        """Status block should handle many concurrent workers."""
        statuses = [(i, "step", i, 10) for i in range(1, 21)]

        lines = format_status_block(
            completed=0,
            total=20,
            active=20,
            total_cost=0.0,
            worker_statuses=statuses
        )

        output = "\n".join(lines)
        assert "0/20 done" in output
        assert "Active: 20" in output


# ============================================================================
# Conflict Detection Edge Cases
# ============================================================================
class TestConflictDetectionEdgeCases:
    """Tests for file conflict detection edge cases."""

    def test_conflict_with_same_file_different_paths(self):
        """Different path representations of same file should conflict."""
        results = [
            WorkerResult(
                task_path="task1.md",
                work_dir=".zen_1",
                returncode=0,
                modified_files=["src/file.py"]
            ),
            WorkerResult(
                task_path="task2.md",
                work_dir=".zen_2",
                returncode=0,
                modified_files=["src/file.py"]  # Same logical file
            ),
        ]

        conflicts = detect_file_conflicts(results)
        assert "src/file.py" in conflicts
        assert len(conflicts["src/file.py"]) == 2

    def test_conflict_detection_with_windows_paths(self):
        """Conflict detection should normalize path separators."""
        results = [
            WorkerResult(
                task_path="task1.md",
                work_dir=".zen_1",
                returncode=0,
                modified_files=["src\\file.py"]  # Windows path
            ),
            WorkerResult(
                task_path="task2.md",
                work_dir=".zen_2",
                returncode=0,
                modified_files=["src/file.py"]  # Unix path
            ),
        ]

        conflicts = detect_file_conflicts(results)

        # Both paths should be normalized to src/file.py and detected as conflict
        assert "src/file.py" in conflicts
        assert len(conflicts["src/file.py"]) == 2

    def test_preflight_conflict_with_overlapping_globs(self, tmp_path):
        """Preflight should detect conflicts from overlapping glob patterns."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "file.py").write_text("")

        task1 = tmp_path / "task1.md"
        task1.write_text("TARGETS: src/*.py\n")

        task2 = tmp_path / "task2.md"
        task2.write_text("TARGETS: src/file.py\n")

        conflicts = detect_preflight_conflicts(
            [str(task1), str(task2)],
            tmp_path
        )

        # Both patterns match src/file.py
        assert len(conflicts) == 1
        conflict_key = list(conflicts.keys())[0]
        assert len(conflicts[conflict_key]) == 2


# ============================================================================
# Dry Run Mode
# ============================================================================
class TestDryRunMode:
    """Tests for dry-run mode behavior."""

    def test_dry_run_no_subprocess_call(self, tmp_path):
        """Dry run should not call subprocess."""
        with patch("zen_mode.swarm.subprocess.run") as mock_run:
            result = execute_worker_task(
                task_path="task.md",
                work_dir=".zen_test",
                project_root=tmp_path,
                dry_run=True
            )

            mock_run.assert_not_called()
            assert "[DRY-RUN]" in result.stdout
            assert result.returncode == 0

    def test_dry_run_swarm_no_scout(self, tmp_path):
        """Dry run swarm should not run scout."""
        task = tmp_path / "task.md"
        task.write_text("Test task")

        config = SwarmConfig(
            tasks=[str(task)],
            workers=1,
            project_root=tmp_path,
            dry_run=True,
        )
        dispatcher = SwarmDispatcher(config)

        with patch.object(dispatcher, "_run_shared_scout") as mock_scout:
            with patch("zen_mode.swarm.ProcessPoolExecutor") as mock_executor_class:
                mock_executor = Mock()
                mock_executor_class.return_value = mock_executor

                mock_future = Mock()
                mock_future.result.return_value = WorkerResult(
                    task_path=str(task), work_dir=".zen_1", returncode=0
                )
                mock_executor.submit.return_value = mock_future

                with patch("zen_mode.swarm.as_completed") as mock_as_completed:
                    mock_as_completed.return_value = [mock_future]

                    summary = dispatcher.execute()

            # Scout should not be called in dry run
            mock_scout.assert_not_called()


# ============================================================================
# Environment Variable Handling
# ============================================================================
class TestEnvironmentVariables:
    """Tests for environment variable handling."""

    def test_work_dir_env_passed_to_subprocess(self, tmp_path):
        """ZEN_WORK_DIR should be passed to subprocess environment."""
        captured_env = {}

        def capture_env(*args, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            return Mock(returncode=0, stdout="", stderr="")

        with patch("zen_mode.swarm.subprocess.run", side_effect=capture_env):
            with patch("zen_mode.swarm._get_modified_files", return_value=[]):
                execute_worker_task(
                    task_path="task.md",
                    work_dir=".zen/worker_abc",
                    project_root=tmp_path,
                    dry_run=False
                )

        assert "ZEN_WORK_DIR" in captured_env
        assert captured_env["ZEN_WORK_DIR"] == ".zen/worker_abc"

    def test_parent_env_inherited(self, tmp_path):
        """Parent environment variables should be inherited."""
        captured_env = {}

        def capture_env(*args, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            return Mock(returncode=0, stdout="", stderr="")

        # Set a test env var
        os.environ["TEST_VAR_FOR_ZEN"] = "test_value"
        try:
            with patch("zen_mode.swarm.subprocess.run", side_effect=capture_env):
                with patch("zen_mode.swarm._get_modified_files", return_value=[]):
                    execute_worker_task(
                        task_path="task.md",
                        work_dir=".zen_test",
                        project_root=tmp_path,
                        dry_run=False
                    )

            assert captured_env.get("TEST_VAR_FOR_ZEN") == "test_value"
        finally:
            del os.environ["TEST_VAR_FOR_ZEN"]


# ============================================================================
# Scout Context Sharing
# ============================================================================
class TestScoutContextSharing:
    """Tests for shared scout context between workers."""

    def test_scout_context_passed_to_all_workers(self, tmp_path):
        """Scout context path should be passed to all worker subprocesses."""
        task1 = tmp_path / "task1.md"
        task1.write_text("TARGETS: src/a.py\n")
        task2 = tmp_path / "task2.md"
        task2.write_text("TARGETS: src/b.py\n")

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.py").touch()
        (tmp_path / "src" / "b.py").touch()

        config = SwarmConfig(
            tasks=[str(task1), str(task2)],
            workers=2,
            project_root=tmp_path,
        )
        dispatcher = SwarmDispatcher(config)

        scout_path = str(tmp_path / "scout.md")

        with patch.object(dispatcher, "_run_shared_scout", return_value=scout_path):
            with patch("zen_mode.swarm.ProcessPoolExecutor") as mock_executor_class:
                mock_executor = Mock()
                mock_executor_class.return_value = mock_executor

                mock_futures = [Mock(), Mock()]
                mock_futures[0].result.return_value = WorkerResult(
                    task_path=str(task1), work_dir=".zen_1", returncode=0
                )
                mock_futures[1].result.return_value = WorkerResult(
                    task_path=str(task2), work_dir=".zen_2", returncode=0
                )
                mock_executor.submit.side_effect = mock_futures

                with patch("zen_mode.swarm.as_completed") as mock_as_completed:
                    mock_as_completed.return_value = mock_futures

                    dispatcher.execute()

                    # Verify both workers got scout context
                    for call in mock_executor.submit.call_args_list:
                        args = call[0]
                        # args[5] is scout_context parameter
                        assert args[5] == scout_path

    def test_scout_failure_continues_without_context(self, tmp_path):
        """If scout fails, workers should still run (without context)."""
        task = tmp_path / "task.md"
        task.write_text("Test task\n")

        config = SwarmConfig(
            tasks=[str(task)],
            workers=1,
            project_root=tmp_path,
        )
        dispatcher = SwarmDispatcher(config)

        with patch.object(dispatcher, "_run_shared_scout", return_value=None):
            with patch("zen_mode.swarm.ProcessPoolExecutor") as mock_executor_class:
                mock_executor = Mock()
                mock_executor_class.return_value = mock_executor

                mock_future = Mock()
                mock_future.result.return_value = WorkerResult(
                    task_path=str(task), work_dir=".zen_1", returncode=0
                )
                mock_executor.submit.return_value = mock_future

                with patch("zen_mode.swarm.as_completed") as mock_as_completed:
                    mock_as_completed.return_value = [mock_future]

                    summary = dispatcher.execute()

                    # Should succeed even without scout
                    assert summary.total_tasks == 1

                    # Verify scout_context was None
                    call_args = mock_executor.submit.call_args[0]
                    assert call_args[5] is None  # scout_context


# ============================================================================
# SwarmSummary Report Generation
# ============================================================================
class TestSwarmSummaryReport:
    """Tests for SwarmSummary report generation."""

    def test_report_handles_long_file_paths(self):
        """Report should truncate very long file paths."""
        from zen_mode.swarm import SwarmSummary

        long_path = "a" * 100 + "/file.py"
        summary = SwarmSummary(
            total_tasks=2,
            succeeded=2,
            failed=0,
            total_cost=0.01,
            task_results=[],
            conflicts={long_path: ["task1.md", "task2.md"]}
        )

        report = summary.pass_fail_report()

        # Should not crash and should truncate
        assert "..." in report
        assert "│" in report  # Box drawing intact

    def test_report_handles_unicode_in_errors(self):
        """Report should handle unicode characters in error messages."""
        from zen_mode.swarm import SwarmSummary

        result = WorkerResult(
            task_path="task.md",
            work_dir=".zen_1",
            returncode=1,
            stderr="Error: 文字化け and émojis 🔥"
        )

        summary = SwarmSummary(
            total_tasks=1,
            succeeded=0,
            failed=1,
            total_cost=0.0,
            task_results=[result],
        )

        # Should not crash
        report = summary.pass_fail_report()
        assert "Failed Tasks" in report

    def test_report_all_tasks_pass(self):
        """Report should show success when all tasks pass."""
        from zen_mode.swarm import SwarmSummary

        summary = SwarmSummary(
            total_tasks=5,
            succeeded=5,
            failed=0,
            total_cost=1.23,
            task_results=[],
        )

        report = summary.pass_fail_report()

        assert "Failed Tasks" not in report
        assert "5" in report
        assert "$1.2300" in report


# ============================================================================
# Allowed Files Handling
# ============================================================================
class TestModifiedFilesFiltering:
    """Tests for _get_modified_files filtering zen internal files."""

    def test_excludes_log_md(self, tmp_path):
        """log.md should not be reported as modified."""
        work_dir = tmp_path / ".zen_test"
        work_dir.mkdir()
        (work_dir / "log.md").write_text("log content")
        (work_dir / "real_file.py").write_text("code")

        modified = _get_modified_files(work_dir)
        normalized = [p.replace(os.sep, "/") for p in modified]

        assert "real_file.py" in normalized
        assert "log.md" not in normalized

    def test_excludes_plan_md(self, tmp_path):
        """plan.md should not be reported as modified."""
        work_dir = tmp_path / ".zen_test"
        work_dir.mkdir()
        (work_dir / "plan.md").write_text("plan content")
        (work_dir / "src").mkdir()
        (work_dir / "src" / "app.py").write_text("code")

        modified = _get_modified_files(work_dir)
        normalized = [p.replace(os.sep, "/") for p in modified]

        assert "src/app.py" in normalized
        assert "plan.md" not in normalized

    def test_excludes_scout_md(self, tmp_path):
        """scout.md should not be reported as modified."""
        work_dir = tmp_path / ".zen_test"
        work_dir.mkdir()
        (work_dir / "scout.md").write_text("scout content")

        modified = _get_modified_files(work_dir)
        assert "scout.md" not in modified

    def test_excludes_backup_directory(self, tmp_path):
        """backup/ directory contents should not be reported as modified."""
        work_dir = tmp_path / ".zen_test"
        work_dir.mkdir()
        (work_dir / "backup").mkdir()
        (work_dir / "backup" / "old_file.py").write_text("backup")
        (work_dir / "new_file.py").write_text("new code")

        modified = _get_modified_files(work_dir)
        normalized = [p.replace(os.sep, "/") for p in modified]

        assert "new_file.py" in normalized
        assert "backup/old_file.py" not in normalized
        assert not any("backup" in p for p in normalized)

    def test_excludes_test_output_txt(self, tmp_path):
        """test_output.txt should not be reported as modified."""
        work_dir = tmp_path / ".zen_test"
        work_dir.mkdir()
        (work_dir / "test_output.txt").write_text("test results")
        (work_dir / "test_output_1.txt").write_text("more results")

        modified = _get_modified_files(work_dir)

        assert "test_output.txt" not in modified
        assert "test_output_1.txt" not in modified

    def test_excludes_final_notes_md(self, tmp_path):
        """final_notes.md should not be reported as modified."""
        work_dir = tmp_path / ".zen_test"
        work_dir.mkdir()
        (work_dir / "final_notes.md").write_text("notes")

        modified = _get_modified_files(work_dir)
        assert "final_notes.md" not in modified


class TestAllowedFilesHandling:
    """Tests for --allowed-files argument construction."""

    def test_allowed_files_from_targets(self, tmp_path):
        """--allowed-files should be constructed from expanded TARGETS."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.py").touch()
        (tmp_path / "src" / "b.py").touch()

        task = tmp_path / "task.md"
        task.write_text("TARGETS: src/*.py\n")

        captured_cmd = []

        def capture_cmd(cmd, **kwargs):
            captured_cmd.extend(cmd)
            return Mock(returncode=0, stdout="", stderr="")

        with patch("zen_mode.swarm.subprocess.run", side_effect=capture_cmd):
            with patch("zen_mode.swarm._get_modified_files", return_value=[]):
                execute_worker_task(
                    task_path=str(task),
                    work_dir=".zen_test",
                    project_root=tmp_path,
                    dry_run=False
                )

        assert "--allowed-files" in captured_cmd
        idx = captured_cmd.index("--allowed-files")
        allowed_files = captured_cmd[idx + 1]

        # Should contain both files
        assert "a.py" in allowed_files
        assert "b.py" in allowed_files

    def test_no_allowed_files_without_targets(self, tmp_path):
        """No --allowed-files if task has no TARGETS header."""
        task = tmp_path / "task.md"
        task.write_text("Just a task without TARGETS\n")

        captured_cmd = []

        def capture_cmd(cmd, **kwargs):
            captured_cmd.extend(cmd)
            return Mock(returncode=0, stdout="", stderr="")

        with patch("zen_mode.swarm.subprocess.run", side_effect=capture_cmd):
            with patch("zen_mode.swarm._get_modified_files", return_value=[]):
                execute_worker_task(
                    task_path=str(task),
                    work_dir=".zen_test",
                    project_root=tmp_path,
                    dry_run=False
                )

        assert "--allowed-files" not in captured_cmd

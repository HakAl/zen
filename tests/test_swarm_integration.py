"""
Integration tests for swarm worker communication and subprocess handling.
These tests verify actual subprocess behavior without mocking.
"""
import os
import subprocess
import sys
import time
import threading
from concurrent.futures import ProcessPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from pathlib import Path
from unittest.mock import patch, Mock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from zen_mode.swarm import (
    SwarmConfig,
    SwarmDispatcher,
    WorkerResult,
    execute_worker_task,
)


# Module-level functions for ProcessPoolExecutor (must be picklable)
def _simple_task(x):
    return x * 2


def _failing_task():
    raise ValueError("Intentional failure")


def _task_with_conditional_fail(x):
    if x == 2:
        raise ValueError("Task 2 failed")
    return x


def _slow_task():
    time.sleep(5)  # Long enough to test timeout, short enough to not hang tests
    return "done"


def _create_worker_result():
    return WorkerResult(
        task_path="task.md",
        work_dir=".zen_test",
        returncode=0,
        cost=0.05,
        stdout="output",
        stderr="",
        modified_files=["src/file.py"]
    )


class TestProcessPoolCommunication:
    """Test that ProcessPoolExecutor actually returns results."""

    def test_simple_worker_returns_result(self):
        """Verify basic ProcessPoolExecutor communication works."""
        with ProcessPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_simple_task, 21)
            result = future.result(timeout=5)
            assert result == 42

    def test_worker_with_exception_propagates(self):
        """Verify exceptions from workers propagate correctly."""
        with ProcessPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_failing_task)
            with pytest.raises(ValueError, match="Intentional failure"):
                future.result(timeout=5)

    def test_as_completed_returns_all_futures(self):
        """Verify as_completed returns all futures even with mixed results."""
        with ProcessPoolExecutor(max_workers=2) as executor:
            futures = {executor.submit(_task_with_conditional_fail, i): i for i in [1, 2, 3]}
            results = []
            errors = []

            for future in as_completed(futures, timeout=10):
                try:
                    results.append(future.result())
                except ValueError as e:
                    errors.append(str(e))

            assert len(results) + len(errors) == 3
            assert 1 in results
            assert 3 in results
            assert len(errors) == 1


class TestSubprocessTimeout:
    """Test subprocess timeout behavior."""

    def test_subprocess_run_timeout_works(self):
        """Verify subprocess.run timeout actually triggers."""
        start = time.time()
        with pytest.raises(subprocess.TimeoutExpired):
            # Sleep for 10 seconds but timeout after 1
            subprocess.run(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                timeout=1,
                capture_output=True,
            )
        elapsed = time.time() - start
        assert elapsed < 3  # Should timeout quickly, not wait 10 seconds

    def test_subprocess_run_with_stdin_devnull(self):
        """Verify stdin=DEVNULL doesn't cause hangs."""
        # This simulates a process that might try to read stdin
        result = subprocess.run(
            [sys.executable, "-c", "import sys; print('stdin is', sys.stdin)"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0

    def test_subprocess_with_large_output(self):
        """Verify large output doesn't cause deadlock with capture_output."""
        # Generate 1MB of output
        code = "import sys; sys.stdout.write('x' * 1000000); sys.stdout.flush()"
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert len(result.stdout) == 1000000


class TestWorkerTaskExecution:
    """Test execute_worker_task behavior."""

    def test_worker_task_with_nonexistent_zen(self, tmp_path):
        """Worker should handle missing zen CLI gracefully."""
        # Temporarily modify PATH to not find zen
        with patch.dict(os.environ, {"PATH": ""}):
            result = execute_worker_task(
                task_path="task.md",
                work_dir=".zen_test",
                project_root=tmp_path,
            )

        # Should fail but not hang
        assert result.returncode != 0


class TestSwarmExecuteFlow:
    """Test the full swarm execute flow."""

    def test_execute_with_mocked_workers_completes(self, tmp_path):
        """Mocked execute should complete without hanging."""
        task1 = tmp_path / "task1.md"
        task1.write_text("Test task 1\n")
        task2 = tmp_path / "task2.md"
        task2.write_text("Test task 2\n")

        config = SwarmConfig(
            tasks=[str(task1), str(task2)],
            workers=2,
            project_root=tmp_path,
        )
        dispatcher = SwarmDispatcher(config)

        # No shared scout - each worker runs its own
        with patch("zen_mode.swarm.execute_worker_task") as mock_execute:
            mock_execute.side_effect = [
                WorkerResult(task_path=str(task1), work_dir=".zen_1", returncode=0),
                WorkerResult(task_path=str(task2), work_dir=".zen_2", returncode=0),
            ]

            start = time.time()
            summary = dispatcher.execute()
            elapsed = time.time() - start

        assert elapsed < 5  # Should complete quickly with mocks
        assert summary.total_tasks == 2
        assert summary.succeeded == 2

    def test_futures_timeout_prevents_hang(self):
        """Verify we can timeout on futures to prevent infinite hang."""
        with ProcessPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_slow_task)

            # This should raise TimeoutError, not hang
            with pytest.raises(FuturesTimeoutError):
                future.result(timeout=1)

            # Cancel the future (though the task may still run)
            future.cancel()


class TestStatusMonitorVisibility:
    """Test that status monitor shows all relevant states."""

    def test_error_phase_is_visible_in_log(self, tmp_path):
        """Verify error phase can be detected from log."""
        from zen_mode.swarm import parse_worker_log

        log_path = tmp_path / "log.md"
        log_path.write_text("""[SCOUT] Starting
[PLAN] Done. 3 steps.
[STEP 1] Doing something
[ERROR] Java tests failed with exit code 1
""")

        phase, current, total, cost = parse_worker_log(log_path)
        assert phase == "error"

    def test_verify_phase_is_visible_in_log(self, tmp_path):
        """Verify verify phase can be detected from log."""
        from zen_mode.swarm import parse_worker_log

        log_path = tmp_path / "log.md"
        log_path.write_text("""[SCOUT] Starting
[PLAN] Done. 2 steps.
[STEP 1] Implementation
[COMPLETE] Step 1
[STEP 2] More work
[COMPLETE] Step 2
[VERIFY] Running gradle test
""")

        phase, current, total, cost = parse_worker_log(log_path)
        assert phase == "verify"
        assert total == 2
        assert current == 2

    def test_format_status_shows_verify_phase(self):
        """Verify phase should be visible in status output."""
        from zen_mode.swarm import format_status_block

        worker_statuses = [
            (1, "verify", 0, 0),  # Task 1 in verify phase
            (2, "step", 2, 3),    # Task 2 in step phase
        ]

        lines = format_status_block(
            completed=0,
            total=2,
            active=2,
            total_cost=0.50,
            worker_statuses=worker_statuses
        )

        output = "\n".join(lines)
        assert "Task 1: verify" in output
        assert "Task 2: 2/3" in output

    def test_format_status_shows_error_phase(self):
        """Error phase should be visible so users know what's wrong."""
        from zen_mode.swarm import format_status_block

        worker_statuses = [
            (1, "error", 0, 0),  # Task 1 errored - should be visible
            (2, "step", 2, 3),
        ]

        lines = format_status_block(
            completed=0,
            total=2,
            active=2,
            total_cost=0.50,
            worker_statuses=worker_statuses
        )

        output = "\n".join(lines)
        # Error phase should be shown so users have visibility
        assert "Task 1: ERROR" in output
        assert "Task 2: 2/3" in output


class TestGradleMavenSpecificIssues:
    """Tests specific to Java build tool issues."""

    def test_subprocess_with_env_inheritance(self, tmp_path):
        """Verify environment is properly inherited to subprocesses."""
        # This is important for Java tools that depend on JAVA_HOME, etc.
        code = "import os; print(os.environ.get('TEST_VAR', 'NOT_SET'))"

        env = {**os.environ, "TEST_VAR": "test_value"}
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env=env,
            timeout=5,
        )

        assert "test_value" in result.stdout

    def test_subprocess_stdin_closed_for_grandchild(self, tmp_path):
        """Verify stdin is closed even for grandchild processes."""
        # Simulate: parent -> child -> grandchild reading stdin
        # The grandchild should get EOF, not hang
        code = '''
import subprocess
import sys
# This grandchild tries to read stdin
result = subprocess.run(
    [sys.executable, "-c", "import sys; data = sys.stdin.read(); print(f'got: {len(data)} bytes')"],
    capture_output=True,
    text=True,
    stdin=subprocess.DEVNULL,
    timeout=5,
)
print(result.stdout)
'''
        result = subprocess.run(
            [sys.executable, "-c", code],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0
        assert "got: 0 bytes" in result.stdout


class TestWorkerResultCollection:
    """Test that results are properly collected from workers."""

    def test_result_contains_stdout_stderr(self, tmp_path):
        """Verify stdout/stderr are captured in WorkerResult.

        Note: The implementation writes both stdout and stderr to a log file,
        then reads it back into result.stdout. result.stderr is always empty
        unless there was a timeout.
        """
        log_content = "Standard output here\nError output here"

        def write_to_log(cmd, **kwargs):
            # Write to the log file that was passed as stdout
            stdout_file = kwargs.get("stdout")
            if stdout_file and hasattr(stdout_file, "write"):
                stdout_file.write(log_content)
            mock_proc = Mock()
            mock_proc.wait.return_value = None
            mock_proc.returncode = 1
            mock_proc.pid = 12345
            return mock_proc

        with patch("zen_mode.swarm.subprocess.Popen", side_effect=write_to_log):
            with patch("zen_mode.swarm._get_modified_files", return_value=[]):
                result = execute_worker_task(
                    task_path="task.md",
                    work_dir=".zen_test",
                    project_root=tmp_path,
                )

        # Both stdout and stderr are combined into log file, read back as stdout
        assert "Standard output here" in result.stdout
        assert "Error output here" in result.stdout
        assert result.stderr == ""  # stderr is always empty (merged into log file)
        assert result.returncode == 1

    def test_result_propagates_through_executor(self):
        """Verify WorkerResult can be pickled and returned through ProcessPoolExecutor."""
        with ProcessPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_create_worker_result)
            result = future.result(timeout=5)

            assert isinstance(result, WorkerResult)
            assert result.task_path == "task.md"
            assert result.cost == 0.05
            assert result.modified_files == ["src/file.py"]

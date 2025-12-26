"""
Diagnostic tests for swarm worker completion detection.

These tests isolate potential hang points to identify why workers
never return/complete in the swarm execution flow.

Run with: pytest tests/test_swarm_completion.py -v -s

Key insight: Single zen tasks work fine, but swarm workers don't complete.
The difference is HOW swarm invokes zen:
- Environment: ZEN_WORK_DIR is set
- stdin: DEVNULL
- stdout/stderr: redirected to file (not terminal)
- Spawned via ProcessPoolExecutor in separate process
"""
import os
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ProcessPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from pathlib import Path
from unittest.mock import patch, Mock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from zen_mode.swarm import execute_worker_task, WorkerResult


# =============================================================================
# SCENARIO 1: Basic subprocess completion with file-based output
# =============================================================================

class TestSubprocessFileOutput:
    """Test that subprocess.run with file-based stdout/stderr completes."""

    def test_simple_subprocess_completes(self, tmp_path):
        """Basic subprocess should complete and return."""
        log_file = tmp_path / "log.txt"

        with open(log_file, "w") as f:
            result = subprocess.run(
                [sys.executable, "-c", "print('hello')"],
                stdout=f,
                stderr=f,
                stdin=subprocess.DEVNULL,
                timeout=5,
            )

        assert result.returncode == 0
        assert "hello" in log_file.read_text()

    def test_subprocess_with_large_output(self, tmp_path):
        """Subprocess with large output shouldn't deadlock with file output."""
        log_file = tmp_path / "log.txt"

        # Generate 1MB of output
        code = "print('x' * 1000000)"

        with open(log_file, "w") as f:
            result = subprocess.run(
                [sys.executable, "-c", code],
                stdout=f,
                stderr=f,
                stdin=subprocess.DEVNULL,
                timeout=10,
            )

        assert result.returncode == 0
        content = log_file.read_text()
        assert len(content) >= 1000000

    def test_subprocess_with_slow_output(self, tmp_path):
        """Subprocess that outputs slowly should still complete."""
        log_file = tmp_path / "log.txt"

        code = """
import time
for i in range(5):
    print(f'line {i}', flush=True)
    time.sleep(0.1)
print('done')
"""

        with open(log_file, "w") as f:
            result = subprocess.run(
                [sys.executable, "-c", code],
                stdout=f,
                stderr=f,
                stdin=subprocess.DEVNULL,
                timeout=10,
            )

        assert result.returncode == 0
        assert "done" in log_file.read_text()


# =============================================================================
# SCENARIO 2: Subprocess spawning grandchildren
# =============================================================================

class TestGrandchildProcesses:
    """Test completion when subprocess spawns its own children."""

    def test_grandchild_doesnt_block_parent(self, tmp_path):
        """Parent should complete even if grandchild is spawned."""
        log_file = tmp_path / "log.txt"

        # Parent spawns a child that completes quickly
        code = """
import subprocess
import sys
result = subprocess.run([sys.executable, '-c', 'print("grandchild")'],
                        capture_output=True, text=True)
print('parent done')
print(result.stdout)
"""

        with open(log_file, "w") as f:
            result = subprocess.run(
                [sys.executable, "-c", code],
                stdout=f,
                stderr=f,
                stdin=subprocess.DEVNULL,
                timeout=10,
            )

        assert result.returncode == 0
        content = log_file.read_text()
        assert "parent done" in content
        assert "grandchild" in content

    def test_grandchild_with_devnull_stdin(self, tmp_path):
        """Grandchild trying to read stdin should get EOF, not block."""
        log_file = tmp_path / "log.txt"

        code = """
import subprocess
import sys
# Grandchild tries to read stdin - should get EOF immediately
result = subprocess.run(
    [sys.executable, '-c', 'import sys; data=sys.stdin.read(); print(f"read {len(data)} bytes")'],
    capture_output=True, text=True, stdin=subprocess.DEVNULL
)
print('parent complete')
print(result.stdout)
"""

        with open(log_file, "w") as f:
            result = subprocess.run(
                [sys.executable, "-c", code],
                stdout=f,
                stderr=f,
                stdin=subprocess.DEVNULL,
                timeout=10,
            )

        assert result.returncode == 0
        content = log_file.read_text()
        assert "parent complete" in content
        assert "read 0 bytes" in content


# =============================================================================
# SCENARIO 3: ProcessPoolExecutor completion detection
# =============================================================================

def _worker_that_returns():
    """Simple worker that returns immediately."""
    return "completed"


def _worker_that_sleeps(seconds):
    """Worker that sleeps then returns."""
    time.sleep(seconds)
    return f"slept {seconds}s"


def _worker_that_raises():
    """Worker that raises an exception."""
    raise ValueError("intentional failure")


class TestProcessPoolCompletion:
    """Test ProcessPoolExecutor correctly reports worker completion."""

    def test_single_worker_completes(self):
        """Single worker should complete and return result."""
        with ProcessPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_worker_that_returns)
            result = future.result(timeout=5)
            assert result == "completed"

    def test_multiple_workers_all_complete(self):
        """All workers should complete via as_completed."""
        with ProcessPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(_worker_that_sleeps, i * 0.1) for i in range(3)]

            results = []
            for future in as_completed(futures, timeout=10):
                results.append(future.result())

            assert len(results) == 3

    def test_as_completed_timeout_works(self):
        """as_completed should raise TimeoutError if workers don't complete."""
        with ProcessPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_worker_that_sleeps, 10)  # Sleep 10s

            with pytest.raises(FuturesTimeoutError):
                for f in as_completed([future], timeout=1):  # Only wait 1s
                    f.result()

    def test_exception_in_worker_propagates(self):
        """Worker exceptions should propagate through future.result()."""
        with ProcessPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_worker_that_raises)

            with pytest.raises(ValueError, match="intentional failure"):
                future.result(timeout=5)


# =============================================================================
# SCENARIO 4: execute_worker_task completion
# =============================================================================

class TestExecuteWorkerTaskCompletion:
    """Test execute_worker_task returns in various scenarios."""

    def test_missing_zen_cli_returns_error(self, tmp_path):
        """Missing zen CLI should fail fast, not hang."""
        # Clear PATH so zen can't be found
        with patch.dict(os.environ, {"PATH": ""}):
            start = time.time()
            result = execute_worker_task(
                task_path="task.md",
                work_dir=".zen_test",
                project_root=tmp_path,
            )
            elapsed = time.time() - start

        # Should fail quickly (< 5s), not hang
        assert elapsed < 5.0
        assert result.returncode != 0

    def test_subprocess_timeout_is_respected(self, tmp_path):
        """Worker should timeout if subprocess takes too long."""
        # Create a mock that simulates a slow subprocess
        def slow_subprocess(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="zen", timeout=1)

        with patch("zen_mode.swarm.subprocess.run", side_effect=slow_subprocess):
            result = execute_worker_task(
                task_path="task.md",
                work_dir=".zen_test",
                project_root=tmp_path,
            )

        assert result.returncode == 124  # Timeout exit code
        assert "timed out" in result.stderr.lower()


# =============================================================================
# SCENARIO 5: Simulated zen execution (mock the actual flow)
# =============================================================================

class TestSimulatedZenExecution:
    """Test with mocked zen subprocess that simulates real behavior."""

    def test_successful_zen_execution(self, tmp_path):
        """Simulated successful zen run should complete."""
        log_content = """[SCOUT] Starting
[PLAN] Done. 2 steps.
[STEP 1] Implementing
[COMPLETE] Step 1
[STEP 2] Testing
[COMPLETE] Step 2
[VERIFY] Running tests
TESTS_PASS
[COST] Total: $0.05
"""

        def mock_subprocess(cmd, **kwargs):
            stdout = kwargs.get("stdout")
            if stdout and hasattr(stdout, "write"):
                stdout.write(log_content)
            return Mock(returncode=0)

        with patch("zen_mode.swarm.subprocess.run", side_effect=mock_subprocess):
            with patch("zen_mode.swarm._get_modified_files", return_value=["src/file.py"]):
                result = execute_worker_task(
                    task_path="task.md",
                    work_dir=".zen_test",
                    project_root=tmp_path,
                )

        assert result.returncode == 0
        assert result.cost == 0.05
        assert "TESTS_PASS" in result.stdout

    def test_zen_execution_with_test_failure(self, tmp_path):
        """Simulated zen run with test failure should still complete."""
        log_content = """[SCOUT] Starting
[PLAN] Done. 1 steps.
[STEP 1] Implementing
[COMPLETE] Step 1
[VERIFY] Running tests
TESTS_FAIL: 3 failures
[ERROR] Tests did not pass
[COST] Total: $0.03
"""

        def mock_subprocess(cmd, **kwargs):
            stdout = kwargs.get("stdout")
            if stdout and hasattr(stdout, "write"):
                stdout.write(log_content)
            return Mock(returncode=1)

        with patch("zen_mode.swarm.subprocess.run", side_effect=mock_subprocess):
            with patch("zen_mode.swarm._get_modified_files", return_value=[]):
                result = execute_worker_task(
                    task_path="task.md",
                    work_dir=".zen_test",
                    project_root=tmp_path,
                )

        assert result.returncode == 1
        assert "TESTS_FAIL" in result.stdout


# =============================================================================
# SCENARIO 6: Full swarm execution with mocked workers
# =============================================================================

class TestSwarmDispatcherCompletion:
    """Test SwarmDispatcher correctly handles worker completion."""

    def test_all_workers_complete(self, tmp_path):
        """All workers should complete and swarm should return summary."""
        from zen_mode.swarm import SwarmConfig, SwarmDispatcher

        task1 = tmp_path / "task1.md"
        task1.write_text("Task 1")
        task2 = tmp_path / "task2.md"
        task2.write_text("Task 2")

        config = SwarmConfig(
            tasks=[str(task1), str(task2)],
            workers=2,
            project_root=tmp_path,
        )
        dispatcher = SwarmDispatcher(config)

        with patch("zen_mode.swarm.run_claude") as mock_run_claude:
            mock_run_claude.return_value = "## Targeted Files\n- `src/file.py`: test"
            with patch("zen_mode.swarm.ProcessPoolExecutor") as mock_executor_class:
                mock_executor = Mock()
                mock_executor_class.return_value = mock_executor

                # Create mock futures that return successful WorkerResults
                mock_futures = [Mock(), Mock()]
                mock_executor.submit.side_effect = mock_futures
                mock_futures[0].result.return_value = WorkerResult(
                    task_path=str(task1), work_dir=".zen_1", returncode=0
                )
                mock_futures[1].result.return_value = WorkerResult(
                    task_path=str(task2), work_dir=".zen_2", returncode=0
                )

                with patch("zen_mode.swarm.as_completed") as mock_as_completed:
                    mock_as_completed.return_value = mock_futures

                    start = time.time()
                    summary = dispatcher.execute()
                    elapsed = time.time() - start

        assert elapsed < 5.0  # Should complete quickly with mocked execution
        assert summary.total_tasks == 2
        assert summary.succeeded == 2
        assert summary.failed == 0

    def test_worker_exception_doesnt_hang_swarm(self, tmp_path):
        """Worker exception should be caught, not hang the swarm."""
        from zen_mode.swarm import SwarmConfig, SwarmDispatcher

        task1 = tmp_path / "task1.md"
        task1.write_text("Task 1")

        config = SwarmConfig(
            tasks=[str(task1)],
            workers=1,
            project_root=tmp_path,
        )
        dispatcher = SwarmDispatcher(config)

        # Mock run_claude for shared scout and ProcessPoolExecutor to raise exception
        with patch("zen_mode.swarm.run_claude") as mock_run_claude:
            mock_run_claude.return_value = "## Targeted Files\n- `src/file.py`: test"
            with patch("zen_mode.swarm.ProcessPoolExecutor") as mock_executor_class:
                mock_executor = Mock()
                mock_executor_class.return_value = mock_executor

                mock_future = Mock()
                mock_future.result.side_effect = RuntimeError("Worker crashed")
                mock_executor.submit.return_value = mock_future

                with patch("zen_mode.swarm.as_completed") as mock_as_completed:
                    mock_as_completed.return_value = [mock_future]

                    start = time.time()
                    summary = dispatcher.execute()
                    elapsed = time.time() - start

        assert elapsed < 5.0
        assert summary.failed == 1
        assert "Worker crashed" in summary.task_results[0].stderr


# =============================================================================
# SCENARIO 7: Real subprocess with simulated zen behavior
# =============================================================================

class TestRealSubprocessCompletion:
    """Test with real subprocess that simulates zen-like behavior."""

    def test_subprocess_that_writes_and_exits(self, tmp_path):
        """Real subprocess writing output should complete."""
        log_file = tmp_path / "log.md"
        work_dir = tmp_path / ".zen_test"
        work_dir.mkdir()

        # Script that simulates zen output
        script = """
import time
print('[SCOUT] Starting')
print('[PLAN] Done. 1 steps.')
print('[STEP 1] Working')
time.sleep(0.1)
print('[COMPLETE] Step 1')
print('[VERIFY] Tests')
print('TESTS_PASS')
print('[COST] Total: $0.01')
"""

        with open(log_file, "w") as f:
            start = time.time()
            result = subprocess.run(
                [sys.executable, "-c", script],
                stdout=f,
                stderr=f,
                stdin=subprocess.DEVNULL,
                timeout=10,
                cwd=tmp_path,
            )
            elapsed = time.time() - start

        assert elapsed < 5.0
        assert result.returncode == 0

        content = log_file.read_text()
        assert "TESTS_PASS" in content
        assert "[COST]" in content

    def test_subprocess_that_runs_pytest(self, tmp_path):
        """Subprocess running pytest should complete."""
        log_file = tmp_path / "log.md"

        # Create a simple test file
        test_file = tmp_path / "test_simple.py"
        test_file.write_text("def test_pass(): assert True")

        with open(log_file, "w") as f:
            start = time.time()
            result = subprocess.run(
                [sys.executable, "-m", "pytest", str(test_file), "-v"],
                stdout=f,
                stderr=f,
                stdin=subprocess.DEVNULL,
                timeout=30,
                cwd=tmp_path,
            )
            elapsed = time.time() - start

        assert elapsed < 30.0
        assert result.returncode == 0
        assert "passed" in log_file.read_text().lower()


# =============================================================================
# SCENARIO 8: Timing and monitoring
# =============================================================================

class TestCompletionTiming:
    """Test timing of completion detection."""

    def test_completion_detected_immediately(self, tmp_path):
        """Completion should be detected without delay after subprocess exits."""
        log_file = tmp_path / "log.md"

        with open(log_file, "w") as f:
            pre_run = time.time()
            result = subprocess.run(
                [sys.executable, "-c", "print('instant')"],
                stdout=f,
                stderr=f,
                stdin=subprocess.DEVNULL,
                timeout=5,
            )
            post_run = time.time()

        # Should return almost instantly
        assert post_run - pre_run < 1.0
        assert result.returncode == 0

    def test_future_result_available_immediately(self):
        """future.result() should return as soon as worker completes."""
        with ProcessPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_worker_that_returns)

            # Poll until done
            start = time.time()
            while not future.done():
                time.sleep(0.01)
                if time.time() - start > 5:
                    pytest.fail("Future never became done")

            # result() should return immediately once done
            result_start = time.time()
            result = future.result(timeout=1)
            result_elapsed = time.time() - result_start

            assert result_elapsed < 0.1
            assert result == "completed"




# =============================================================================
# SCENARIO 10: Isolate ProcessPoolExecutor layer
# =============================================================================

def _run_subprocess_like_swarm(task_path: str, work_dir: str, project_root: str) -> dict:
    """
    Run subprocess exactly like execute_worker_task does.
    Returns dict instead of WorkerResult to avoid import issues in worker process.
    """
    import subprocess
    import os
    from pathlib import Path

    project_root = Path(project_root)
    work_path = project_root / work_dir
    work_path.mkdir(parents=True, exist_ok=True)
    log_file = work_path / "log.md"

    env = {**os.environ, "ZEN_WORK_DIR": work_dir}

    try:
        with open(log_file, "a", encoding="utf-8") as log_f:
            proc = subprocess.run(
                ["zen", "--help"],  # Simple command that should complete
                cwd=project_root,
                stdin=subprocess.DEVNULL,
                stdout=log_f,
                stderr=log_f,
                timeout=30,
                env=env,
            )
        return {
            "returncode": proc.returncode,
            "stdout": log_file.read_text() if log_file.exists() else "",
            "completed": True,
        }
    except subprocess.TimeoutExpired:
        return {"returncode": 124, "stdout": "", "completed": False, "error": "timeout"}
    except Exception as e:
        return {"returncode": 1, "stdout": "", "completed": False, "error": str(e)}



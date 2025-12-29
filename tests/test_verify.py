"""Tests for zen_mode.verify module."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from zen_mode.verify import (
    VerifyState,
    VerifyTimeout,
    FixResult,
    truncate_preserve_tail,
    extract_filenames,
    verify_test_output,
    detect_no_tests,
    extract_failure_count,
    phase_verify,
    phase_fix_tests,
    verify_and_fix,
    detect_project_runtime,
    TEST_COMMANDS,
)
from zen_mode.context import Context


def make_test_context(tmp_path: Path) -> Context:
    """Create a test context with temporary directories."""
    work_dir = tmp_path / ".zen"
    work_dir.mkdir(parents=True, exist_ok=True)
    return Context(
        work_dir=work_dir,
        task_file=str(tmp_path / "task.md"),
        project_root=tmp_path,
        flags=set(),
    )


class TestVerifyStateEnumValues:
    """Test VerifyState enum values."""

    def test_pass_state_exists(self):
        assert VerifyState.PASS is not None

    def test_fail_state_exists(self):
        assert VerifyState.FAIL is not None

    def test_none_state_exists(self):
        assert VerifyState.NONE is not None

    def test_error_state_exists(self):
        assert VerifyState.ERROR is not None

    def test_states_are_distinct(self):
        states = [VerifyState.PASS, VerifyState.FAIL, VerifyState.NONE, VerifyState.ERROR]
        assert len(set(states)) == 4


class TestFixResultEnum:
    """Test FixResult enum values."""

    def test_applied_exists(self):
        assert FixResult.APPLIED is not None

    def test_blocked_exists(self):
        assert FixResult.BLOCKED is not None

    def test_results_are_distinct(self):
        assert FixResult.APPLIED != FixResult.BLOCKED


class TestVerifyTimeoutException:
    """Test VerifyTimeout exception."""

    def test_verify_timeout_is_exception(self):
        assert issubclass(VerifyTimeout, Exception)

    def test_verify_timeout_can_be_raised(self):
        with pytest.raises(VerifyTimeout):
            raise VerifyTimeout("Claude timed out")

    def test_verify_timeout_message(self):
        exc = VerifyTimeout("test message")
        assert str(exc) == "test message"

    @patch('zen_mode.verify.run_claude')
    def test_phase_verify_raises_on_no_output(self, mock_run_claude, tmp_path):
        """phase_verify raises VerifyTimeout when Claude returns no output."""
        ctx = make_test_context(tmp_path)
        mock_run_claude.return_value = None  # Claude returns nothing

        with pytest.raises(VerifyTimeout, match="Claude did not respond"):
            phase_verify(ctx)


class TestTruncatePreserveTail:
    """Test truncate_preserve_tail helper function."""

    def test_short_text_unchanged(self):
        text = "short text"
        result = truncate_preserve_tail(text, max_chars=100)
        assert result == text

    def test_exact_length_unchanged(self):
        text = "a" * 100
        result = truncate_preserve_tail(text, max_chars=100)
        assert result == text

    def test_long_text_truncated(self):
        text = "a" * 200
        result = truncate_preserve_tail(text, max_chars=100)
        # Allow slight overage due to marker text
        assert len(result) <= 110
        assert "truncated" in result

    def test_preserves_tail(self):
        text = "HEAD" + ("x" * 100) + "TAIL"
        result = truncate_preserve_tail(text, max_chars=50)
        # Tail should be preserved (70% of 50 = 35 chars)
        assert "TAIL" in result

    def test_preserves_head(self):
        text = "HEAD" + ("x" * 100) + "TAIL"
        result = truncate_preserve_tail(text, max_chars=50)
        # Head should be preserved (30% of 50 = 15 chars)
        assert "HEAD" in result


class TestExtractFilenames:
    """Test extract_filenames helper function."""

    def test_extracts_python_traceback_files(self):
        output = '''
Traceback (most recent call last):
  File "/path/to/test_app.py", line 10, in test_something
    assert result == expected
  File "/path/to/app.py", line 25, in calculate
    return x / y
AssertionError
'''
        filenames = extract_filenames(output)
        assert "/path/to/test_app.py" in filenames
        assert "/path/to/app.py" in filenames

    def test_returns_unique_files(self):
        output = '''
  File "/path/to/app.py", line 10, in func1
  File "/path/to/app.py", line 20, in func2
'''
        filenames = extract_filenames(output)
        assert len(filenames) == 1
        assert filenames[0] == "/path/to/app.py"

    def test_empty_output_returns_empty_list(self):
        assert extract_filenames("") == []

    def test_no_matches_returns_empty_list(self):
        assert extract_filenames("no file references here") == []


class TestVerifyTestOutput:
    """Test verify_test_output function."""

    def test_pytest_passed(self):
        output = "===== 5 passed in 0.23s ====="
        assert verify_test_output(output) is True

    def test_pytest_failed(self):
        output = "===== 1 failed, 4 passed in 0.50s ====="
        assert verify_test_output(output) is True

    def test_jest_passed(self):
        output = "Tests: 10 passed, 10 total"
        assert verify_test_output(output) is True

    def test_cargo_passed(self):
        output = "test result: ok. 5 passed; 0 failed"
        assert verify_test_output(output) is True

    def test_go_passed(self):
        output = "ok  mypackage  0.005s"
        assert verify_test_output(output) is True

    def test_generic_passed(self):
        output = "All 10 tests passed"
        assert verify_test_output(output) is True

    def test_no_test_output(self):
        output = "Compiling source files..."
        assert verify_test_output(output) is False

    def test_empty_output(self):
        assert verify_test_output("") is False


class TestDetectNoTests:
    """Test detect_no_tests function."""

    def test_pytest_no_tests(self):
        output = "collected 0 items"
        assert detect_no_tests(output) is True

    def test_pytest_no_tests_ran(self):
        output = "no tests ran"
        assert detect_no_tests(output) is True

    def test_jest_no_tests(self):
        output = "No tests found"
        assert detect_no_tests(output) is True

    def test_cargo_no_tests(self):
        output = "running 0 tests"
        assert detect_no_tests(output) is True

    def test_go_no_tests(self):
        output = "?   mypackage  [no test files]"
        assert detect_no_tests(output) is True

    def test_normal_output_not_detected(self):
        output = "5 passed in 0.23s"
        assert detect_no_tests(output) is False

    def test_empty_output(self):
        assert detect_no_tests("") is False


class TestExtractFailureCount:
    """Test extract_failure_count function."""

    def test_pytest_failures(self):
        output = "===== 2 failed, 8 passed in 1.23s ====="
        assert extract_failure_count(output) == 2

    def test_jest_failures(self):
        output = "Tests: 3 failed, 7 passed, 10 total"
        assert extract_failure_count(output) == 3

    def test_no_failures(self):
        output = "===== 10 passed in 0.50s ====="
        assert extract_failure_count(output) is None

    def test_cargo_failures(self):
        output = "test result: FAILED. 1 passed; 2 failed"
        assert extract_failure_count(output) == 2

    def test_empty_output(self):
        assert extract_failure_count("") is None

    def test_none_output(self):
        assert extract_failure_count(None) is None

    def test_unicode_normalization(self):
        # Test with smart quotes and em-dashes
        output = "2 tests failed - see details"
        assert extract_failure_count(output) == 2


class TestPhaseVerifyMocked:
    """Test phase_verify with mocked Claude calls."""

    @patch('zen_mode.verify.run_claude')
    def test_returns_pass_state(self, mock_run_claude, tmp_path):
        ctx = make_test_context(tmp_path)

        # Create test output file
        test_file = ctx.test_output_file
        test_file.write_text("===== 5 passed in 0.23s =====")

        mock_run_claude.return_value = "Tests completed. TESTS_PASS"

        state, output = phase_verify(ctx)
        assert state == VerifyState.PASS


class TestPhaseFixTestsMocked:
    """Test phase_fix_tests with mocked Claude calls."""

    @patch('zen_mode.verify.run_claude')
    def test_returns_applied_on_success(self, mock_run_claude, tmp_path):
        ctx = make_test_context(tmp_path)
        mock_run_claude.return_value = "Fixed the issue. FIXES_APPLIED"

        result = phase_fix_tests(ctx, "test failure output", attempt=1)
        assert result == FixResult.APPLIED

    @patch('zen_mode.verify.run_claude')
    def test_returns_blocked_on_failure(self, mock_run_claude, tmp_path):
        ctx = make_test_context(tmp_path)
        mock_run_claude.return_value = "Cannot fix. FIXES_BLOCKED: Missing dependency"

        result = phase_fix_tests(ctx, "test failure output", attempt=1)
        assert result == FixResult.BLOCKED

    @patch('zen_mode.verify.run_claude')
    def test_returns_blocked_on_no_output(self, mock_run_claude, tmp_path):
        ctx = make_test_context(tmp_path)
        mock_run_claude.return_value = None

        result = phase_fix_tests(ctx, "test failure output", attempt=1)
        assert result == FixResult.BLOCKED


class TestVerifyAndFixMocked:
    """Test verify_and_fix orchestrator with mocked phases."""

    @patch('zen_mode.verify.phase_fix_tests')
    @patch('zen_mode.verify.phase_verify')
    def test_returns_true_on_pass(self, mock_verify, mock_fix, tmp_path):
        ctx = make_test_context(tmp_path)
        mock_verify.return_value = (VerifyState.PASS, "test output")

        result = verify_and_fix(ctx)
        assert result is True
        mock_fix.assert_not_called()

    @patch('zen_mode.verify.phase_fix_tests')
    @patch('zen_mode.verify.phase_verify')
    def test_returns_true_on_no_tests(self, mock_verify, mock_fix, tmp_path):
        ctx = make_test_context(tmp_path)
        mock_verify.return_value = (VerifyState.NONE, "")

        result = verify_and_fix(ctx)
        assert result is True
        mock_fix.assert_not_called()

    @patch('zen_mode.verify.phase_fix_tests')
    @patch('zen_mode.verify.phase_verify')
    def test_returns_false_on_error(self, mock_verify, mock_fix, tmp_path):
        ctx = make_test_context(tmp_path)
        mock_verify.return_value = (VerifyState.ERROR, "")

        result = verify_and_fix(ctx)
        assert result is False
        mock_fix.assert_not_called()

    @patch('zen_mode.verify.phase_fix_tests')
    @patch('zen_mode.verify.phase_verify')
    def test_calls_fix_on_failure(self, mock_verify, mock_fix, tmp_path):
        ctx = make_test_context(tmp_path)

        # First call fails, second call passes
        mock_verify.side_effect = [
            (VerifyState.FAIL, "failure output"),
            (VerifyState.PASS, "pass output"),
        ]
        mock_fix.return_value = FixResult.APPLIED

        result = verify_and_fix(ctx)
        assert result is True
        mock_fix.assert_called_once()

    @patch('zen_mode.verify.phase_fix_tests')
    @patch('zen_mode.verify.phase_verify')
    def test_stops_on_fix_blocked(self, mock_verify, mock_fix, tmp_path):
        ctx = make_test_context(tmp_path)
        mock_verify.return_value = (VerifyState.FAIL, "failure output")
        mock_fix.return_value = FixResult.BLOCKED

        result = verify_and_fix(ctx)
        assert result is False

    @patch('zen_mode.verify.phase_fix_tests')
    @patch('zen_mode.verify.phase_verify')
    @patch('zen_mode.verify.MAX_FIX_ATTEMPTS', 2)
    def test_respects_max_attempts(self, mock_verify, mock_fix, tmp_path):
        ctx = make_test_context(tmp_path)

        # Always fail
        mock_verify.return_value = (VerifyState.FAIL, "failure output")
        mock_fix.return_value = FixResult.APPLIED

        result = verify_and_fix(ctx)
        assert result is False
        # Should call fix MAX_FIX_ATTEMPTS times (2)
        assert mock_fix.call_count == 2


class TestDetectProjectRuntime:
    """Test detect_project_runtime function."""

    def test_detects_go_project(self, tmp_path):
        (tmp_path / "go.mod").write_text("module example")
        runtime, available = detect_project_runtime(tmp_path)
        assert runtime == "go"

    def test_detects_node_project(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        runtime, available = detect_project_runtime(tmp_path)
        assert runtime == "node"

    def test_detects_python_project_default(self, tmp_path):
        runtime, available = detect_project_runtime(tmp_path)
        assert runtime is None
        assert available is True

    def test_detects_cargo_project(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text("[package]")
        runtime, available = detect_project_runtime(tmp_path)
        assert runtime == "cargo"


class TestTestCommandHints:
    """Test TEST_COMMANDS mapping."""

    def test_go_runtime_gets_go_test(self):
        assert TEST_COMMANDS["go"] == "go test ./..."

    def test_node_runtime_gets_npm_test(self):
        assert TEST_COMMANDS["node"] == "npm test"

    def test_all_detected_runtimes_have_commands(self):
        expected = ["go", "node", "cargo", "gradle", "mvn", "dotnet",
                    "ruby", "php", "elixir", "swift", "sbt", "dart", "zig", "cmake", "cabal"]
        for runtime in expected:
            assert runtime in TEST_COMMANDS, f"Missing command for {runtime}"

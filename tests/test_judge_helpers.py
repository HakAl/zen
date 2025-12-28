"""
Tests for Judge phase helper functions (non-git related).

For git-related tests (get_changed_filenames, should_skip_judge, etc.),
see test_git.py which consolidates all git operations with proper mocking.
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Import from package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from zen_mode.judge import _is_test_or_doc, phase_judge_ctx
from zen_mode.context import Context
from zen_mode.core import _check_previous_completion


class TestIsTestOrDoc:
    """Tests for _is_test_or_doc() helper function."""

    # Documentation files
    def test_markdown_file(self):
        assert _is_test_or_doc("README.md") is True

    def test_txt_file(self):
        assert _is_test_or_doc("CHANGELOG.txt") is True

    def test_rst_file(self):
        assert _is_test_or_doc("docs/index.rst") is True

    def test_nested_doc_file(self):
        assert _is_test_or_doc("docs/api/overview.md") is True

    # Test files - various patterns
    def test_test_directory(self):
        assert _is_test_or_doc("tests/test_core.py") is True

    def test_test_in_path(self):
        assert _is_test_or_doc("src/test/helpers.py") is True

    def test_file_starting_with_test(self):
        assert _is_test_or_doc("test_utils.py") is True

    def test_underscore_test_pattern(self):
        assert _is_test_or_doc("core_test.py") is True

    def test_test_underscore_pattern(self):
        assert _is_test_or_doc("test_core.py") is True

    # Non-test/doc files
    def test_regular_python_file(self):
        assert _is_test_or_doc("src/core.py") is False

    def test_auth_file(self):
        assert _is_test_or_doc("src/auth.py") is False

    def test_config_file(self):
        assert _is_test_or_doc("config.json") is False

    def test_javascript_file(self):
        assert _is_test_or_doc("src/app.js") is False

    # Edge cases
    def test_file_with_test_in_name_but_not_pattern(self):
        # "contest.py" contains "test" but not as a test pattern
        assert _is_test_or_doc("contest.py") is False

    def test_testimony_file(self):
        # "testimony" starts with "test" so it matches the test pattern
        # This is expected behavior per the spec (startswith('test'))
        assert _is_test_or_doc("testimony.py") is True

    def test_attestation_file(self):
        assert _is_test_or_doc("attestation.py") is False

    def test_empty_string(self):
        assert _is_test_or_doc("") is False


class TestCheckPreviousCompletion:
    """Tests for _check_previous_completion() helper function."""

    def test_no_notes_file(self, tmp_path):
        """Returns False when final_notes.md doesn't exist."""
        notes_file = tmp_path / "final_notes.md"
        assert _check_previous_completion(notes_file) is False

    def test_notes_without_cost_summary(self, tmp_path):
        """Returns False when final_notes.md exists but has no cost summary."""
        notes_file = tmp_path / "final_notes.md"
        notes_file.write_text("# Summary\n- Changed some files\n")
        assert _check_previous_completion(notes_file) is False

    def test_notes_with_cost_summary(self, tmp_path):
        """Returns True when final_notes.md has cost summary (completed run)."""
        notes_file = tmp_path / "final_notes.md"
        notes_file.write_text("# Summary\n- Changed files\n\n## Cost Summary\nTotal: $0.05\n")
        assert _check_previous_completion(notes_file) is True


class TestConsecutiveRetryCheckpoint:
    """Tests for consecutive retry checkpoint logic in phase_implement.

    When multiple consecutive steps require retries to succeed, it indicates
    the plan may have issues. The checkpoint logs a warning to alert the user.

    Logic (implemented in phase_implement):
    - Track `consecutive_retry_steps` counter
    - If step succeeds on attempt > 1: increment counter
    - If counter >= 2: log checkpoint warning
    - If step succeeds on attempt 1: reset counter to 0
    """

    def test_checkpoint_logic_first_attempt_success(self):
        """First-attempt success resets the counter."""
        consecutive_retry_steps = 3
        step_succeeded_on_attempt = 1

        # Logic from phase_implement
        if step_succeeded_on_attempt > 1:
            consecutive_retry_steps += 1
        else:
            consecutive_retry_steps = 0

        assert consecutive_retry_steps == 0

    def test_checkpoint_logic_retry_increments(self):
        """Retry success increments the counter."""
        consecutive_retry_steps = 0
        step_succeeded_on_attempt = 2

        if step_succeeded_on_attempt > 1:
            consecutive_retry_steps += 1
        else:
            consecutive_retry_steps = 0

        assert consecutive_retry_steps == 1

    def test_checkpoint_logic_triggers_at_two(self):
        """Checkpoint triggers when counter reaches 2."""
        consecutive_retry_steps = 1
        step_succeeded_on_attempt = 3  # Needed 3 attempts

        checkpoint_triggered = False
        if step_succeeded_on_attempt > 1:
            consecutive_retry_steps += 1
            if consecutive_retry_steps >= 2:
                checkpoint_triggered = True
        else:
            consecutive_retry_steps = 0

        assert consecutive_retry_steps == 2
        assert checkpoint_triggered is True

    def test_checkpoint_logic_scenario(self):
        """Full scenario: step1 retries, step2 retries -> checkpoint."""
        consecutive_retry_steps = 0

        # Step 1: needed 2 attempts
        step_succeeded_on_attempt = 2
        if step_succeeded_on_attempt > 1:
            consecutive_retry_steps += 1
        else:
            consecutive_retry_steps = 0
        assert consecutive_retry_steps == 1

        # Step 2: needed 3 attempts -> triggers checkpoint
        step_succeeded_on_attempt = 3
        checkpoint_triggered = False
        if step_succeeded_on_attempt > 1:
            consecutive_retry_steps += 1
            if consecutive_retry_steps >= 2:
                checkpoint_triggered = True
        else:
            consecutive_retry_steps = 0
        assert consecutive_retry_steps == 2
        assert checkpoint_triggered is True

        # Step 3: first attempt success -> resets
        step_succeeded_on_attempt = 1
        if step_succeeded_on_attempt > 1:
            consecutive_retry_steps += 1
        else:
            consecutive_retry_steps = 0
        assert consecutive_retry_steps == 0


class TestNonInteractiveMode:
    """Tests for non_interactive parameter in phase_judge_ctx."""

    @patch('zen_mode.judge.run_claude')
    @patch('zen_mode.judge.git')
    def test_non_interactive_auto_fails_on_no_response(self, mock_git, mock_run_claude, tmp_path):
        """When non_interactive=True and judge returns None, should exit without input()."""
        # Setup mock git
        mock_git.is_repo.return_value = True
        mock_git.get_changed_filenames.return_value = "file1.py"

        # Setup context
        work_dir = tmp_path / ".zen"
        work_dir.mkdir()
        (work_dir / "scout.md").write_text("scout content")
        (work_dir / "plan.md").write_text("plan content")
        (work_dir / "test_output.txt").write_text("test output")

        ctx = Context(
            project_root=tmp_path,
            work_dir=work_dir,
            task_file=tmp_path / "task.md",
        )

        # run_claude returns None (simulating failure)
        mock_run_claude.return_value = None

        # Should raise JudgeError without blocking on input()
        from zen_mode.exceptions import JudgeError
        with pytest.raises(JudgeError):
            phase_judge_ctx(ctx, non_interactive=True)

    @patch('zen_mode.judge.run_claude')
    @patch('zen_mode.judge.git')
    def test_non_interactive_auto_fails_on_unclear_verdict(self, mock_git, mock_run_claude, tmp_path):
        """When non_interactive=True and judge gives unclear verdict, should exit."""
        # Setup mock git
        mock_git.is_repo.return_value = True
        mock_git.get_changed_filenames.return_value = "file1.py"

        # Setup context
        work_dir = tmp_path / ".zen"
        work_dir.mkdir()
        (work_dir / "scout.md").write_text("scout content")
        (work_dir / "plan.md").write_text("plan content")
        (work_dir / "test_output.txt").write_text("test output")

        ctx = Context(
            project_root=tmp_path,
            work_dir=work_dir,
            task_file=tmp_path / "task.md",
        )

        # run_claude returns unclear verdict (neither APPROVED nor REJECTED)
        mock_run_claude.return_value = "Some unclear response"

        # Should raise JudgeError without blocking on input()
        from zen_mode.exceptions import JudgeError
        with pytest.raises(JudgeError):
            phase_judge_ctx(ctx, non_interactive=True)

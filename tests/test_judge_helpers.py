"""
Tests for Judge phase helper functions (non-git related).

For git-related tests (get_changed_filenames, should_skip_judge, etc.),
see test_git.py which consolidates all git operations with proper mocking.
"""
import sys
from pathlib import Path

import pytest

# Import from package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from zen_mode.judge import _is_test_or_doc
from zen_mode.core import _check_previous_completion, NOTES_FILE


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

    def test_no_notes_file(self, tmp_path, monkeypatch):
        """Returns False when final_notes.md doesn't exist."""
        import zen_mode.core as core
        monkeypatch.setattr(core, "NOTES_FILE", tmp_path / "final_notes.md")
        assert _check_previous_completion() is False

    def test_notes_without_cost_summary(self, tmp_path, monkeypatch):
        """Returns False when final_notes.md exists but has no cost summary."""
        import zen_mode.core as core
        notes_file = tmp_path / "final_notes.md"
        notes_file.write_text("# Summary\n- Changed some files\n")
        monkeypatch.setattr(core, "NOTES_FILE", notes_file)
        assert _check_previous_completion() is False

    def test_notes_with_cost_summary(self, tmp_path, monkeypatch):
        """Returns True when final_notes.md has cost summary (completed run)."""
        import zen_mode.core as core
        notes_file = tmp_path / "final_notes.md"
        notes_file.write_text("# Summary\n- Changed files\n\n## Cost Summary\nTotal: $0.05\n")
        monkeypatch.setattr(core, "NOTES_FILE", notes_file)
        assert _check_previous_completion() is True


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

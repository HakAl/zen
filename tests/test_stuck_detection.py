"""
Tests for "I'm Stuck" Detection behavior (Item 4 from implementation_plan.md).

When the model outputs hesitation phrases like "I cannot", "I am unable", etc.,
the system should:
1. Detect the stuck pattern
2. Inject a coaching prompt
3. Immediately retry with the coaching (same attempt, not a new retry)
4. If still stuck after coaching, proceed to next attempt
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

# Import from package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestStuckDetection:
    """Tests for 'I'm stuck' detection and coaching prompt injection."""

    @pytest.fixture
    def mock_zen_env(self, tmp_path):
        """Set up a mock zen environment."""
        work_dir = tmp_path / ".zen"
        work_dir.mkdir()

        plan_file = work_dir / "plan.md"
        plan_file.write_text("## Step 1: Do something\n")

        log_file = work_dir / "log.md"
        log_file.write_text("")

        return {
            "work_dir": work_dir,
            "plan_file": plan_file,
            "log_file": log_file,
            "tmp_path": tmp_path,
        }

    @patch('zen_mode.core.create_snapshot')
    @patch('zen_mode.core.drop_snapshot')
    @patch('zen_mode.core.restore_snapshot')
    @patch('zen_mode.core.run_linter')
    @patch('zen_mode.core.run_claude')
    @patch('zen_mode.core.log')
    @patch('zen_mode.core.backup_scout_files')
    def test_detects_i_cannot_phrase(
        self, mock_backup, mock_log, mock_claude, mock_linter,
        mock_restore, mock_drop, mock_create, mock_zen_env
    ):
        """Should detect 'I cannot' as a stuck phrase and inject coaching."""
        from zen_mode.core import phase_implement

        with patch('zen_mode.core.PLAN_FILE', mock_zen_env["plan_file"]):
            with patch('zen_mode.core.LOG_FILE', mock_zen_env["log_file"]):
                with patch('zen_mode.core.WORK_DIR', mock_zen_env["work_dir"]):
                    with patch('zen_mode.core.get_completed_steps', return_value=set()):
                        mock_create.return_value = ""

                        call_count = [0]

                        def mock_responses(prompt, model=None, timeout=None):
                            call_count[0] += 1
                            if call_count[0] == 1:
                                return "I cannot complete this task because..."
                            # After coaching, succeed
                            return "STEP_COMPLETE"

                        mock_claude.side_effect = mock_responses
                        mock_linter.return_value = (True, "")

                        phase_implement()

                        # Should have called Claude twice (stuck + coaching retry)
                        assert mock_claude.call_count == 2

                        # Second call should have COACHING in prompt
                        second_prompt = mock_claude.call_args_list[1][0][0]
                        assert "COACHING:" in second_prompt

    @patch('zen_mode.core.create_snapshot')
    @patch('zen_mode.core.drop_snapshot')
    @patch('zen_mode.core.restore_snapshot')
    @patch('zen_mode.core.run_linter')
    @patch('zen_mode.core.run_claude')
    @patch('zen_mode.core.log')
    @patch('zen_mode.core.backup_scout_files')
    def test_detects_i_am_unable_phrase(
        self, mock_backup, mock_log, mock_claude, mock_linter,
        mock_restore, mock_drop, mock_create, mock_zen_env
    ):
        """Should detect 'I am unable' as a stuck phrase."""
        from zen_mode.core import phase_implement

        with patch('zen_mode.core.PLAN_FILE', mock_zen_env["plan_file"]):
            with patch('zen_mode.core.LOG_FILE', mock_zen_env["log_file"]):
                with patch('zen_mode.core.WORK_DIR', mock_zen_env["work_dir"]):
                    with patch('zen_mode.core.get_completed_steps', return_value=set()):
                        mock_create.return_value = ""

                        responses = [
                            "I am unable to modify this file.",
                            "STEP_COMPLETE"
                        ]
                        mock_claude.side_effect = responses
                        mock_linter.return_value = (True, "")

                        phase_implement()

                        assert mock_claude.call_count == 2
                        second_prompt = mock_claude.call_args_list[1][0][0]
                        assert "COACHING:" in second_prompt

    @patch('zen_mode.core.create_snapshot')
    @patch('zen_mode.core.drop_snapshot')
    @patch('zen_mode.core.restore_snapshot')
    @patch('zen_mode.core.run_linter')
    @patch('zen_mode.core.run_claude')
    @patch('zen_mode.core.log')
    @patch('zen_mode.core.backup_scout_files')
    def test_detects_im_unable_phrase(
        self, mock_backup, mock_log, mock_claude, mock_linter,
        mock_restore, mock_drop, mock_create, mock_zen_env
    ):
        """Should detect \"I'm unable\" as a stuck phrase."""
        from zen_mode.core import phase_implement

        with patch('zen_mode.core.PLAN_FILE', mock_zen_env["plan_file"]):
            with patch('zen_mode.core.LOG_FILE', mock_zen_env["log_file"]):
                with patch('zen_mode.core.WORK_DIR', mock_zen_env["work_dir"]):
                    with patch('zen_mode.core.get_completed_steps', return_value=set()):
                        mock_create.return_value = ""

                        responses = [
                            "I'm unable to find the file.",
                            "STEP_COMPLETE"
                        ]
                        mock_claude.side_effect = responses
                        mock_linter.return_value = (True, "")

                        phase_implement()

                        assert mock_claude.call_count == 2

    @patch('zen_mode.core.create_snapshot')
    @patch('zen_mode.core.drop_snapshot')
    @patch('zen_mode.core.restore_snapshot')
    @patch('zen_mode.core.run_linter')
    @patch('zen_mode.core.run_claude')
    @patch('zen_mode.core.log')
    @patch('zen_mode.core.backup_scout_files')
    def test_detects_not_possible_phrase(
        self, mock_backup, mock_log, mock_claude, mock_linter,
        mock_restore, mock_drop, mock_create, mock_zen_env
    ):
        """Should detect 'not possible' as a stuck phrase."""
        from zen_mode.core import phase_implement

        with patch('zen_mode.core.PLAN_FILE', mock_zen_env["plan_file"]):
            with patch('zen_mode.core.LOG_FILE', mock_zen_env["log_file"]):
                with patch('zen_mode.core.WORK_DIR', mock_zen_env["work_dir"]):
                    with patch('zen_mode.core.get_completed_steps', return_value=set()):
                        mock_create.return_value = ""

                        responses = [
                            "It is not possible to change this.",
                            "STEP_COMPLETE"
                        ]
                        mock_claude.side_effect = responses
                        mock_linter.return_value = (True, "")

                        phase_implement()

                        assert mock_claude.call_count == 2

    @patch('zen_mode.core.create_snapshot')
    @patch('zen_mode.core.drop_snapshot')
    @patch('zen_mode.core.restore_snapshot')
    @patch('zen_mode.core.run_linter')
    @patch('zen_mode.core.run_claude')
    @patch('zen_mode.core.log')
    @patch('zen_mode.core.backup_scout_files')
    def test_detects_cannot_complete_phrase(
        self, mock_backup, mock_log, mock_claude, mock_linter,
        mock_restore, mock_drop, mock_create, mock_zen_env
    ):
        """Should detect 'cannot complete' as a stuck phrase."""
        from zen_mode.core import phase_implement

        with patch('zen_mode.core.PLAN_FILE', mock_zen_env["plan_file"]):
            with patch('zen_mode.core.LOG_FILE', mock_zen_env["log_file"]):
                with patch('zen_mode.core.WORK_DIR', mock_zen_env["work_dir"]):
                    with patch('zen_mode.core.get_completed_steps', return_value=set()):
                        mock_create.return_value = ""

                        responses = [
                            "Sorry, I cannot complete this step.",
                            "STEP_COMPLETE"
                        ]
                        mock_claude.side_effect = responses
                        mock_linter.return_value = (True, "")

                        phase_implement()

                        assert mock_claude.call_count == 2

    @patch('zen_mode.core.create_snapshot')
    @patch('zen_mode.core.drop_snapshot')
    @patch('zen_mode.core.restore_snapshot')
    @patch('zen_mode.core.run_linter')
    @patch('zen_mode.core.run_claude')
    @patch('zen_mode.core.log')
    @patch('zen_mode.core.backup_scout_files')
    def test_no_coaching_when_step_complete(
        self, mock_backup, mock_log, mock_claude, mock_linter,
        mock_restore, mock_drop, mock_create, mock_zen_env
    ):
        """If output contains STEP_COMPLETE, don't trigger stuck detection."""
        from zen_mode.core import phase_implement

        with patch('zen_mode.core.PLAN_FILE', mock_zen_env["plan_file"]):
            with patch('zen_mode.core.LOG_FILE', mock_zen_env["log_file"]):
                with patch('zen_mode.core.WORK_DIR', mock_zen_env["work_dir"]):
                    with patch('zen_mode.core.get_completed_steps', return_value=set()):
                        mock_create.return_value = ""

                        # Contains stuck phrase BUT also STEP_COMPLETE
                        mock_claude.return_value = "I cannot believe how easy this was! STEP_COMPLETE"
                        mock_linter.return_value = (True, "")

                        phase_implement()

                        # Should only call once (no coaching needed)
                        assert mock_claude.call_count == 1

    @patch('zen_mode.core.create_snapshot')
    @patch('zen_mode.core.drop_snapshot')
    @patch('zen_mode.core.restore_snapshot')
    @patch('zen_mode.core.run_linter')
    @patch('zen_mode.core.run_claude')
    @patch('zen_mode.core.log')
    @patch('zen_mode.core.backup_scout_files')
    def test_coaching_prompt_contains_encouragement(
        self, mock_backup, mock_log, mock_claude, mock_linter,
        mock_restore, mock_drop, mock_create, mock_zen_env
    ):
        """Coaching prompt should contain helpful guidance."""
        from zen_mode.core import phase_implement

        with patch('zen_mode.core.PLAN_FILE', mock_zen_env["plan_file"]):
            with patch('zen_mode.core.LOG_FILE', mock_zen_env["log_file"]):
                with patch('zen_mode.core.WORK_DIR', mock_zen_env["work_dir"]):
                    with patch('zen_mode.core.get_completed_steps', return_value=set()):
                        mock_create.return_value = ""

                        captured_prompts = []

                        def capture(prompt, model=None, timeout=None):
                            captured_prompts.append(prompt)
                            if len(captured_prompts) == 1:
                                return "I cannot do this."
                            return "STEP_COMPLETE"

                        mock_claude.side_effect = capture
                        mock_linter.return_value = (True, "")

                        phase_implement()

                        coaching_prompt = captured_prompts[1]
                        assert "COACHING:" in coaching_prompt
                        assert "You CAN do this" in coaching_prompt
                        assert "file access" in coaching_prompt.lower()

    @patch('zen_mode.core.create_snapshot')
    @patch('zen_mode.core.drop_snapshot')
    @patch('zen_mode.core.restore_snapshot')
    @patch('zen_mode.core.run_linter')
    @patch('zen_mode.core.run_claude')
    @patch('zen_mode.core.log')
    @patch('zen_mode.core.backup_scout_files')
    def test_logs_stuck_detection(
        self, mock_backup, mock_log, mock_claude, mock_linter,
        mock_restore, mock_drop, mock_create, mock_zen_env
    ):
        """Should log when stuck is detected."""
        from zen_mode.core import phase_implement

        with patch('zen_mode.core.PLAN_FILE', mock_zen_env["plan_file"]):
            with patch('zen_mode.core.LOG_FILE', mock_zen_env["log_file"]):
                with patch('zen_mode.core.WORK_DIR', mock_zen_env["work_dir"]):
                    with patch('zen_mode.core.get_completed_steps', return_value=set()):
                        mock_create.return_value = ""

                        responses = ["I cannot do this.", "STEP_COMPLETE"]
                        mock_claude.side_effect = responses
                        mock_linter.return_value = (True, "")

                        phase_implement()

                        log_messages = [str(c) for c in mock_log.call_args_list]
                        stuck_logged = any("[STUCK]" in msg for msg in log_messages)
                        assert stuck_logged, f"Should log STUCK detection. Got: {log_messages}"

    @patch('zen_mode.core.create_snapshot')
    @patch('zen_mode.core.drop_snapshot')
    @patch('zen_mode.core.restore_snapshot')
    @patch('zen_mode.core.run_linter')
    @patch('zen_mode.core.run_claude')
    @patch('zen_mode.core.log')
    @patch('zen_mode.core.backup_scout_files')
    def test_still_stuck_after_coaching_proceeds_to_next_attempt(
        self, mock_backup, mock_log, mock_claude, mock_linter,
        mock_restore, mock_drop, mock_create, mock_zen_env
    ):
        """If still stuck after coaching, should proceed to next attempt."""
        from zen_mode.core import phase_implement, MAX_RETRIES

        with patch('zen_mode.core.PLAN_FILE', mock_zen_env["plan_file"]):
            with patch('zen_mode.core.LOG_FILE', mock_zen_env["log_file"]):
                with patch('zen_mode.core.WORK_DIR', mock_zen_env["work_dir"]):
                    with patch('zen_mode.core.get_completed_steps', return_value=set()):
                        mock_create.return_value = ""

                        call_count = [0]

                        def mock_responses(prompt, model=None, timeout=None):
                            call_count[0] += 1
                            # First attempt: stuck
                            if call_count[0] == 1:
                                return "I cannot do this."
                            # After coaching: still stuck
                            if call_count[0] == 2:
                                return "I am unable to proceed."
                            # Later attempts: succeed
                            return "STEP_COMPLETE"

                        mock_claude.side_effect = mock_responses
                        mock_linter.return_value = (True, "")

                        phase_implement()

                        # Should have:
                        # - Attempt 1: stuck (1) + coaching retry (2) = 2 calls
                        # - Attempt 2: success (3) = 1 call
                        # Total = 3 calls minimum
                        assert mock_claude.call_count >= 3

                        # Check for "still stuck" log
                        log_messages = [str(c) for c in mock_log.call_args_list]
                        still_stuck_logged = any("Still stuck" in msg for msg in log_messages)
                        assert still_stuck_logged, "Should log 'Still stuck after coaching'"

    @patch('zen_mode.core.create_snapshot')
    @patch('zen_mode.core.drop_snapshot')
    @patch('zen_mode.core.restore_snapshot')
    @patch('zen_mode.core.run_linter')
    @patch('zen_mode.core.run_claude')
    @patch('zen_mode.core.log')
    @patch('zen_mode.core.backup_scout_files')
    def test_coaching_same_attempt_not_new_retry(
        self, mock_backup, mock_log, mock_claude, mock_linter,
        mock_restore, mock_drop, mock_create, mock_zen_env
    ):
        """Coaching should happen in the same attempt, not consume a retry."""
        from zen_mode.core import phase_implement, MAX_RETRIES

        with patch('zen_mode.core.PLAN_FILE', mock_zen_env["plan_file"]):
            with patch('zen_mode.core.LOG_FILE', mock_zen_env["log_file"]):
                with patch('zen_mode.core.WORK_DIR', mock_zen_env["work_dir"]):
                    with patch('zen_mode.core.get_completed_steps', return_value=set()):
                        mock_create.return_value = ""

                        responses = [
                            "I cannot do this.",  # Attempt 1: stuck
                            "STEP_COMPLETE",      # Coaching retry succeeds
                        ]
                        mock_claude.side_effect = responses
                        mock_linter.return_value = (True, "")

                        phase_implement()

                        # Should NOT see "Retry 2/X" log because coaching is same attempt
                        log_messages = [str(c) for c in mock_log.call_args_list]
                        retry_logged = any("Retry 2" in msg for msg in log_messages)
                        assert not retry_logged, "Coaching should not count as a new retry attempt"

    @patch('zen_mode.core.create_snapshot')
    @patch('zen_mode.core.drop_snapshot')
    @patch('zen_mode.core.restore_snapshot')
    @patch('zen_mode.core.run_linter')
    @patch('zen_mode.core.run_claude')
    @patch('zen_mode.core.log')
    @patch('zen_mode.core.backup_scout_files')
    def test_normal_output_no_coaching(
        self, mock_backup, mock_log, mock_claude, mock_linter,
        mock_restore, mock_drop, mock_create, mock_zen_env
    ):
        """Normal output without stuck phrases should not trigger coaching."""
        from zen_mode.core import phase_implement

        with patch('zen_mode.core.PLAN_FILE', mock_zen_env["plan_file"]):
            with patch('zen_mode.core.LOG_FILE', mock_zen_env["log_file"]):
                with patch('zen_mode.core.WORK_DIR', mock_zen_env["work_dir"]):
                    with patch('zen_mode.core.get_completed_steps', return_value=set()):
                        mock_create.return_value = ""
                        mock_claude.return_value = "I have completed the task. STEP_COMPLETE"
                        mock_linter.return_value = (True, "")

                        phase_implement()

                        # Only one call, no coaching needed
                        assert mock_claude.call_count == 1

                        # No STUCK log
                        log_messages = [str(c) for c in mock_log.call_args_list]
                        stuck_logged = any("[STUCK]" in msg for msg in log_messages)
                        assert not stuck_logged

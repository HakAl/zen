"""
Tests for Model Escalation behavior (Item 3 from implementation_plan.md).

When Sonnet (MODEL_HANDS) fails twice, the system should escalate to
Opus (MODEL_BRAIN) on the final retry with a clean prompt that:
1. Resets to the base prompt (no accumulated garbage)
2. Includes an ESCALATION notice
3. Summarizes why previous attempts failed
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

# Import from package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from zen_mode.context import Context
from zen_mode.config import MAX_RETRIES, MODEL_BRAIN, MODEL_HANDS


class TestModelEscalation:
    """Tests for model escalation from Sonnet to Opus on repeated failures."""

    @pytest.fixture
    def mock_ctx(self, tmp_path):
        """Set up a mock context for testing."""
        work_dir = tmp_path / ".zen"
        work_dir.mkdir()

        # Create plan file with a step
        plan_file = work_dir / "plan.md"
        plan_file.write_text("## Step 1: Do something\n")

        # Create log file
        log_file = work_dir / "log.md"
        log_file.write_text("")

        # Create scout file
        scout_file = work_dir / "scout.md"
        scout_file.write_text("")

        ctx = Context(
            work_dir=work_dir,
            task_file="task.md",
            project_root=tmp_path,
        )

        return ctx

    @patch('zen_mode.implement.run_linter_with_timeout')
    @patch('zen_mode.implement.run_claude')
    def test_escalates_to_opus_on_final_retry(
        self, mock_claude, mock_linter, mock_ctx
    ):
        """On the final retry (MAX_RETRIES), model should switch to MODEL_BRAIN."""
        from zen_mode.implement import phase_implement_ctx

        # First attempts fail lint, final attempt succeeds
        call_count = [0]

        def mock_claude_responses(prompt, model=None, **kwargs):
            call_count[0] += 1
            return "STEP_COMPLETE"

        mock_claude.side_effect = mock_claude_responses

        # Lint fails for first N-1 attempts, passes on last
        lint_results = [(False, "Error: something wrong")] * (MAX_RETRIES - 1) + [(True, "")]
        mock_linter.side_effect = lint_results

        phase_implement_ctx(mock_ctx)

        # Verify model escalation happened
        calls = mock_claude.call_args_list

        # Should have MAX_RETRIES calls
        assert len(calls) == MAX_RETRIES

        # First calls should use MODEL_HANDS
        for i in range(MAX_RETRIES - 1):
            assert calls[i][1]['model'] == MODEL_HANDS, f"Call {i} should use MODEL_HANDS"

        # Final call should use MODEL_BRAIN
        assert calls[-1][1]['model'] == MODEL_BRAIN, "Final call should use MODEL_BRAIN"

    @patch('zen_mode.implement.run_linter_with_timeout')
    @patch('zen_mode.implement.run_claude')
    def test_escalation_prompt_includes_escalation_notice(
        self, mock_claude, mock_linter, mock_ctx
    ):
        """The escalation prompt should include 'ESCALATION:' notice."""
        from zen_mode.implement import phase_implement_ctx

        captured_prompts = []

        def capture_prompt(prompt, model=None, **kwargs):
            captured_prompts.append(prompt)
            return "STEP_COMPLETE"

        mock_claude.side_effect = capture_prompt

        # Lint fails until final attempt
        lint_results = [(False, "Some lint error")] * (MAX_RETRIES - 1) + [(True, "")]
        mock_linter.side_effect = lint_results

        phase_implement_ctx(mock_ctx)

        # The final prompt should contain ESCALATION
        assert len(captured_prompts) == MAX_RETRIES
        final_prompt = captured_prompts[-1]
        assert "ESCALATION:" in final_prompt, "Final prompt should contain ESCALATION notice"
        assert "senior specialist" in final_prompt.lower(), "Should mention senior specialist"

    @patch('zen_mode.implement.run_linter_with_timeout')
    @patch('zen_mode.implement.run_claude')
    def test_escalation_includes_last_error_summary(
        self, mock_claude, mock_linter, mock_ctx
    ):
        """The escalation prompt should include a summary of the last error."""
        from zen_mode.implement import phase_implement_ctx

        captured_prompts = []

        def capture_prompt(prompt, model=None, **kwargs):
            captured_prompts.append(prompt)
            return "STEP_COMPLETE"

        mock_claude.side_effect = capture_prompt

        # Specific error that should appear in escalation
        specific_error = "undefined variable 'foobar' on line 42"
        lint_results = [(False, specific_error)] * (MAX_RETRIES - 1) + [(True, "")]
        mock_linter.side_effect = lint_results

        phase_implement_ctx(mock_ctx)

        # The final prompt should contain the error summary
        final_prompt = captured_prompts[-1]
        assert "Last error:" in final_prompt, "Should mention last error"
        # The error should be included (possibly truncated)
        assert "foobar" in final_prompt or "undefined" in final_prompt, \
            "Error content should be included in escalation"

    @patch('zen_mode.implement.run_linter_with_timeout')
    @patch('zen_mode.implement.run_claude')
    def test_escalation_logs_message(
        self, mock_claude, mock_linter, mock_ctx, caplog
    ):
        """Should log 'Escalating to MODEL_BRAIN' when escalating."""
        import logging
        from zen_mode.implement import phase_implement_ctx

        mock_claude.return_value = "STEP_COMPLETE"

        lint_results = [(False, "error")] * (MAX_RETRIES - 1) + [(True, "")]
        mock_linter.side_effect = lint_results

        with caplog.at_level(logging.INFO, logger="zen_mode"):
            phase_implement_ctx(mock_ctx)

        # Check that escalation was logged
        log_output = caplog.text
        assert "Escalating" in log_output and MODEL_BRAIN in log_output, \
            f"Should log escalation message. Got: {log_output}"

    @patch('zen_mode.implement.run_linter_with_timeout')
    @patch('zen_mode.implement.run_claude')
    def test_no_escalation_if_first_attempt_succeeds(
        self, mock_claude, mock_linter, mock_ctx
    ):
        """If first attempt succeeds, should not escalate."""
        from zen_mode.implement import phase_implement_ctx

        mock_claude.return_value = "STEP_COMPLETE"
        mock_linter.return_value = (True, "")  # Success on first try

        phase_implement_ctx(mock_ctx)

        # Should only have one call, using MODEL_HANDS
        assert mock_claude.call_count == 1
        assert mock_claude.call_args[1]['model'] == MODEL_HANDS

    @patch('zen_mode.implement.run_linter_with_timeout')
    @patch('zen_mode.implement.run_claude')
    def test_escalation_uses_clean_base_prompt(
        self, mock_claude, mock_linter, mock_ctx
    ):
        """Escalation should use clean base prompt, not accumulated lint errors."""
        from zen_mode.implement import phase_implement_ctx

        captured_prompts = []

        def capture_prompt(prompt, model=None, **kwargs):
            captured_prompts.append(prompt)
            return "STEP_COMPLETE"

        mock_claude.side_effect = capture_prompt

        # Different lint errors each time to accumulate garbage
        lint_results = [
            (False, "Error A: first problem"),
            (False, "Error B: second problem"),
        ] + [(True, "")]
        mock_linter.side_effect = lint_results

        if MAX_RETRIES >= 3:
            phase_implement_ctx(mock_ctx)

            # Final prompt should NOT contain accumulated errors A and B
            # It should have ESCALATION with just the last error
            final_prompt = captured_prompts[-1]

            # The escalation prompt should start fresh
            assert "ESCALATION:" in final_prompt
            # Should not have multiple LINT FAILED sections
            lint_failed_count = final_prompt.count("LINT FAILED")
            assert lint_failed_count == 0, \
                f"Escalation prompt should not contain accumulated LINT FAILED sections, got {lint_failed_count}"

"""
Tests for CLAUDE.md Constitution inclusion in Judge fix prompt (Task 6).

When the Judge rejects changes and provides feedback for fixes,
the fix prompt should include the CLAUDE.md constitution so the
fixer knows about project-specific rules and conventions.
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Import from package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from zen_mode.utils import Context
from zen_mode.verify import VerifyState


class TestConstitutionInFixPrompt:
    """Tests for CLAUDE.md inclusion in phase_judge_ctx() fix prompt."""

    @pytest.fixture
    def mock_ctx(self, tmp_path):
        """Set up a mock context for testing."""
        # Project root
        project_root = tmp_path

        # Work directory
        work_dir = tmp_path / ".zen"
        work_dir.mkdir()

        # Create required files
        plan_file = work_dir / "plan.md"
        plan_file.write_text("## Step 1: Add a feature\n")

        scout_file = work_dir / "scout.md"
        scout_file.write_text("# Scout Report\nFile tree:\nsrc/main.py\n")

        test_output_file = work_dir / "test_output.txt"
        test_output_file.write_text("Tests passed\n")

        log_file = work_dir / "log.md"
        log_file.write_text("")

        ctx = Context(
            work_dir=work_dir,
            task_file="task.md",
            project_root=project_root,
        )

        return ctx

    @patch('zen_mode.judge.phase_verify')
    @patch('zen_mode.implement.run_linter_with_timeout')
    @patch('zen_mode.judge.git.get_changed_filenames')
    @patch('zen_mode.judge.run_claude')
    def test_constitution_included_when_claude_md_exists(
        self, mock_claude, mock_changed_files, mock_linter, mock_verify, mock_ctx
    ):
        """When CLAUDE.md exists, it should be included in the fix prompt."""
        from zen_mode.judge import phase_judge_ctx

        # Create CLAUDE.md in project root
        claude_md = mock_ctx.project_root / "CLAUDE.md"
        constitution_content = "# Project Constitution\n- Rule 1: Use type hints\n- Rule 2: No print statements"
        claude_md.write_text(constitution_content)

        mock_changed_files.return_value = "src/main.py"

        captured_prompts = []

        def capture_prompts(prompt, model=None, **kwargs):
            captured_prompts.append(prompt)
            # First call: judge rejects
            if len(captured_prompts) == 1:
                return "JUDGE_REJECTED\n\n## Issues\n- Missing type hints"
            # Second call: fix succeeds, then judge approves
            elif len(captured_prompts) == 2:
                return "FIXES_COMPLETE"
            else:
                return "JUDGE_APPROVED"

        mock_claude.side_effect = capture_prompts
        mock_linter.return_value = (True, "")
        mock_verify.return_value = (VerifyState.PASS, "")

        phase_judge_ctx(mock_ctx)

        # Should have 3 prompts: judge, fix, judge again
        assert len(captured_prompts) >= 2

        # The second prompt is the fix prompt
        fix_prompt = captured_prompts[1]

        # Constitution should be in the fix prompt
        assert "## Constitution (CLAUDE.md)" in fix_prompt
        assert constitution_content in fix_prompt

    @patch('zen_mode.judge.phase_verify')
    @patch('zen_mode.implement.run_linter_with_timeout')
    @patch('zen_mode.judge.git.get_changed_filenames')
    @patch('zen_mode.judge.run_claude')
    def test_fallback_message_when_no_claude_md(
        self, mock_claude, mock_changed_files, mock_linter, mock_verify, mock_ctx
    ):
        """When CLAUDE.md doesn't exist, should show fallback message."""
        from zen_mode.judge import phase_judge_ctx

        # DO NOT create CLAUDE.md - it should not exist

        mock_changed_files.return_value = "src/main.py"

        captured_prompts = []

        def capture_prompts(prompt, model=None, **kwargs):
            captured_prompts.append(prompt)
            if len(captured_prompts) == 1:
                return "JUDGE_REJECTED\n\n## Issues\n- Problem found"
            elif len(captured_prompts) == 2:
                return "FIXES_COMPLETE"
            else:
                return "JUDGE_APPROVED"

        mock_claude.side_effect = capture_prompts
        mock_linter.return_value = (True, "")
        mock_verify.return_value = (VerifyState.PASS, "")

        phase_judge_ctx(mock_ctx)

        # The fix prompt should have fallback message
        fix_prompt = captured_prompts[1]

        assert "## Constitution (CLAUDE.md)" in fix_prompt
        assert "[No CLAUDE.md found]" in fix_prompt

    @patch('zen_mode.judge.phase_verify')
    @patch('zen_mode.implement.run_linter_with_timeout')
    @patch('zen_mode.judge.git.get_changed_filenames')
    @patch('zen_mode.judge.run_claude')
    def test_constitution_appears_before_changed_files(
        self, mock_claude, mock_changed_files, mock_linter, mock_verify, mock_ctx
    ):
        """Constitution section should appear before Changed Files section."""
        from zen_mode.judge import phase_judge_ctx

        # Create CLAUDE.md
        claude_md = mock_ctx.project_root / "CLAUDE.md"
        claude_md.write_text("# Rules\n- Follow PEP 8")

        mock_changed_files.return_value = "src/main.py"

        captured_prompts = []

        def capture_prompts(prompt, model=None, **kwargs):
            captured_prompts.append(prompt)
            if len(captured_prompts) == 1:
                return "JUDGE_REJECTED\n\n## Issues\n- Bad code"
            elif len(captured_prompts) == 2:
                return "FIXES_COMPLETE"
            else:
                return "JUDGE_APPROVED"

        mock_claude.side_effect = capture_prompts
        mock_linter.return_value = (True, "")
        mock_verify.return_value = (VerifyState.PASS, "")

        phase_judge_ctx(mock_ctx)

        fix_prompt = captured_prompts[1]

        # Find positions of key sections
        constitution_pos = fix_prompt.find("## Constitution (CLAUDE.md)")
        changed_files_pos = fix_prompt.find("## Changed Files")

        # Constitution should appear before Changed Files
        assert constitution_pos < changed_files_pos, \
            "Constitution should appear before Changed Files section"

    @patch('zen_mode.judge.phase_verify')
    @patch('zen_mode.implement.run_linter_with_timeout')
    @patch('zen_mode.judge.git.get_changed_filenames')
    @patch('zen_mode.judge.run_claude')
    def test_constitution_appears_after_feedback(
        self, mock_claude, mock_changed_files, mock_linter, mock_verify, mock_ctx
    ):
        """Constitution section should appear after the judge feedback."""
        from zen_mode.judge import phase_judge_ctx

        # Create CLAUDE.md
        claude_md = mock_ctx.project_root / "CLAUDE.md"
        claude_md.write_text("# Rules\n- Test everything")

        mock_changed_files.return_value = "src/main.py"

        captured_prompts = []
        feedback = "## Issues\n- Missing tests\n\n## Fix Plan\nStep 1: Add tests"

        def capture_prompts(prompt, model=None, **kwargs):
            captured_prompts.append(prompt)
            if len(captured_prompts) == 1:
                return f"JUDGE_REJECTED\n\n{feedback}"
            elif len(captured_prompts) == 2:
                return "FIXES_COMPLETE"
            else:
                return "JUDGE_APPROVED"

        mock_claude.side_effect = capture_prompts
        mock_linter.return_value = (True, "")
        mock_verify.return_value = (VerifyState.PASS, "")

        phase_judge_ctx(mock_ctx)

        fix_prompt = captured_prompts[1]

        # Find positions
        feedback_pos = fix_prompt.find(feedback)
        constitution_pos = fix_prompt.find("## Constitution (CLAUDE.md)")

        # Feedback should appear before Constitution
        assert feedback_pos < constitution_pos, \
            "Judge feedback should appear before Constitution section"

    @patch('zen_mode.judge.phase_verify')
    @patch('zen_mode.implement.run_linter_with_timeout')
    @patch('zen_mode.judge.git.get_changed_filenames')
    @patch('zen_mode.judge.run_claude')
    def test_constitution_content_preserved(
        self, mock_claude, mock_changed_files, mock_linter, mock_verify, mock_ctx
    ):
        """Constitution content should be preserved exactly as written."""
        from zen_mode.judge import phase_judge_ctx

        # Create CLAUDE.md with specific formatting
        claude_md = mock_ctx.project_root / "CLAUDE.md"
        complex_content = """# Project Rules

## Code Style
- Use type hints everywhere
- Max line length: 100

## Security
- Never log passwords
- Validate all user input

## Testing
- Write tests for all features
"""
        claude_md.write_text(complex_content)

        mock_changed_files.return_value = "src/auth.py"

        captured_prompts = []

        def capture_prompts(prompt, model=None, **kwargs):
            captured_prompts.append(prompt)
            if len(captured_prompts) == 1:
                return "JUDGE_REJECTED\n\n## Issues\n- Security issue"
            elif len(captured_prompts) == 2:
                return "FIXES_COMPLETE"
            else:
                return "JUDGE_APPROVED"

        mock_claude.side_effect = capture_prompts
        mock_linter.return_value = (True, "")
        mock_verify.return_value = (VerifyState.PASS, "")

        phase_judge_ctx(mock_ctx)

        fix_prompt = captured_prompts[1]

        # All key parts of the constitution should be present
        assert "# Project Rules" in fix_prompt
        assert "## Code Style" in fix_prompt
        assert "## Security" in fix_prompt
        assert "## Testing" in fix_prompt
        assert "Use type hints everywhere" in fix_prompt
        assert "Never log passwords" in fix_prompt
        assert "Write tests for all features" in fix_prompt

    @patch('zen_mode.judge.phase_verify')
    @patch('zen_mode.implement.run_linter_with_timeout')
    @patch('zen_mode.judge.git.get_changed_filenames')
    @patch('zen_mode.judge.run_claude')
    def test_fix_prompt_structure(
        self, mock_claude, mock_changed_files, mock_linter, mock_verify, mock_ctx
    ):
        """Fix prompt should have the expected structure with all sections."""
        from zen_mode.judge import phase_judge_ctx

        # Create CLAUDE.md
        claude_md = mock_ctx.project_root / "CLAUDE.md"
        claude_md.write_text("# Rules\n- Be awesome")

        mock_changed_files.return_value = "src/app.py"

        captured_prompts = []

        def capture_prompts(prompt, model=None, **kwargs):
            captured_prompts.append(prompt)
            if len(captured_prompts) == 1:
                return "JUDGE_REJECTED\n\n## Issues\n- Fix this"
            elif len(captured_prompts) == 2:
                return "FIXES_COMPLETE"
            else:
                return "JUDGE_APPROVED"

        mock_claude.side_effect = capture_prompts
        mock_linter.return_value = (True, "")
        mock_verify.return_value = (VerifyState.PASS, "")

        phase_judge_ctx(mock_ctx)

        fix_prompt = captured_prompts[1]

        # Verify all expected sections are present in order
        assert "JUDGE FEEDBACK - Fixes Required:" in fix_prompt
        assert "## Constitution (CLAUDE.md)" in fix_prompt
        assert "## Changed Files" in fix_prompt
        assert "## Original Plan" in fix_prompt
        assert "IMPORTANT: This is a fresh session" in fix_prompt
        assert "End with: FIXES_COMPLETE or FIXES_BLOCKED" in fix_prompt

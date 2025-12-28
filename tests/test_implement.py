"""
Tests for Implement phase helper functions.

Tests linter timeout, backup logic, and prompt building.
(Escalation tests are in test_model_escalation.py)
"""
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from zen_mode.implement import (
    run_linter_with_timeout,
    backup_scout_files_ctx,
    build_verify_prompt,
    build_implement_prompt,
    extract_plan_goal,
    get_step_context,
)
from zen_mode.context import Context


class TestExtractPlanGoal:
    """Tests for extract_plan_goal() function."""

    def test_extracts_goal_from_standard_format(self):
        plan = "# Plan\n**Goal:** Build a REST API\n## Steps"
        assert extract_plan_goal(plan) == "Build a REST API"

    def test_handles_missing_goal(self):
        plan = "# Plan\n## Step 1: Do something"
        result = extract_plan_goal(plan)
        # Falls back to first non-header line
        assert "Step 1" in result or result == "Complete the implementation"

    def test_handles_empty_plan(self):
        assert extract_plan_goal("") == "Complete the implementation"

    def test_goal_with_extra_whitespace(self):
        plan = "**Goal:**   Add validation   \n## Steps"
        assert extract_plan_goal(plan) == "Add validation"

    def test_goal_at_end_of_line(self):
        plan = "**Goal:** Implement feature"
        assert extract_plan_goal(plan) == "Implement feature"


class TestGetStepContext:
    """Tests for get_step_context() function."""

    def test_first_step_no_prev(self):
        steps = [(1, "First"), (2, "Second"), (3, "Third")]
        ctx = get_step_context(steps, 0)
        assert ctx['prev'] is None
        assert ctx['next'] == "Second"
        assert ctx['total'] == 3

    def test_middle_step_has_both(self):
        steps = [(1, "First"), (2, "Second"), (3, "Third")]
        ctx = get_step_context(steps, 1)
        assert ctx['prev'] == "First"
        assert ctx['next'] == "Third"
        assert ctx['total'] == 3

    def test_last_step_no_next(self):
        steps = [(1, "First"), (2, "Second"), (3, "Third")]
        ctx = get_step_context(steps, 2)
        assert ctx['prev'] == "Second"
        assert ctx['next'] is None
        assert ctx['total'] == 3

    def test_single_step_plan(self):
        steps = [(1, "Only step")]
        ctx = get_step_context(steps, 0)
        assert ctx['prev'] is None
        assert ctx['next'] is None
        assert ctx['total'] == 1

    def test_truncates_long_descriptions(self):
        steps = [(1, "A" * 100), (2, "B" * 100)]
        ctx = get_step_context(steps, 1)
        assert len(ctx['prev']) == 80  # truncated to 80 chars


class TestRunLinterWithTimeout:
    """Tests for run_linter_with_timeout() function."""

    @patch('zen_mode.implement.linter.run_lint')
    @patch('zen_mode.implement.git.get_changed_files')
    def test_success_returns_violations(self, mock_git, mock_lint):
        """Successful lint returns True and output."""
        mock_git.return_value = ["src/foo.py"]
        mock_lint.return_value = (True, "All good")

        passed, output = run_linter_with_timeout(timeout=5)

        assert passed is True
        assert output == "All good"

    @patch('zen_mode.implement.linter.run_lint')
    @patch('zen_mode.implement.git.get_changed_files')
    def test_failure_returns_violations(self, mock_git, mock_lint):
        """Failed lint returns False and errors."""
        mock_git.return_value = ["src/foo.py"]
        mock_lint.return_value = (False, "Line 10: undefined name 'bar'")

        passed, output = run_linter_with_timeout(timeout=5)

        assert passed is False
        assert "undefined name" in output

    @patch('zen_mode.implement.linter.run_lint')
    @patch('zen_mode.implement.git.get_changed_files')
    def test_timeout_returns_false(self, mock_git, mock_lint):
        """Timeout returns False with timeout message."""
        mock_git.return_value = ["src/foo.py"]

        # Make linter hang
        def slow_lint(paths=None):
            time.sleep(2)
            return (True, "")

        mock_lint.side_effect = slow_lint

        passed, output = run_linter_with_timeout(timeout=0.1)

        assert passed is False
        assert "timed out" in output.lower()

    @patch('zen_mode.implement.linter.run_lint')
    @patch('zen_mode.implement.git.get_changed_files')
    def test_uses_provided_paths(self, mock_git, mock_lint):
        """Linter uses explicitly provided paths instead of git."""
        mock_lint.return_value = (True, "")
        explicit_paths = ["specific/file.py"]

        run_linter_with_timeout(paths=explicit_paths)

        # Should NOT call git.get_changed_files
        mock_git.assert_not_called()
        # Should pass explicit paths to linter
        mock_lint.assert_called_once_with(paths=explicit_paths)


class TestBackupScoutFilesCtx:
    """Tests for backup_scout_files_ctx() function."""

    @pytest.fixture
    def mock_ctx(self, tmp_path):
        """Set up a mock context for testing."""
        work_dir = tmp_path / ".zen"
        work_dir.mkdir()

        # Create scout file referencing files
        scout_file = work_dir / "scout.md"
        scout_file.write_text("""
# Scout Report

Files to modify:
- `src/main.py` - main entry point
- `src/utils.py` - utility functions
- `nonexistent.py` - doesn't exist
""")

        # Create log file
        log_file = work_dir / "log.md"
        log_file.write_text("")

        # Create plan file
        plan_file = work_dir / "plan.md"
        plan_file.write_text("")

        # Create the actual source files
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "main.py").write_text("# main.py content")
        (src_dir / "utils.py").write_text("# utils.py content")

        ctx = Context(
            work_dir=work_dir,
            task_file="task.md",
            project_root=tmp_path,
        )

        return ctx

    def test_creates_backup(self, mock_ctx):
        """backup_scout_files_ctx creates backups of referenced files."""
        backup_scout_files_ctx(mock_ctx)

        # Check backups were created
        backup_main = mock_ctx.backup_dir / "src" / "main.py"
        backup_utils = mock_ctx.backup_dir / "src" / "utils.py"

        assert backup_main.exists()
        assert backup_utils.exists()
        assert backup_main.read_text() == "# main.py content"
        assert backup_utils.read_text() == "# utils.py content"

    def test_ignores_nonexistent_files(self, mock_ctx):
        """backup_scout_files_ctx ignores files that don't exist."""
        backup_scout_files_ctx(mock_ctx)

        # nonexistent.py should not cause an error or create backup
        backup_nonexistent = mock_ctx.backup_dir / "nonexistent.py"
        assert not backup_nonexistent.exists()

    def test_handles_empty_scout(self, mock_ctx):
        """backup_scout_files_ctx handles empty scout file."""
        mock_ctx.scout_file.write_text("")

        # Should not raise
        backup_scout_files_ctx(mock_ctx)

        # Backup dir may or may not exist but no files backed up
        if mock_ctx.backup_dir.exists():
            backed_up = list(mock_ctx.backup_dir.rglob("*"))
            files = [f for f in backed_up if f.is_file()]
            assert len(files) == 0


class TestBuildVerifyPrompt:
    """Tests for build_verify_prompt() function."""

    def test_includes_step_description(self):
        """Verify prompt includes the step description."""
        step_desc = "Check that all tests pass"
        plan = "## Step 1: Run tests\n## Step 2: Verify"

        prompt = build_verify_prompt(step_desc, plan)

        assert step_desc in prompt

    def test_lean_mode_excludes_full_plan(self):
        """Verify prompt uses lean context by default (no full plan)."""
        step_desc = "Verify tests"
        plan = "## Step 1: Add feature\n## Step 2: Verify tests"

        prompt = build_verify_prompt(step_desc, plan)

        # Lean mode: plan not included, but recovery hint is
        assert plan not in prompt
        assert ".zen/plan.md" in prompt

    def test_full_plan_mode_includes_plan(self):
        """Verify prompt includes full plan when requested."""
        step_desc = "Verify tests"
        plan = "## Step 1: Add feature\n## Step 2: Verify tests"

        prompt = build_verify_prompt(step_desc, plan, include_full_plan=True)

        assert plan in prompt

    def test_includes_verification_instructions(self):
        """Verify prompt has verification-only instructions."""
        prompt = build_verify_prompt("check it", "plan content")

        assert "Do NOT make any changes" in prompt or "verification only" in prompt.lower()

    def test_includes_completion_markers(self):
        """Verify prompt includes expected completion markers."""
        prompt = build_verify_prompt("verify", "plan")

        assert "STEP_COMPLETE" in prompt
        assert "STEP_BLOCKED" in prompt


class TestBuildImplementPrompt:
    """Tests for build_implement_prompt() function."""

    def test_includes_step_number_and_description(self, tmp_path):
        """Implement prompt includes step details."""
        prompt = build_implement_prompt(
            step_num=3,
            step_desc="Add error handling",
            plan="Full plan text",
            project_root=tmp_path,
        )

        assert "Step 3" in prompt
        assert "Add error handling" in prompt

    def test_lean_mode_excludes_full_plan(self, tmp_path):
        """Implement prompt uses lean context by default."""
        plan = "## Step 1: Setup\n## Step 2: Implement\n## Step 3: Test"
        step_context = {'prev': 'Setup', 'next': 'Test', 'total': 3}
        prompt = build_implement_prompt(
            step_num=2,
            step_desc="Implement feature",
            plan=plan,
            project_root=tmp_path,
            step_context=step_context,
            goal="Build the feature",
        )

        # Lean mode: plan not included, but navigation and recovery are
        assert plan not in prompt
        assert "Step 2 of 3" in prompt
        assert ".zen/plan.md" in prompt

    def test_full_plan_mode_includes_plan(self, tmp_path):
        """Implement prompt includes full plan when requested."""
        plan = "## Step 1: Setup\n## Step 2: Implement\n## Step 3: Test"
        prompt = build_implement_prompt(
            step_num=2,
            step_desc="Implement feature",
            plan=plan,
            project_root=tmp_path,
            include_full_plan=True,
        )

        assert plan in prompt

    def test_includes_allowed_files_scope(self, tmp_path):
        """Implement prompt includes allowed files restriction."""
        prompt = build_implement_prompt(
            step_num=1,
            step_desc="Do something",
            plan="plan",
            project_root=tmp_path,
            allowed_files="src/auth/*.py",
        )

        assert "src/auth/*.py" in prompt
        assert "SCOPE" in prompt
        assert "MUST ONLY modify" in prompt

    def test_no_scope_without_allowed_files(self, tmp_path):
        """Implement prompt has no SCOPE section without allowed_files."""
        prompt = build_implement_prompt(
            step_num=1,
            step_desc="Do something",
            plan="plan",
            project_root=tmp_path,
            allowed_files=None,
        )

        assert "SCOPE" not in prompt

    def test_includes_preflight_check(self, tmp_path):
        """Implement prompt includes preflight check."""
        prompt = build_implement_prompt(
            step_num=1,
            step_desc="something",
            plan="plan",
            project_root=tmp_path,
        )

        assert "preflight" in prompt.lower()
        assert "FILES" in prompt
        assert "TASK" in prompt

    def test_includes_completion_markers(self, tmp_path):
        """Implement prompt includes expected completion markers."""
        prompt = build_implement_prompt(
            step_num=1,
            step_desc="something",
            plan="plan",
            project_root=tmp_path,
        )

        assert "STEP_COMPLETE" in prompt
        assert "STEP_BLOCKED" in prompt

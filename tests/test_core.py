"""
Tests for core.py - the main orchestration module.

Tests cover:
1. _check_previous_completion() - Checks if task already completed
2. run() - Main entry point (mock Claude calls)
3. Flag handling (--reset, --retry, --skip-judge)
4. Fast track vs normal flow paths
5. Error handling paths
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestCheckPreviousCompletion:
    """Tests for _check_previous_completion() function."""

    def test_returns_false_when_file_missing(self, tmp_path):
        """No notes file means not completed."""
        from zen_mode.core import _check_previous_completion

        notes_file = tmp_path / "final_notes.md"
        assert _check_previous_completion(notes_file) is False

    def test_returns_false_when_file_empty(self, tmp_path):
        """Empty notes file means not completed."""
        from zen_mode.core import _check_previous_completion

        notes_file = tmp_path / "final_notes.md"
        notes_file.write_text("")
        assert _check_previous_completion(notes_file) is False

    def test_returns_false_when_no_cost_summary(self, tmp_path):
        """Notes without cost summary means incomplete run."""
        from zen_mode.core import _check_previous_completion

        notes_file = tmp_path / "final_notes.md"
        notes_file.write_text("# Summary\n- Did some stuff\n")
        assert _check_previous_completion(notes_file) is False

    def test_returns_true_when_cost_summary_present(self, tmp_path):
        """Notes with cost summary means completed run."""
        from zen_mode.core import _check_previous_completion

        notes_file = tmp_path / "final_notes.md"
        notes_file.write_text(
            "# Summary\n- Did some stuff\n\n## Cost Summary\nTotal: $0.05\n"
        )
        assert _check_previous_completion(notes_file) is True

    def test_handles_read_error_gracefully(self, tmp_path, monkeypatch):
        """Handle read errors by returning False."""
        from zen_mode.core import _check_previous_completion

        notes_file = tmp_path / "final_notes.md"
        notes_file.write_text("content")

        # Make read_text raise an error
        def raise_error(*args, **kwargs):
            raise IOError("Permission denied")

        monkeypatch.setattr(Path, "read_text", raise_error)
        assert _check_previous_completion(notes_file) is False


class TestWriteCostSummary:
    """Tests for _write_cost_summary() helper."""

    def test_writes_cost_breakdown(self, tmp_path):
        """Cost summary written to notes file."""
        from zen_mode.core import _write_cost_summary
        from zen_mode.context import Context

        work_dir = tmp_path / ".zen"
        work_dir.mkdir()
        notes_file = work_dir / "final_notes.md"
        notes_file.write_text("# Summary\n")
        log_file = work_dir / "log.md"

        ctx = Context(
            work_dir=work_dir,
            task_file="task.md",
            project_root=tmp_path,
        )
        ctx.record_cost("scout", 0.01, {"in": 100, "out": 50, "cache_read": 10})
        ctx.record_cost("plan", 0.02, {"in": 200, "out": 100, "cache_read": 20})

        _write_cost_summary(ctx)

        content = notes_file.read_text()
        assert "## Cost Summary" in content
        assert "$0.03" in content  # Total
        assert "scout" in content
        assert "plan" in content

    def test_no_op_when_no_costs(self, tmp_path):
        """No cost summary written when no costs recorded."""
        from zen_mode.core import _write_cost_summary
        from zen_mode.context import Context

        work_dir = tmp_path / ".zen"
        work_dir.mkdir()
        notes_file = work_dir / "final_notes.md"
        notes_file.write_text("# Summary\n")

        ctx = Context(
            work_dir=work_dir,
            task_file="task.md",
            project_root=tmp_path,
        )

        _write_cost_summary(ctx)

        content = notes_file.read_text()
        assert "## Cost Summary" not in content


class TestRunFlagHandling:
    """Tests for flag handling in run()."""

    @patch('zen_mode.core.phase_scout_ctx')
    @patch('zen_mode.core.phase_plan_ctx')
    @patch('zen_mode.core.phase_implement_ctx')
    @patch('zen_mode.core.verify_and_fix')
    @patch('zen_mode.core.project_has_tests')
    @patch('zen_mode.core.should_skip_judge_ctx')
    @patch('zen_mode.core.run_claude')
    def test_reset_flag_clears_work_dir(
        self,
        mock_run_claude,
        mock_skip_judge,
        mock_has_tests,
        mock_verify,
        mock_implement,
        mock_plan,
        mock_scout,
        tmp_path,
        monkeypatch
    ):
        """--reset flag removes work directory."""
        from zen_mode import core
        from zen_mode.config import WORK_DIR_NAME

        project_root = tmp_path
        work_dir = project_root / WORK_DIR_NAME
        work_dir.mkdir(parents=True)

        # Create existing files
        (work_dir / "scout.md").write_text("old scout")
        (work_dir / "plan.md").write_text("old plan")

        task_file = project_root / "task.md"
        task_file.write_text("# Test task")

        monkeypatch.setattr('zen_mode.core.PROJECT_ROOT', project_root)
        monkeypatch.setattr('zen_mode.config.PROJECT_ROOT', project_root)

        def scout_side_effect(ctx):
            ctx.scout_file.write_text("<TRIAGE>\nFAST_TRACK: NO\n</TRIAGE>")
        mock_scout.side_effect = scout_side_effect

        def plan_side_effect(ctx):
            ctx.plan_file.write_text("## Step 1: Do stuff\n")
        mock_plan.side_effect = plan_side_effect

        mock_has_tests.return_value = False
        mock_skip_judge.return_value = True
        mock_run_claude.return_value = "Summary"

        core.run(str(task_file), flags={"--reset"})

        # Work dir should be recreated fresh
        scout_content = (work_dir / "scout.md").read_text()
        assert "old scout" not in scout_content

    @patch('zen_mode.core.phase_scout_ctx')
    @patch('zen_mode.core.phase_plan_ctx')
    @patch('zen_mode.core.phase_implement_ctx')
    @patch('zen_mode.core.verify_and_fix')
    @patch('zen_mode.core.project_has_tests')
    @patch('zen_mode.core.should_skip_judge_ctx')
    @patch('zen_mode.core.run_claude')
    def test_retry_flag_clears_completion_markers(
        self,
        mock_run_claude,
        mock_skip_judge,
        mock_has_tests,
        mock_verify,
        mock_implement,
        mock_plan,
        mock_scout,
        tmp_path,
        monkeypatch
    ):
        """--retry flag clears [COMPLETE] markers from log."""
        from zen_mode import core
        from zen_mode.config import WORK_DIR_NAME

        project_root = tmp_path
        work_dir = project_root / WORK_DIR_NAME
        work_dir.mkdir(parents=True)

        # Create log with completion markers
        log_file = work_dir / "log.md"
        log_file.write_text(
            "[SCOUT] Starting...\n[COMPLETE] Step 1\n[COMPLETE] Step 2\n"
        )

        task_file = project_root / "task.md"
        task_file.write_text("# Test task")

        monkeypatch.setattr('zen_mode.core.PROJECT_ROOT', project_root)
        monkeypatch.setattr('zen_mode.config.PROJECT_ROOT', project_root)

        def scout_side_effect(ctx):
            ctx.scout_file.write_text("<TRIAGE>\nFAST_TRACK: NO\n</TRIAGE>")
        mock_scout.side_effect = scout_side_effect

        def plan_side_effect(ctx):
            ctx.plan_file.write_text("## Step 1: Do stuff\n")
        mock_plan.side_effect = plan_side_effect

        mock_has_tests.return_value = False
        mock_skip_judge.return_value = True
        mock_run_claude.return_value = "Summary"

        core.run(str(task_file), flags={"--retry"})

        # Completion markers should be removed
        log_content = log_file.read_text()
        assert "[SCOUT] Starting" in log_content
        assert "[COMPLETE] Step" not in log_content

    @patch('zen_mode.core.phase_scout_ctx')
    @patch('zen_mode.core.phase_plan_ctx')
    @patch('zen_mode.core.phase_implement_ctx')
    @patch('zen_mode.core.verify_and_fix')
    @patch('zen_mode.core.project_has_tests')
    @patch('zen_mode.core.phase_judge_ctx')
    @patch('zen_mode.core.should_skip_judge_ctx')
    @patch('zen_mode.core.run_claude')
    def test_skip_judge_flag_skips_judge_phase(
        self,
        mock_run_claude,
        mock_skip_judge,
        mock_judge,
        mock_has_tests,
        mock_verify,
        mock_implement,
        mock_plan,
        mock_scout,
        tmp_path,
        monkeypatch
    ):
        """--skip-judge flag skips judge phase."""
        from zen_mode import core
        from zen_mode.config import WORK_DIR_NAME

        project_root = tmp_path
        work_dir = project_root / WORK_DIR_NAME
        work_dir.mkdir(parents=True)

        task_file = project_root / "task.md"
        task_file.write_text("# Test task")

        monkeypatch.setattr('zen_mode.core.PROJECT_ROOT', project_root)
        monkeypatch.setattr('zen_mode.config.PROJECT_ROOT', project_root)

        def scout_side_effect(ctx):
            ctx.scout_file.write_text("<TRIAGE>\nFAST_TRACK: NO\n</TRIAGE>")
        mock_scout.side_effect = scout_side_effect

        def plan_side_effect(ctx):
            ctx.plan_file.write_text("## Step 1: Do stuff\n")
        mock_plan.side_effect = plan_side_effect

        mock_has_tests.return_value = False
        mock_skip_judge.return_value = False  # Would normally call judge
        mock_run_claude.return_value = "Summary"

        core.run(str(task_file), flags={"--skip-judge"})

        # Judge should NOT be called
        mock_judge.assert_not_called()

    @patch('zen_mode.core.phase_scout_ctx')
    @patch('zen_mode.core.phase_plan_ctx')
    @patch('zen_mode.core.phase_implement_ctx')
    @patch('zen_mode.core.verify_and_fix')
    @patch('zen_mode.core.project_has_tests')
    @patch('zen_mode.core.should_skip_judge_ctx')
    @patch('zen_mode.core.run_claude')
    def test_skip_verify_flag_skips_verification(
        self,
        mock_run_claude,
        mock_skip_judge,
        mock_has_tests,
        mock_verify,
        mock_implement,
        mock_plan,
        mock_scout,
        tmp_path,
        monkeypatch
    ):
        """--skip-verify flag skips verification phase."""
        from zen_mode import core
        from zen_mode.config import WORK_DIR_NAME

        project_root = tmp_path
        work_dir = project_root / WORK_DIR_NAME
        work_dir.mkdir(parents=True)

        task_file = project_root / "task.md"
        task_file.write_text("# Test task")

        monkeypatch.setattr('zen_mode.core.PROJECT_ROOT', project_root)
        monkeypatch.setattr('zen_mode.config.PROJECT_ROOT', project_root)

        def scout_side_effect(ctx):
            ctx.scout_file.write_text("<TRIAGE>\nFAST_TRACK: NO\n</TRIAGE>")
        mock_scout.side_effect = scout_side_effect

        def plan_side_effect(ctx):
            ctx.plan_file.write_text("## Step 1: Do stuff\n")
        mock_plan.side_effect = plan_side_effect

        mock_has_tests.return_value = True  # Has tests, would verify
        mock_skip_judge.return_value = True
        mock_run_claude.return_value = "Summary"

        core.run(str(task_file), flags={"--skip-verify"})

        # Verify should NOT be called
        mock_verify.assert_not_called()


class TestRunPreviousCompletion:
    """Tests for previous completion detection."""

    @patch('zen_mode.core.phase_scout_ctx')
    def test_skips_when_previously_completed(
        self,
        mock_scout,
        tmp_path,
        monkeypatch
    ):
        """Skip run when previous run completed successfully."""
        from zen_mode import core
        from zen_mode.config import WORK_DIR_NAME

        project_root = tmp_path
        work_dir = project_root / WORK_DIR_NAME
        work_dir.mkdir(parents=True)

        # Create completed notes
        notes_file = work_dir / "final_notes.md"
        notes_file.write_text("# Done\n\n## Cost Summary\nTotal: $0.05\n")

        task_file = project_root / "task.md"
        task_file.write_text("# Test task")

        monkeypatch.setattr('zen_mode.core.PROJECT_ROOT', project_root)
        monkeypatch.setattr('zen_mode.config.PROJECT_ROOT', project_root)

        core.run(str(task_file))

        # Scout should NOT be called (skipped)
        mock_scout.assert_not_called()

    @patch('zen_mode.core.phase_scout_ctx')
    @patch('zen_mode.core.phase_plan_ctx')
    @patch('zen_mode.core.phase_implement_ctx')
    @patch('zen_mode.core.project_has_tests')
    @patch('zen_mode.core.should_skip_judge_ctx')
    @patch('zen_mode.core.run_claude')
    def test_reset_overrides_previous_completion(
        self,
        mock_run_claude,
        mock_skip_judge,
        mock_has_tests,
        mock_implement,
        mock_plan,
        mock_scout,
        tmp_path,
        monkeypatch
    ):
        """--reset forces new run even if previously completed."""
        from zen_mode import core
        from zen_mode.config import WORK_DIR_NAME

        project_root = tmp_path
        work_dir = project_root / WORK_DIR_NAME
        work_dir.mkdir(parents=True)

        # Create completed notes
        notes_file = work_dir / "final_notes.md"
        notes_file.write_text("# Done\n\n## Cost Summary\nTotal: $0.05\n")

        task_file = project_root / "task.md"
        task_file.write_text("# Test task")

        monkeypatch.setattr('zen_mode.core.PROJECT_ROOT', project_root)
        monkeypatch.setattr('zen_mode.config.PROJECT_ROOT', project_root)

        def scout_side_effect(ctx):
            ctx.scout_file.write_text("<TRIAGE>\nFAST_TRACK: NO\n</TRIAGE>")
        mock_scout.side_effect = scout_side_effect

        def plan_side_effect(ctx):
            ctx.plan_file.write_text("## Step 1: Do stuff\n")
        mock_plan.side_effect = plan_side_effect

        mock_has_tests.return_value = False
        mock_skip_judge.return_value = True
        mock_run_claude.return_value = "Summary"

        core.run(str(task_file), flags={"--reset"})

        # Scout SHOULD be called
        mock_scout.assert_called_once()


class TestRunFastTrack:
    """Tests for fast track flow."""

    @patch('zen_mode.core.phase_scout_ctx')
    @patch('zen_mode.core.phase_plan_ctx')
    @patch('zen_mode.core.phase_implement_ctx')
    @patch('zen_mode.core.verify_and_fix')
    @patch('zen_mode.core.project_has_tests')
    @patch('zen_mode.core.run_claude')
    def test_fast_track_success_skips_planner(
        self,
        mock_run_claude,
        mock_has_tests,
        mock_verify,
        mock_implement,
        mock_plan,
        mock_scout,
        tmp_path,
        monkeypatch
    ):
        """Successful fast track skips planner phase."""
        from zen_mode import core
        from zen_mode.config import WORK_DIR_NAME

        project_root = tmp_path
        work_dir = project_root / WORK_DIR_NAME
        work_dir.mkdir(parents=True)

        task_file = project_root / "task.md"
        task_file.write_text("# Test task")

        monkeypatch.setattr('zen_mode.core.PROJECT_ROOT', project_root)
        monkeypatch.setattr('zen_mode.config.PROJECT_ROOT', project_root)

        def scout_side_effect(ctx):
            ctx.scout_file.write_text("""
<TRIAGE>
COMPLEXITY: LOW
CONFIDENCE: 0.95
FAST_TRACK: YES
</TRIAGE>

<MICRO_SPEC>
TARGET_FILE: src/main.py
OPERATION: UPDATE
INSTRUCTION: Add comment
</MICRO_SPEC>
""")
        mock_scout.side_effect = scout_side_effect

        mock_has_tests.return_value = True
        mock_verify.return_value = True  # Fast track succeeds
        mock_run_claude.return_value = "Summary"

        core.run(str(task_file))

        # Planner should NOT be called
        mock_plan.assert_not_called()

    @patch('zen_mode.core.phase_scout_ctx')
    @patch('zen_mode.core.phase_plan_ctx')
    @patch('zen_mode.core.phase_implement_ctx')
    @patch('zen_mode.core.verify_and_fix')
    @patch('zen_mode.core.project_has_tests')
    @patch('zen_mode.core.should_skip_judge_ctx')
    @patch('zen_mode.core.run_claude')
    def test_fast_track_failure_escalates_to_planner(
        self,
        mock_run_claude,
        mock_skip_judge,
        mock_has_tests,
        mock_verify,
        mock_implement,
        mock_plan,
        mock_scout,
        tmp_path,
        monkeypatch
    ):
        """Failed fast track escalates to planner phase."""
        from zen_mode import core
        from zen_mode.config import WORK_DIR_NAME

        project_root = tmp_path
        work_dir = project_root / WORK_DIR_NAME
        work_dir.mkdir(parents=True)

        task_file = project_root / "task.md"
        task_file.write_text("# Test task")

        monkeypatch.setattr('zen_mode.core.PROJECT_ROOT', project_root)
        monkeypatch.setattr('zen_mode.config.PROJECT_ROOT', project_root)

        def scout_side_effect(ctx):
            ctx.scout_file.write_text("""
<TRIAGE>
COMPLEXITY: LOW
CONFIDENCE: 0.95
FAST_TRACK: YES
</TRIAGE>

<MICRO_SPEC>
TARGET_FILE: src/main.py
OPERATION: UPDATE
INSTRUCTION: Add comment
</MICRO_SPEC>
""")
        mock_scout.side_effect = scout_side_effect

        def plan_side_effect(ctx):
            ctx.plan_file.write_text("## Step 1: Real plan\n")
        mock_plan.side_effect = plan_side_effect

        mock_has_tests.return_value = True
        # First verify fails (fast track), second succeeds
        mock_verify.side_effect = [False, True]
        mock_skip_judge.return_value = True
        mock_run_claude.return_value = "Summary"

        core.run(str(task_file))

        # Planner SHOULD be called after escalation
        mock_plan.assert_called_once()

    @patch('zen_mode.core.phase_scout_ctx')
    @patch('zen_mode.core.phase_plan_ctx')
    @patch('zen_mode.core.phase_implement_ctx')
    @patch('zen_mode.core.verify_and_fix')
    @patch('zen_mode.core.project_has_tests')
    @patch('zen_mode.core.run_claude')
    def test_fast_track_no_tests_skips_verify(
        self,
        mock_run_claude,
        mock_has_tests,
        mock_verify,
        mock_implement,
        mock_plan,
        mock_scout,
        tmp_path,
        monkeypatch
    ):
        """Fast track with no tests skips verification."""
        from zen_mode import core
        from zen_mode.config import WORK_DIR_NAME

        project_root = tmp_path
        work_dir = project_root / WORK_DIR_NAME
        work_dir.mkdir(parents=True)

        task_file = project_root / "task.md"
        task_file.write_text("# Test task")

        monkeypatch.setattr('zen_mode.core.PROJECT_ROOT', project_root)
        monkeypatch.setattr('zen_mode.config.PROJECT_ROOT', project_root)

        def scout_side_effect(ctx):
            ctx.scout_file.write_text("""
<TRIAGE>
COMPLEXITY: LOW
CONFIDENCE: 0.95
FAST_TRACK: YES
</TRIAGE>

<MICRO_SPEC>
TARGET_FILE: src/main.py
OPERATION: UPDATE
INSTRUCTION: Add comment
</MICRO_SPEC>
""")
        mock_scout.side_effect = scout_side_effect

        mock_has_tests.return_value = False  # No tests
        mock_run_claude.return_value = "Summary"

        core.run(str(task_file))

        # Verify should NOT be called (no tests)
        mock_verify.assert_not_called()
        # Planner should NOT be called (fast track succeeds)
        mock_plan.assert_not_called()


class TestRunNormalFlow:
    """Tests for normal (non-fast-track) flow."""

    @patch('zen_mode.core.phase_scout_ctx')
    @patch('zen_mode.core.phase_plan_ctx')
    @patch('zen_mode.core.phase_implement_ctx')
    @patch('zen_mode.core.verify_and_fix')
    @patch('zen_mode.core.project_has_tests')
    @patch('zen_mode.core.phase_judge_ctx')
    @patch('zen_mode.core.should_skip_judge_ctx')
    @patch('zen_mode.core.run_claude')
    def test_normal_flow_calls_all_phases(
        self,
        mock_run_claude,
        mock_skip_judge,
        mock_judge,
        mock_has_tests,
        mock_verify,
        mock_implement,
        mock_plan,
        mock_scout,
        tmp_path,
        monkeypatch
    ):
        """Normal flow calls scout, plan, implement, verify, judge."""
        from zen_mode import core
        from zen_mode.config import WORK_DIR_NAME

        project_root = tmp_path
        work_dir = project_root / WORK_DIR_NAME
        work_dir.mkdir(parents=True)

        task_file = project_root / "task.md"
        task_file.write_text("# Test task")

        monkeypatch.setattr('zen_mode.core.PROJECT_ROOT', project_root)
        monkeypatch.setattr('zen_mode.config.PROJECT_ROOT', project_root)

        def scout_side_effect(ctx):
            ctx.scout_file.write_text("<TRIAGE>\nFAST_TRACK: NO\n</TRIAGE>")
        mock_scout.side_effect = scout_side_effect

        def plan_side_effect(ctx):
            ctx.plan_file.write_text("## Step 1: Do stuff\n")
        mock_plan.side_effect = plan_side_effect

        mock_has_tests.return_value = True
        mock_verify.return_value = True
        mock_skip_judge.return_value = False  # Should call judge
        mock_run_claude.return_value = "Summary"

        core.run(str(task_file))

        # All phases should be called
        mock_scout.assert_called_once()
        mock_plan.assert_called_once()
        mock_implement.assert_called_once()
        mock_verify.assert_called_once()
        mock_judge.assert_called_once()

    @patch('zen_mode.core.phase_scout_ctx')
    @patch('zen_mode.core.phase_plan_ctx')
    @patch('zen_mode.core.phase_implement_ctx')
    @patch('zen_mode.core.verify_and_fix')
    @patch('zen_mode.core.project_has_tests')
    @patch('zen_mode.core.should_skip_judge_ctx')
    @patch('zen_mode.core.run_claude')
    def test_verify_failure_raises_error(
        self,
        mock_run_claude,
        mock_skip_judge,
        mock_has_tests,
        mock_verify,
        mock_implement,
        mock_plan,
        mock_scout,
        tmp_path,
        monkeypatch
    ):
        """Verification failure raises VerifyError."""
        from zen_mode import core
        from zen_mode.config import WORK_DIR_NAME
        from zen_mode.exceptions import VerifyError

        project_root = tmp_path
        work_dir = project_root / WORK_DIR_NAME
        work_dir.mkdir(parents=True)

        task_file = project_root / "task.md"
        task_file.write_text("# Test task")

        monkeypatch.setattr('zen_mode.core.PROJECT_ROOT', project_root)
        monkeypatch.setattr('zen_mode.config.PROJECT_ROOT', project_root)

        def scout_side_effect(ctx):
            ctx.scout_file.write_text("<TRIAGE>\nFAST_TRACK: NO\n</TRIAGE>")
        mock_scout.side_effect = scout_side_effect

        def plan_side_effect(ctx):
            ctx.plan_file.write_text("## Step 1: Do stuff\n")
        mock_plan.side_effect = plan_side_effect

        mock_has_tests.return_value = True
        mock_verify.return_value = False  # Verification fails
        mock_skip_judge.return_value = True

        with pytest.raises(VerifyError):
            core.run(str(task_file))


class TestRunErrorHandling:
    """Tests for error handling in run()."""

    def test_config_error_for_missing_task_file(self, tmp_path, monkeypatch):
        """Raises ConfigError for missing task file."""
        from zen_mode import core
        from zen_mode.exceptions import ConfigError

        monkeypatch.setattr('zen_mode.core.PROJECT_ROOT', tmp_path)
        monkeypatch.setattr('zen_mode.config.PROJECT_ROOT', tmp_path)

        with pytest.raises(ConfigError, match="not found"):
            core.run(str(tmp_path / "nonexistent.md"))

    def test_config_error_for_task_outside_project(self, tmp_path, monkeypatch):
        """Raises ConfigError for task file outside project."""
        from zen_mode import core
        from zen_mode.exceptions import ConfigError
        import tempfile

        project_root = tmp_path / "project"
        project_root.mkdir()
        monkeypatch.setattr('zen_mode.core.PROJECT_ROOT', project_root)
        monkeypatch.setattr('zen_mode.config.PROJECT_ROOT', project_root)

        # Create task file outside project
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("# Task")
            outside_task = f.name

        try:
            with pytest.raises(ConfigError, match="within project"):
                core.run(outside_task)
        finally:
            Path(outside_task).unlink()

    @patch('zen_mode.core.phase_scout_ctx')
    @patch('zen_mode.core.phase_plan_ctx')
    @patch('zen_mode.core.phase_implement_ctx')
    @patch('zen_mode.core.project_has_tests')
    @patch('zen_mode.core.should_skip_judge_ctx')
    @patch('zen_mode.core.run_claude')
    def test_keyboard_interrupt_logs_and_reraises(
        self,
        mock_run_claude,
        mock_skip_judge,
        mock_has_tests,
        mock_implement,
        mock_plan,
        mock_scout,
        tmp_path,
        monkeypatch
    ):
        """KeyboardInterrupt is logged and re-raised."""
        from zen_mode import core
        from zen_mode.config import WORK_DIR_NAME

        project_root = tmp_path
        work_dir = project_root / WORK_DIR_NAME
        work_dir.mkdir(parents=True)

        task_file = project_root / "task.md"
        task_file.write_text("# Test task")

        monkeypatch.setattr('zen_mode.core.PROJECT_ROOT', project_root)
        monkeypatch.setattr('zen_mode.config.PROJECT_ROOT', project_root)

        def scout_side_effect(ctx):
            ctx.scout_file.write_text("<TRIAGE>\nFAST_TRACK: NO\n</TRIAGE>")
        mock_scout.side_effect = scout_side_effect

        mock_plan.side_effect = KeyboardInterrupt("User cancelled")

        with pytest.raises(KeyboardInterrupt):
            core.run(str(task_file))

        # Log should contain interrupt message
        log_file = work_dir / "log.md"
        assert log_file.exists()
        log_content = log_file.read_text()
        assert "INTERRUPTED" in log_content

    @patch('zen_mode.core.phase_scout_ctx')
    @patch('zen_mode.core.phase_plan_ctx')
    @patch('zen_mode.core.phase_implement_ctx')
    @patch('zen_mode.core.project_has_tests')
    @patch('zen_mode.core.should_skip_judge_ctx')
    @patch('zen_mode.core.run_claude')
    def test_verify_timeout_raises_zen_error(
        self,
        mock_run_claude,
        mock_skip_judge,
        mock_has_tests,
        mock_implement,
        mock_plan,
        mock_scout,
        tmp_path,
        monkeypatch
    ):
        """VerifyTimeout is converted to ZenError."""
        from zen_mode import core
        from zen_mode.config import WORK_DIR_NAME
        from zen_mode.verify import VerifyTimeout
        from zen_mode.exceptions import ZenError

        project_root = tmp_path
        work_dir = project_root / WORK_DIR_NAME
        work_dir.mkdir(parents=True)

        task_file = project_root / "task.md"
        task_file.write_text("# Test task")

        monkeypatch.setattr('zen_mode.core.PROJECT_ROOT', project_root)
        monkeypatch.setattr('zen_mode.config.PROJECT_ROOT', project_root)

        def scout_side_effect(ctx):
            ctx.scout_file.write_text("<TRIAGE>\nFAST_TRACK: NO\n</TRIAGE>")
        mock_scout.side_effect = scout_side_effect

        mock_plan.side_effect = VerifyTimeout("Test timed out")

        with pytest.raises(ZenError, match="Timeout"):
            core.run(str(task_file))


class TestRunScoutContext:
    """Tests for scout_context parameter."""

    @patch('zen_mode.core.phase_scout_ctx')
    @patch('zen_mode.core.phase_plan_ctx')
    @patch('zen_mode.core.phase_implement_ctx')
    @patch('zen_mode.core.project_has_tests')
    @patch('zen_mode.core.should_skip_judge_ctx')
    @patch('zen_mode.core.run_claude')
    def test_scout_context_uses_provided_file(
        self,
        mock_run_claude,
        mock_skip_judge,
        mock_has_tests,
        mock_implement,
        mock_plan,
        mock_scout,
        tmp_path,
        monkeypatch
    ):
        """scout_context parameter uses provided file instead of running scout."""
        from zen_mode import core
        from zen_mode.config import WORK_DIR_NAME

        project_root = tmp_path
        work_dir = project_root / WORK_DIR_NAME
        work_dir.mkdir(parents=True)

        task_file = project_root / "task.md"
        task_file.write_text("# Test task")

        # Create pre-computed scout file
        scout_context = project_root / "precomputed_scout.md"
        scout_context.write_text("<TRIAGE>\nFAST_TRACK: NO\n</TRIAGE>")

        monkeypatch.setattr('zen_mode.core.PROJECT_ROOT', project_root)
        monkeypatch.setattr('zen_mode.config.PROJECT_ROOT', project_root)

        def plan_side_effect(ctx):
            ctx.plan_file.write_text("## Step 1: Do stuff\n")
        mock_plan.side_effect = plan_side_effect

        mock_has_tests.return_value = False
        mock_skip_judge.return_value = True
        mock_run_claude.return_value = "Summary"

        core.run(str(task_file), scout_context=str(scout_context))

        # Scout phase should NOT be called
        mock_scout.assert_not_called()

        # Scout file should contain precomputed content
        copied_scout = work_dir / "scout.md"
        assert copied_scout.exists()
        assert "FAST_TRACK: NO" in copied_scout.read_text()

    def test_scout_context_missing_file_raises_error(self, tmp_path, monkeypatch):
        """Missing scout_context file raises ConfigError."""
        from zen_mode import core
        from zen_mode.exceptions import ConfigError

        project_root = tmp_path
        task_file = project_root / "task.md"
        task_file.write_text("# Test task")

        monkeypatch.setattr('zen_mode.core.PROJECT_ROOT', project_root)
        monkeypatch.setattr('zen_mode.config.PROJECT_ROOT', project_root)

        with pytest.raises(ConfigError, match="not found"):
            core.run(str(task_file), scout_context=str(tmp_path / "nonexistent.md"))

    def test_scout_context_outside_project_raises_error(self, tmp_path, monkeypatch):
        """Scout context outside project raises ConfigError."""
        from zen_mode import core
        from zen_mode.exceptions import ConfigError
        import tempfile

        project_root = tmp_path / "project"
        project_root.mkdir()
        task_file = project_root / "task.md"
        task_file.write_text("# Test task")

        monkeypatch.setattr('zen_mode.core.PROJECT_ROOT', project_root)
        monkeypatch.setattr('zen_mode.config.PROJECT_ROOT', project_root)

        # Create scout file outside project
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("# Scout")
            outside_scout = f.name

        try:
            with pytest.raises(ConfigError, match="within project"):
                core.run(str(task_file), scout_context=outside_scout)
        finally:
            Path(outside_scout).unlink()


class TestRunSummaryGeneration:
    """Tests for summary generation at end of run."""

    @patch('zen_mode.core.phase_scout_ctx')
    @patch('zen_mode.core.phase_plan_ctx')
    @patch('zen_mode.core.phase_implement_ctx')
    @patch('zen_mode.core.project_has_tests')
    @patch('zen_mode.core.should_skip_judge_ctx')
    @patch('zen_mode.core.run_claude')
    def test_summary_written_to_notes(
        self,
        mock_run_claude,
        mock_skip_judge,
        mock_has_tests,
        mock_implement,
        mock_plan,
        mock_scout,
        tmp_path,
        monkeypatch
    ):
        """Summary from Claude is written to notes file."""
        from zen_mode import core
        from zen_mode.config import WORK_DIR_NAME

        project_root = tmp_path
        work_dir = project_root / WORK_DIR_NAME
        work_dir.mkdir(parents=True)

        task_file = project_root / "task.md"
        task_file.write_text("# Test task")

        monkeypatch.setattr('zen_mode.core.PROJECT_ROOT', project_root)
        monkeypatch.setattr('zen_mode.config.PROJECT_ROOT', project_root)

        def scout_side_effect(ctx):
            ctx.scout_file.write_text("<TRIAGE>\nFAST_TRACK: NO\n</TRIAGE>")
        mock_scout.side_effect = scout_side_effect

        def plan_side_effect(ctx):
            ctx.plan_file.write_text("## Step 1: Do stuff\n")
        mock_plan.side_effect = plan_side_effect

        mock_has_tests.return_value = False
        mock_skip_judge.return_value = True
        mock_run_claude.return_value = "- Added feature X\n- Fixed bug Y"

        core.run(str(task_file))

        notes_file = work_dir / "final_notes.md"
        content = notes_file.read_text()
        assert "Added feature X" in content
        assert "Fixed bug Y" in content

    @patch('zen_mode.core.phase_scout_ctx')
    @patch('zen_mode.core.phase_plan_ctx')
    @patch('zen_mode.core.phase_implement_ctx')
    @patch('zen_mode.core.project_has_tests')
    @patch('zen_mode.core.should_skip_judge_ctx')
    @patch('zen_mode.core.run_claude')
    def test_summary_timeout_skips_gracefully(
        self,
        mock_run_claude,
        mock_skip_judge,
        mock_has_tests,
        mock_implement,
        mock_plan,
        mock_scout,
        tmp_path,
        monkeypatch
    ):
        """Summary timeout is handled gracefully."""
        from zen_mode import core
        from zen_mode.config import WORK_DIR_NAME

        project_root = tmp_path
        work_dir = project_root / WORK_DIR_NAME
        work_dir.mkdir(parents=True)

        task_file = project_root / "task.md"
        task_file.write_text("# Test task")

        monkeypatch.setattr('zen_mode.core.PROJECT_ROOT', project_root)
        monkeypatch.setattr('zen_mode.config.PROJECT_ROOT', project_root)

        def scout_side_effect(ctx):
            ctx.scout_file.write_text("<TRIAGE>\nFAST_TRACK: NO\n</TRIAGE>")
        mock_scout.side_effect = scout_side_effect

        def plan_side_effect(ctx):
            ctx.plan_file.write_text("## Step 1: Do stuff\n")
        mock_plan.side_effect = plan_side_effect

        mock_has_tests.return_value = False
        mock_skip_judge.return_value = True
        mock_run_claude.return_value = None  # Timeout

        # Should not raise
        core.run(str(task_file))

        # Log should mention skipped summary
        log_file = work_dir / "log.md"
        log_content = log_file.read_text()
        assert "SUMMARY" in log_content and "Skipped" in log_content

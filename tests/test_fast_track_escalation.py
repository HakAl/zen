"""
Tests for fast track escalation behavior.

When fast track fails verify, it must escalate properly:
1. Clear synthetic plan (so planner runs fresh)
2. Clear completion markers (so implement runs)
3. Planner creates new plan
4. Implement executes new plan

Bug scenario this prevents:
- Fast track runs → step completes
- Verify fails
- Escalates but plan.md cached → planner skips
- Implement sees step complete → skips
- Goes to verify again (loop)
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestFastTrackEscalation:
    """Test escalation clears state properly."""

    def _setup_fast_track_scout(self, work_dir: Path) -> str:
        """Create scout output that triggers fast track."""
        return """
## Targeted Files
- src/main.py: update function

<TRIAGE>
COMPLEXITY: LOW
CONFIDENCE: 0.95
FAST_TRACK: YES
</TRIAGE>

<MICRO_SPEC>
TARGET_FILE: src/main.py
OPERATION: UPDATE
INSTRUCTION: Add a comment at line 10
</MICRO_SPEC>
"""

    @patch('zen_mode.core.phase_scout_ctx')
    @patch('zen_mode.core.phase_plan_ctx')
    @patch('zen_mode.core.phase_implement_ctx')
    @patch('zen_mode.core.verify_and_fix')
    @patch('zen_mode.core.should_skip_judge_ctx')
    @patch('zen_mode.core.run_claude')
    def test_escalation_clears_plan_on_verify_failure(
        self,
        mock_run_claude,
        mock_skip_judge,
        mock_verify,
        mock_implement,
        mock_plan,
        mock_scout,
        tmp_path,
        monkeypatch
    ):
        """When fast track fails verify, plan.md should be deleted before planner runs."""
        from zen_mode import core
        from zen_mode.config import WORK_DIR_NAME

        # Setup paths
        project_root = tmp_path
        work_dir = project_root / WORK_DIR_NAME
        work_dir.mkdir()

        # Create task file
        task_file = project_root / "task.md"
        task_file.write_text("# Test task")

        # Monkeypatch config
        monkeypatch.setattr('zen_mode.core.PROJECT_ROOT', project_root)
        monkeypatch.setattr('zen_mode.core.WORK_DIR', work_dir)
        monkeypatch.setattr('zen_mode.config.PROJECT_ROOT', project_root)
        monkeypatch.setattr('zen_mode.config.WORK_DIR', work_dir)

        # Setup scout to return fast-track output
        def scout_side_effect(ctx):
            scout_file = ctx.work_dir / "scout.md"
            scout_file.write_text(self._setup_fast_track_scout(work_dir))
        mock_scout.side_effect = scout_side_effect

        # Track if plan file existed when planner was called
        plan_existed_when_planner_called = []

        def plan_side_effect(ctx):
            plan_existed_when_planner_called.append(ctx.plan_file.exists())
            ctx.plan_file.write_text("## Step 1: Real plan step\n")
        mock_plan.side_effect = plan_side_effect

        # First verify fails (fast track), second succeeds (after planner)
        mock_verify.side_effect = [False, True]
        mock_skip_judge.return_value = True
        mock_run_claude.return_value = "Summary done"

        # Run
        core.run(str(task_file))

        # Planner should have been called with NO existing plan
        assert len(plan_existed_when_planner_called) == 1
        assert plan_existed_when_planner_called[0] is False, \
            "Plan file should be deleted before planner runs on escalation"

    @patch('zen_mode.core.phase_scout_ctx')
    @patch('zen_mode.core.phase_plan_ctx')
    @patch('zen_mode.core.phase_implement_ctx')
    @patch('zen_mode.core.verify_and_fix')
    @patch('zen_mode.core.should_skip_judge_ctx')
    @patch('zen_mode.core.run_claude')
    def test_escalation_clears_completion_markers(
        self,
        mock_run_claude,
        mock_skip_judge,
        mock_verify,
        mock_implement,
        mock_plan,
        mock_scout,
        tmp_path,
        monkeypatch
    ):
        """When fast track fails, completion markers should be cleared."""
        from zen_mode import core
        from zen_mode.config import WORK_DIR_NAME

        # Setup paths
        project_root = tmp_path
        work_dir = project_root / WORK_DIR_NAME
        work_dir.mkdir()

        task_file = project_root / "task.md"
        task_file.write_text("# Test task")

        monkeypatch.setattr('zen_mode.core.PROJECT_ROOT', project_root)
        monkeypatch.setattr('zen_mode.core.WORK_DIR', work_dir)
        monkeypatch.setattr('zen_mode.config.PROJECT_ROOT', project_root)
        monkeypatch.setattr('zen_mode.config.WORK_DIR', work_dir)

        def scout_side_effect(ctx):
            scout_file = ctx.work_dir / "scout.md"
            scout_file.write_text(self._setup_fast_track_scout(work_dir))
        mock_scout.side_effect = scout_side_effect

        # Track log content when implement is called
        log_content_when_implement_called = []

        def implement_side_effect(ctx, allowed_files=None):
            log_file = ctx.work_dir / "log.md"
            if log_file.exists():
                log_content_when_implement_called.append(log_file.read_text())
            else:
                log_content_when_implement_called.append("")

            # Simulate completing a step
            from zen_mode.files import log
            log("[COMPLETE] Step 1", log_file, ctx.work_dir)

        mock_implement.side_effect = implement_side_effect

        def plan_side_effect(ctx):
            ctx.plan_file.write_text("## Step 1: New plan step\n")
        mock_plan.side_effect = plan_side_effect

        mock_verify.side_effect = [False, True]
        mock_skip_judge.return_value = True
        mock_run_claude.return_value = "Summary"

        core.run(str(task_file))

        # Should have been called twice: once for fast track, once after escalation
        assert len(log_content_when_implement_called) == 2

        # Second call should NOT have completion markers from first call
        second_call_log = log_content_when_implement_called[1]
        assert "[COMPLETE] Step" not in second_call_log, \
            "Completion markers should be cleared on escalation"


class TestFastTrackNoEscalation:
    """Test that successful fast track doesn't trigger planner."""

    @patch('zen_mode.core.phase_scout_ctx')
    @patch('zen_mode.core.phase_plan_ctx')
    @patch('zen_mode.core.phase_implement_ctx')
    @patch('zen_mode.core.verify_and_fix')
    @patch('zen_mode.core.run_claude')
    def test_successful_fast_track_skips_planner(
        self,
        mock_run_claude,
        mock_verify,
        mock_implement,
        mock_plan,
        mock_scout,
        tmp_path,
        monkeypatch
    ):
        """When fast track succeeds, planner should NOT be called."""
        from zen_mode import core
        from zen_mode.config import WORK_DIR_NAME

        project_root = tmp_path
        work_dir = project_root / WORK_DIR_NAME
        work_dir.mkdir()

        task_file = project_root / "task.md"
        task_file.write_text("# Test task")

        monkeypatch.setattr('zen_mode.core.PROJECT_ROOT', project_root)
        monkeypatch.setattr('zen_mode.core.WORK_DIR', work_dir)
        monkeypatch.setattr('zen_mode.config.PROJECT_ROOT', project_root)
        monkeypatch.setattr('zen_mode.config.WORK_DIR', work_dir)

        def scout_side_effect(ctx):
            scout_file = ctx.work_dir / "scout.md"
            scout_file.write_text("""
<TRIAGE>
COMPLEXITY: LOW
CONFIDENCE: 0.95
FAST_TRACK: YES
</TRIAGE>

<MICRO_SPEC>
TARGET_FILE: x.py
OPERATION: UPDATE
INSTRUCTION: Add comment
</MICRO_SPEC>
""")
        mock_scout.side_effect = scout_side_effect

        mock_verify.return_value = True  # Fast track succeeds
        mock_run_claude.return_value = "Summary"

        core.run(str(task_file))

        # Planner should NOT have been called
        mock_plan.assert_not_called()

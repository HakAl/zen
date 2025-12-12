"""
Tests for Snapshot integration in phase_implement (Item 5 from implementation_plan.md).

The snapshot system should:
1. Create a git stash snapshot before each step mutation
2. Drop the snapshot after a successful step (prevent stash growth)
3. Restore the snapshot on step failure
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

# Import from package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestSnapshotIntegration:
    """Tests for snapshot create/drop/restore integration in phase_implement."""

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
    def test_creates_snapshot_before_step(
        self, mock_backup, mock_log, mock_claude, mock_linter,
        mock_restore, mock_drop, mock_create, mock_zen_env
    ):
        """Should create a snapshot before executing each step."""
        from zen_mode.core import phase_implement

        with patch('zen_mode.core.PLAN_FILE', mock_zen_env["plan_file"]):
            with patch('zen_mode.core.LOG_FILE', mock_zen_env["log_file"]):
                with patch('zen_mode.core.WORK_DIR', mock_zen_env["work_dir"]):
                    with patch('zen_mode.core.get_completed_steps', return_value=set()):
                        mock_create.return_value = "zen-snapshot-step_1-12345"
                        mock_claude.return_value = "STEP_COMPLETE"
                        mock_linter.return_value = (True, "")

                        phase_implement()

                        # Should have called create_snapshot with step label
                        mock_create.assert_called_once()
                        call_args = mock_create.call_args[0][0]
                        assert "step_1" in call_args

    @patch('zen_mode.core.create_snapshot')
    @patch('zen_mode.core.drop_snapshot')
    @patch('zen_mode.core.restore_snapshot')
    @patch('zen_mode.core.run_linter')
    @patch('zen_mode.core.run_claude')
    @patch('zen_mode.core.log')
    @patch('zen_mode.core.backup_scout_files')
    def test_drops_snapshot_on_success(
        self, mock_backup, mock_log, mock_claude, mock_linter,
        mock_restore, mock_drop, mock_create, mock_zen_env
    ):
        """Should drop the snapshot after successful step completion."""
        from zen_mode.core import phase_implement

        with patch('zen_mode.core.PLAN_FILE', mock_zen_env["plan_file"]):
            with patch('zen_mode.core.LOG_FILE', mock_zen_env["log_file"]):
                with patch('zen_mode.core.WORK_DIR', mock_zen_env["work_dir"]):
                    with patch('zen_mode.core.get_completed_steps', return_value=set()):
                        snapshot_ref = "zen-snapshot-step_1-12345"
                        mock_create.return_value = snapshot_ref
                        mock_claude.return_value = "STEP_COMPLETE"
                        mock_linter.return_value = (True, "")

                        phase_implement()

                        # Should have called drop_snapshot with the ref
                        mock_drop.assert_called_once_with(snapshot_ref)

    @patch('zen_mode.core.create_snapshot')
    @patch('zen_mode.core.drop_snapshot')
    @patch('zen_mode.core.restore_snapshot')
    @patch('zen_mode.core.run_linter')
    @patch('zen_mode.core.run_claude')
    @patch('zen_mode.core.log')
    @patch('zen_mode.core.backup_scout_files')
    @patch('zen_mode.core.BACKUP_DIR')
    def test_restores_snapshot_on_failure(
        self, mock_backup_dir, mock_backup, mock_log, mock_claude, mock_linter,
        mock_restore, mock_drop, mock_create, mock_zen_env
    ):
        """Should restore the snapshot when step fails after all retries."""
        from zen_mode.core import phase_implement, MAX_RETRIES

        with patch('zen_mode.core.PLAN_FILE', mock_zen_env["plan_file"]):
            with patch('zen_mode.core.LOG_FILE', mock_zen_env["log_file"]):
                with patch('zen_mode.core.WORK_DIR', mock_zen_env["work_dir"]):
                    with patch('zen_mode.core.get_completed_steps', return_value=set()):
                        snapshot_ref = "zen-snapshot-step_1-12345"
                        mock_create.return_value = snapshot_ref
                        mock_backup_dir.exists.return_value = False

                        # All attempts fail (never return STEP_COMPLETE)
                        mock_claude.return_value = "I tried but failed."

                        with pytest.raises(SystemExit):
                            phase_implement()

                        # Should have called restore_snapshot
                        mock_restore.assert_called_once_with(snapshot_ref)
                        # Should NOT have called drop_snapshot
                        mock_drop.assert_not_called()

    @patch('zen_mode.core.create_snapshot')
    @patch('zen_mode.core.drop_snapshot')
    @patch('zen_mode.core.restore_snapshot')
    @patch('zen_mode.core.run_linter')
    @patch('zen_mode.core.run_claude')
    @patch('zen_mode.core.log')
    @patch('zen_mode.core.backup_scout_files')
    def test_no_drop_if_no_snapshot_created(
        self, mock_backup, mock_log, mock_claude, mock_linter,
        mock_restore, mock_drop, mock_create, mock_zen_env
    ):
        """Should not call drop_snapshot if create_snapshot returned empty."""
        from zen_mode.core import phase_implement

        with patch('zen_mode.core.PLAN_FILE', mock_zen_env["plan_file"]):
            with patch('zen_mode.core.LOG_FILE', mock_zen_env["log_file"]):
                with patch('zen_mode.core.WORK_DIR', mock_zen_env["work_dir"]):
                    with patch('zen_mode.core.get_completed_steps', return_value=set()):
                        # Snapshot creation returns empty (e.g., not a git repo)
                        mock_create.return_value = ""
                        mock_claude.return_value = "STEP_COMPLETE"
                        mock_linter.return_value = (True, "")

                        phase_implement()

                        # drop_snapshot should not be called with empty ref
                        # (the function checks for truthiness)
                        mock_drop.assert_not_called()

    @patch('zen_mode.core.create_snapshot')
    @patch('zen_mode.core.drop_snapshot')
    @patch('zen_mode.core.restore_snapshot')
    @patch('zen_mode.core.run_linter')
    @patch('zen_mode.core.run_claude')
    @patch('zen_mode.core.log')
    @patch('zen_mode.core.backup_scout_files')
    def test_multiple_steps_each_get_snapshot(
        self, mock_backup, mock_log, mock_claude, mock_linter,
        mock_restore, mock_drop, mock_create, mock_zen_env
    ):
        """Each step should get its own snapshot."""
        from zen_mode.core import phase_implement

        # Plan with multiple steps
        mock_zen_env["plan_file"].write_text(
            "## Step 1: First thing\n## Step 2: Second thing\n"
        )

        with patch('zen_mode.core.PLAN_FILE', mock_zen_env["plan_file"]):
            with patch('zen_mode.core.LOG_FILE', mock_zen_env["log_file"]):
                with patch('zen_mode.core.WORK_DIR', mock_zen_env["work_dir"]):
                    with patch('zen_mode.core.get_completed_steps', return_value=set()):
                        # Return different snapshot refs for each step
                        mock_create.side_effect = [
                            "zen-snapshot-step_1-111",
                            "zen-snapshot-step_2-222"
                        ]
                        mock_claude.return_value = "STEP_COMPLETE"
                        mock_linter.return_value = (True, "")

                        phase_implement()

                        # Should have created 2 snapshots
                        assert mock_create.call_count == 2
                        create_calls = mock_create.call_args_list
                        assert "step_1" in create_calls[0][0][0]
                        assert "step_2" in create_calls[1][0][0]

                        # Should have dropped 2 snapshots
                        assert mock_drop.call_count == 2
                        drop_calls = mock_drop.call_args_list
                        assert drop_calls[0][0][0] == "zen-snapshot-step_1-111"
                        assert drop_calls[1][0][0] == "zen-snapshot-step_2-222"

    @patch('zen_mode.core.create_snapshot')
    @patch('zen_mode.core.drop_snapshot')
    @patch('zen_mode.core.restore_snapshot')
    @patch('zen_mode.core.run_linter')
    @patch('zen_mode.core.run_claude')
    @patch('zen_mode.core.log')
    @patch('zen_mode.core.backup_scout_files')
    def test_snapshot_drop_on_lint_pass_after_retries(
        self, mock_backup, mock_log, mock_claude, mock_linter,
        mock_restore, mock_drop, mock_create, mock_zen_env
    ):
        """Snapshot should be dropped when lint finally passes after retries."""
        from zen_mode.core import phase_implement

        with patch('zen_mode.core.PLAN_FILE', mock_zen_env["plan_file"]):
            with patch('zen_mode.core.LOG_FILE', mock_zen_env["log_file"]):
                with patch('zen_mode.core.WORK_DIR', mock_zen_env["work_dir"]):
                    with patch('zen_mode.core.get_completed_steps', return_value=set()):
                        snapshot_ref = "zen-snapshot-step_1-12345"
                        mock_create.return_value = snapshot_ref
                        mock_claude.return_value = "STEP_COMPLETE"

                        # Lint fails first, then passes
                        mock_linter.side_effect = [
                            (False, "Error on first try"),
                            (True, ""),
                        ]

                        phase_implement()

                        # Snapshot should still be dropped on eventual success
                        mock_drop.assert_called_once_with(snapshot_ref)

    @patch('zen_mode.core.create_snapshot')
    @patch('zen_mode.core.drop_snapshot')
    @patch('zen_mode.core.restore_snapshot')
    @patch('zen_mode.core.run_linter')
    @patch('zen_mode.core.run_claude')
    @patch('zen_mode.core.log')
    @patch('zen_mode.core.backup_scout_files')
    def test_skips_completed_steps_no_snapshot(
        self, mock_backup, mock_log, mock_claude, mock_linter,
        mock_restore, mock_drop, mock_create, mock_zen_env
    ):
        """Should not create snapshot for already-completed steps."""
        from zen_mode.core import phase_implement

        # Plan with 2 steps
        mock_zen_env["plan_file"].write_text(
            "## Step 1: First thing\n## Step 2: Second thing\n"
        )

        with patch('zen_mode.core.PLAN_FILE', mock_zen_env["plan_file"]):
            with patch('zen_mode.core.LOG_FILE', mock_zen_env["log_file"]):
                with patch('zen_mode.core.WORK_DIR', mock_zen_env["work_dir"]):
                    # Step 1 is already completed
                    with patch('zen_mode.core.get_completed_steps', return_value={1}):
                        mock_create.return_value = "zen-snapshot-step_2-222"
                        mock_claude.return_value = "STEP_COMPLETE"
                        mock_linter.return_value = (True, "")

                        phase_implement()

                        # Should only create snapshot for step 2
                        assert mock_create.call_count == 1
                        assert "step_2" in mock_create.call_args[0][0]


class TestSnapshotEdgeCases:
    """Edge case tests for snapshot behavior."""

    @pytest.fixture
    def mock_zen_env(self, tmp_path):
        work_dir = tmp_path / ".zen"
        work_dir.mkdir()
        plan_file = work_dir / "plan.md"
        plan_file.write_text("## Step 1: Do something\n")
        log_file = work_dir / "log.md"
        log_file.write_text("")
        return {"work_dir": work_dir, "plan_file": plan_file, "log_file": log_file}

    @patch('zen_mode.core.create_snapshot')
    @patch('zen_mode.core.drop_snapshot')
    @patch('zen_mode.core.restore_snapshot')
    @patch('zen_mode.core.run_linter')
    @patch('zen_mode.core.run_claude')
    @patch('zen_mode.core.log')
    @patch('zen_mode.core.backup_scout_files')
    @patch('zen_mode.core.BACKUP_DIR')
    def test_restore_not_called_if_snapshot_empty(
        self, mock_backup_dir, mock_backup, mock_log, mock_claude, mock_linter,
        mock_restore, mock_drop, mock_create, mock_zen_env
    ):
        """Should not call restore_snapshot if no snapshot was created."""
        from zen_mode.core import phase_implement

        with patch('zen_mode.core.PLAN_FILE', mock_zen_env["plan_file"]):
            with patch('zen_mode.core.LOG_FILE', mock_zen_env["log_file"]):
                with patch('zen_mode.core.WORK_DIR', mock_zen_env["work_dir"]):
                    with patch('zen_mode.core.get_completed_steps', return_value=set()):
                        # No snapshot created (not a git repo)
                        mock_create.return_value = ""
                        mock_backup_dir.exists.return_value = False
                        mock_claude.return_value = "I failed."  # Never completes

                        with pytest.raises(SystemExit):
                            phase_implement()

                        # restore should not be called with empty ref
                        mock_restore.assert_not_called()

    @patch('zen_mode.core.create_snapshot')
    @patch('zen_mode.core.drop_snapshot')
    @patch('zen_mode.core.restore_snapshot')
    @patch('zen_mode.core.run_linter')
    @patch('zen_mode.core.run_claude')
    @patch('zen_mode.core.log')
    @patch('zen_mode.core.backup_scout_files')
    def test_snapshot_created_before_claude_called(
        self, mock_backup, mock_log, mock_claude, mock_linter,
        mock_restore, mock_drop, mock_create, mock_zen_env
    ):
        """Snapshot should be created BEFORE run_claude is called."""
        from zen_mode.core import phase_implement

        with patch('zen_mode.core.PLAN_FILE', mock_zen_env["plan_file"]):
            with patch('zen_mode.core.LOG_FILE', mock_zen_env["log_file"]):
                with patch('zen_mode.core.WORK_DIR', mock_zen_env["work_dir"]):
                    with patch('zen_mode.core.get_completed_steps', return_value=set()):
                        call_order = []

                        def track_create(label):
                            call_order.append(('create_snapshot', label))
                            return "snapshot-ref"

                        def track_claude(prompt, model=None, timeout=None):
                            call_order.append(('run_claude', None))
                            return "STEP_COMPLETE"

                        mock_create.side_effect = track_create
                        mock_claude.side_effect = track_claude
                        mock_linter.return_value = (True, "")

                        phase_implement()

                        # create_snapshot should come before run_claude
                        create_idx = next(i for i, (name, _) in enumerate(call_order) if name == 'create_snapshot')
                        claude_idx = next(i for i, (name, _) in enumerate(call_order) if name == 'run_claude')
                        assert create_idx < claude_idx, "Snapshot must be created before Claude is called"

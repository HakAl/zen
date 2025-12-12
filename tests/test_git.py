"""
Git-related tests for zen.py and zen_lint.py.

=============================================================================
                            !! CRITICAL WARNING !!
=============================================================================

ALL GIT OPERATIONS IN THIS FILE MUST BE MOCKED.

NEVER use real subprocess calls to git. Real git operations can:
- Stash/lose user's working changes
- Delete untracked files (git clean -fd)
- Modify the repository state
- Cause data loss

ALWAYS use @patch('subprocess.run') or @patch('module.subprocess.run') and
return Mock objects for any git command.

Example of CORRECT mocking:
    @patch('zen_lint.subprocess.run')
    def test_something(self, mock_run):
        mock_run.return_value = Mock(returncode=0, stdout="file.py")
        # ... test code ...

Example of WRONG approach (DO NOT DO THIS):
    def test_something(self, tmp_path):
        subprocess.run(["git", "init"], ...)  # WRONG! Real git call!

=============================================================================
"""
import sys
from pathlib import Path
from unittest.mock import patch, Mock, MagicMock

import pytest

# Scripts are in scripts/ directory
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
# Package is in src/ directory
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _reload_zen_lint():
    """Reload zen_lint module."""
    if 'zen_lint' in sys.modules:
        del sys.modules['zen_lint']
    import zen_lint
    return zen_lint


# =============================================================================
# Tests for zen_lint.get_git_changes()
# =============================================================================

class TestGetGitChanges:
    """Tests for get_git_changes() function in zen_lint.

    WARNING: All tests must mock subprocess.run. Never make real git calls.
    """

    @patch('zen_lint.subprocess.run')
    def test_get_git_changes_normal_repo(self, mock_run):
        """Normal repo with tracked changes returns file list."""
        zen_lint = _reload_zen_lint()

        def mock_side_effect(cmd, **kwargs):
            if "rev-parse" in cmd and "--git-dir" in cmd:
                return Mock(returncode=0, stdout=".git")
            if "rev-parse" in cmd and "HEAD" in cmd:
                return Mock(returncode=0, stdout="abc123")
            if "diff" in cmd and "--name-only" in cmd:
                return Mock(returncode=0, stdout="src/file.py\ntests/test.py\n")
            if "ls-files" in cmd:
                return Mock(returncode=0, stdout="")
            return Mock(returncode=0, stdout="")

        mock_run.side_effect = mock_side_effect

        result = zen_lint.get_git_changes()

        assert "src/file.py" in result
        assert "tests/test.py" in result

    @patch('zen_lint.subprocess.run')
    def test_get_git_changes_handles_no_head(self, mock_run):
        """BUG #9: get_git_changes should handle repos with no commits.

        WARNING: This test MUST mock subprocess.run. Previously this test
        used real git calls which caused data loss.

        When HEAD doesn't exist (fresh repo with staged but uncommitted files),
        the function should fall back to git diff --cached.
        """
        zen_lint = _reload_zen_lint()

        def mock_no_head_repo(cmd, **kwargs):
            # git rev-parse --git-dir succeeds (is a repo)
            if "rev-parse" in cmd and "--git-dir" in cmd:
                return Mock(returncode=0, stdout=".git")
            # git rev-parse HEAD fails (no commits yet)
            if "rev-parse" in cmd and "HEAD" in cmd:
                return Mock(returncode=128, stderr="fatal: bad revision 'HEAD'")
            # git diff HEAD fails
            if "diff" in cmd and "HEAD" in cmd and "--cached" not in cmd:
                return Mock(returncode=128, stderr="fatal: bad revision 'HEAD'")
            # git diff --cached works (shows staged files)
            if "diff" in cmd and "--cached" in cmd:
                return Mock(returncode=0, stdout="staged.py\n")
            # git ls-files --others works (untracked files)
            if "ls-files" in cmd:
                return Mock(returncode=0, stdout="")
            return Mock(returncode=0, stdout="")

        mock_run.side_effect = mock_no_head_repo

        result = zen_lint.get_git_changes()

        # Should find the staged file even without HEAD
        assert "staged.py" in result, (
            f"BUG: get_git_changes missed staged file in repo with no commits. Got: {result}"
        )

    @patch('zen_lint.subprocess.run')
    def test_get_git_changes_not_a_repo(self, mock_run):
        """Not in a git repo returns empty list."""
        zen_lint = _reload_zen_lint()

        mock_run.return_value = Mock(returncode=128, stderr="fatal: not a git repository")

        result = zen_lint.get_git_changes()

        # Returns empty list when not in a git repo
        assert result == [] or result == ""

    @patch('zen_lint.subprocess.run')
    def test_get_git_changes_with_untracked(self, mock_run):
        """Untracked files should be included."""
        zen_lint = _reload_zen_lint()

        def mock_side_effect(cmd, **kwargs):
            if "rev-parse" in cmd and "--git-dir" in cmd:
                return Mock(returncode=0, stdout=".git")
            if "rev-parse" in cmd and "HEAD" in cmd:
                return Mock(returncode=0, stdout="abc123")
            if "diff" in cmd:
                return Mock(returncode=0, stdout="")
            if "ls-files" in cmd:
                return Mock(returncode=0, stdout="new_untracked.py\n")
            return Mock(returncode=0, stdout="")

        mock_run.side_effect = mock_side_effect

        result = zen_lint.get_git_changes()

        assert "new_untracked.py" in result


# =============================================================================
# Tests for get_changed_filenames() in zen_mode.core
# =============================================================================

class TestGetChangedFilenames:
    """Test extraction of changed file names.

    WARNING: All tests must mock subprocess.run. Never make real git calls.
    """

    def _mock_normal_repo(self, diff_output="", untracked_output=""):
        """Mock a normal git repo with commits.

        This helper creates a mock side_effect for subprocess.run that
        simulates a normal git repository with an existing HEAD commit.
        """
        def mock_run(cmd, **kwargs):
            if "rev-parse" in cmd and "--git-dir" in cmd:
                return Mock(returncode=0, stdout=".git")
            if "rev-parse" in cmd and "HEAD" in cmd:
                return Mock(returncode=0, stdout="abc123")
            if "diff" in cmd and "--name-only" in cmd:
                return Mock(returncode=0, stdout=diff_output)
            if "ls-files" in cmd:
                return Mock(returncode=0, stdout=untracked_output)
            return Mock(returncode=1, stdout="")
        return mock_run

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.BACKUP_DIR')
    def test_git_diff_success(self, mock_backup_dir, mock_run):
        """When git diff succeeds, return file list."""
        from zen_mode.core import get_changed_filenames

        mock_run.side_effect = self._mock_normal_repo(
            diff_output="src/file1.py\nsrc/file2.py\ntests/test_file.py\n"
        )

        result = get_changed_filenames()

        assert "src/file1.py" in result
        assert "src/file2.py" in result
        assert "tests/test_file.py" in result

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.BACKUP_DIR')
    def test_git_diff_empty_output(self, mock_backup_dir, mock_run):
        """When git diff returns empty, fall back to backup."""
        from zen_mode.core import get_changed_filenames

        mock_run.side_effect = self._mock_normal_repo(diff_output="", untracked_output="")
        mock_backup_dir.exists.return_value = True
        mock_backup_dir.rglob.return_value = []

        result = get_changed_filenames()

        assert result == "[No files detected]"

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.BACKUP_DIR')
    def test_git_failure_uses_backup(self, mock_backup_dir, mock_run):
        """When git fails, fall back to backup directory."""
        from zen_mode.core import get_changed_filenames

        mock_run.side_effect = Exception("git not found")

        # Mock backup directory with files
        mock_backup_dir.exists.return_value = True
        mock_file1 = MagicMock()
        mock_file1.relative_to.return_value = Path("src/core.py")
        mock_file2 = MagicMock()
        mock_file2.relative_to.return_value = Path("tests/test_core.py")
        mock_backup_dir.rglob.return_value = [mock_file1, mock_file2]

        result = get_changed_filenames()

        assert "src/core.py" in result or "src\\core.py" in result

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.BACKUP_DIR')
    def test_no_git_no_backup(self, mock_backup_dir, mock_run):
        """When both git and backup fail, return placeholder."""
        from zen_mode.core import get_changed_filenames

        mock_run.side_effect = Exception("git not found")
        mock_backup_dir.exists.return_value = False

        result = get_changed_filenames()

        assert result == "[No files detected]"


# =============================================================================
# Tests for should_skip_judge() in zen_mode.core
# =============================================================================

class TestShouldSkipJudgeGitOperations:
    """Tests for git operations in should_skip_judge().

    WARNING: All tests must mock subprocess.run. Never make real git calls.

    These tests focus on how should_skip_judge() handles various git states:
    - Normal repos with commits
    - Fresh repos without HEAD
    - Git command failures
    """

    def _mock_git_numstat(self, numstat_output, untracked_output=""):
        """Mock git subprocess calls for should_skip_judge().

        WARNING: This returns a mock side_effect function, NOT real git calls.
        """
        def mock_run(cmd, **kwargs):
            if "rev-parse" in cmd and "--git-dir" in cmd:
                return Mock(returncode=0, stdout=".git")
            if "rev-parse" in cmd and "HEAD" in cmd:
                return Mock(returncode=0, stdout="abc123")
            if "--numstat" in cmd:
                return Mock(returncode=0, stdout=numstat_output)
            elif "ls-files" in cmd:
                return Mock(returncode=0, stdout=untracked_output)
            return Mock(returncode=1, stdout="")
        return mock_run

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.log')
    def test_no_changes_skips_judge(self, mock_log, mock_run):
        """No changes detected should skip judge."""
        from zen_mode.core import should_skip_judge

        mock_run.side_effect = self._mock_git_numstat("", "")

        result = should_skip_judge()

        assert result is True
        mock_log.assert_called_with("[JUDGE] Skipping: No changes detected")

    @patch('zen_mode.core.subprocess.run')
    def test_git_failure_requires_judge(self, mock_run):
        """Git command failure should require judge (safe default)."""
        from zen_mode.core import should_skip_judge

        mock_run.return_value = Mock(returncode=1, stdout="")

        result = should_skip_judge()

        assert result is False

    @patch('zen_mode.core.subprocess.run')
    def test_git_exception_requires_judge(self, mock_run):
        """Git exception should require judge (safe default)."""
        from zen_mode.core import should_skip_judge

        mock_run.side_effect = Exception("git not found")

        result = should_skip_judge()

        assert result is False


# =============================================================================
# Tests for git edge cases (no HEAD, deletions, etc.)
# =============================================================================

class TestGitEdgeCases:
    """Tests for edge cases in git state handling.

    WARNING: All tests must mock subprocess.run. Never make real git calls.

    These tests demonstrate bugs in the current implementation when:
    - No commits exist (fresh repo with staged files)
    - Files are deleted but never committed
    - Mixed staged/unstaged states
    """

    def _mock_no_head_repo(self, staged_files="", untracked_files="", staged_numstat=""):
        """Mock a git repo with no commits (HEAD doesn't exist).

        WARNING: This returns a mock side_effect function, NOT real git calls.

        In this state:
        - git rev-parse --git-dir succeeds (is a repo)
        - git rev-parse HEAD fails (no commits)
        - git diff HEAD fails (returncode=128, fatal: bad revision 'HEAD')
        - git diff --cached works (shows staged files)
        - git diff --cached --numstat works (shows staged file stats)
        - git ls-files --others works (shows untracked files)
        """
        def mock_run(cmd, **kwargs):
            if "rev-parse" in cmd and "--git-dir" in cmd:
                return Mock(returncode=0, stdout=".git")
            if "rev-parse" in cmd and "HEAD" in cmd:
                return Mock(returncode=128, stdout="", stderr="fatal: bad revision 'HEAD'")
            if "diff" in cmd and "HEAD" in cmd:
                return Mock(returncode=128, stdout="", stderr="fatal: bad revision 'HEAD'")
            if "diff" in cmd and "--cached" in cmd and "--numstat" in cmd:
                return Mock(returncode=0, stdout=staged_numstat)
            if "diff" in cmd and "--cached" in cmd:
                return Mock(returncode=0, stdout=staged_files)
            if "ls-files" in cmd:
                return Mock(returncode=0, stdout=untracked_files)
            return Mock(returncode=1, stdout="")
        return mock_run

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.BACKUP_DIR')
    def test_get_changed_filenames_no_head_with_staged_files(self, mock_backup_dir, mock_run):
        """BUG: get_changed_filenames() returns nothing when HEAD doesn't exist.

        Scenario: Fresh repo, files are staged but no commits yet.
        Expected: Should return the staged files.
        Actual: Returns '[No files detected]' because git diff HEAD fails.
        """
        from zen_mode.core import get_changed_filenames

        mock_run.side_effect = self._mock_no_head_repo(
            staged_files="src/main.py\nsrc/utils.py\n"
        )
        mock_backup_dir.exists.return_value = False

        result = get_changed_filenames()

        assert "src/main.py" in result, f"Expected staged files, got: {result}"
        assert "src/utils.py" in result

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.log')
    def test_should_skip_judge_no_head_with_staged_files(self, mock_log, mock_run):
        """BUG: should_skip_judge() incorrectly requires judge when HEAD doesn't exist.

        Scenario: Fresh repo with only test files staged.
        Expected: Should skip judge (only test files).
        Actual: Returns False because git diff --numstat HEAD fails.
        """
        from zen_mode.core import should_skip_judge

        mock_run.side_effect = self._mock_no_head_repo(
            staged_files="tests/test_main.py\n",
            staged_numstat="50\t0\ttests/test_main.py\n"
        )

        result = should_skip_judge()

        assert result is True, "Should skip judge when only test files are staged"

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.BACKUP_DIR')
    def test_get_changed_filenames_includes_untracked_in_no_head_repo(self, mock_backup_dir, mock_run):
        """BUG: Untracked files not detected when HEAD doesn't exist."""
        from zen_mode.core import get_changed_filenames

        mock_run.side_effect = self._mock_no_head_repo(
            staged_files="",
            untracked_files="new_file.py\n"
        )
        mock_backup_dir.exists.return_value = False

        result = get_changed_filenames()

        assert "new_file.py" in result, f"Expected untracked files, got: {result}"


class TestDeletionTracking:
    """Tests for verifying file deletion tracking.

    WARNING: All tests must mock subprocess.run. Never make real git calls.

    The scout phase may identify deletion candidates, and we need
    to verify those deletions actually occurred.
    """

    def _mock_staged_deletions(self):
        """Mock a repo with staged file deletions.

        WARNING: This returns a mock side_effect function, NOT real git calls.
        """
        def mock_run(cmd, **kwargs):
            if "rev-parse" in cmd and "--git-dir" in cmd:
                return Mock(returncode=0, stdout=".git")
            if "rev-parse" in cmd and "HEAD" in cmd:
                return Mock(returncode=0, stdout="abc123")
            if "--name-only" in cmd and "HEAD" in cmd:
                return Mock(returncode=0, stdout="deleted_file.py\nmodified_file.py\n")
            if "--numstat" in cmd and "HEAD" in cmd:
                return Mock(returncode=0, stdout="0\t50\tdeleted_file.py\n10\t5\tmodified_file.py\n")
            if "ls-files" in cmd:
                return Mock(returncode=0, stdout="")
            return Mock(returncode=0, stdout="")
        return mock_run

    @patch('zen_mode.core.subprocess.run')
    def test_get_changed_filenames_shows_deleted_files(self, mock_run):
        """Verify deleted files appear in changed files list."""
        from zen_mode.core import get_changed_filenames

        mock_run.side_effect = self._mock_staged_deletions()

        result = get_changed_filenames()

        assert "deleted_file.py" in result, "Deleted files should appear in changed list"
        assert "modified_file.py" in result

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.log')
    @patch('zen_mode.core.read_file')
    @patch('zen_mode.core.parse_steps')
    def test_should_skip_judge_counts_deletions(self, mock_parse, mock_read, mock_log, mock_run):
        """Verify deletion line counts are included in total."""
        from zen_mode.core import should_skip_judge

        mock_run.side_effect = self._mock_staged_deletions()
        mock_read.return_value = "## Step 1: Delete file\n## Step 2: Modify other"
        mock_parse.return_value = [(1, "Delete file"), (2, "Modify other")]

        result = should_skip_judge()

        # 50 deletes + 10 adds + 5 deletes = 65 lines total
        assert result is False, "65 lines of changes should require judge review"

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.BACKUP_DIR')
    def test_deleted_file_not_in_backup_not_tracked(self, mock_backup_dir, mock_run):
        """Files created and deleted in same session leave no trace.

        This is a limitation - we can't verify deletion of files
        that were never backed up or committed.
        """
        from zen_mode.core import get_changed_filenames

        mock_run.return_value = Mock(returncode=0, stdout="")
        mock_backup_dir.exists.return_value = False

        result = get_changed_filenames()

        assert result == "[No files detected]"


# =============================================================================
# Tests for snapshot functions (create_snapshot, restore_snapshot, drop_snapshot)
# =============================================================================

class TestSnapshots:
    """Tests for git stash snapshot functions.

    WARNING: All tests must mock subprocess.run. Never make real git calls.

    These functions use git stash to create/restore snapshots before
    risky operations. Real calls could lose user's working changes.
    """

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.PROJECT_ROOT')
    @patch('zen_mode.core.log')
    def test_create_snapshot_success(self, mock_log, mock_project_root, mock_run):
        """create_snapshot creates a stash with the given label."""
        from zen_mode.core import create_snapshot

        mock_project_root.__truediv__ = lambda self, x: MagicMock(exists=lambda: True)

        def mock_side_effect(cmd, **kwargs):
            if "status" in cmd and "--porcelain" in cmd:
                return Mock(returncode=0, stdout="M file.py\n")
            if "stash" in cmd and "push" in cmd:
                return Mock(returncode=0, stdout="Saved working directory")
            return Mock(returncode=0, stdout="")

        mock_run.side_effect = mock_side_effect

        result = create_snapshot("step_1")

        assert "zen-snapshot-step_1" in result
        mock_log.assert_called()

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.PROJECT_ROOT')
    def test_create_snapshot_no_changes(self, mock_project_root, mock_run):
        """create_snapshot returns empty string when no changes to stash."""
        from zen_mode.core import create_snapshot

        mock_project_root.__truediv__ = lambda self, x: MagicMock(exists=lambda: True)
        mock_run.return_value = Mock(returncode=0, stdout="")  # No changes

        result = create_snapshot("step_1")

        assert result == ""

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.PROJECT_ROOT')
    def test_create_snapshot_not_git_repo(self, mock_project_root, mock_run):
        """create_snapshot returns empty string when not in a git repo."""
        from zen_mode.core import create_snapshot

        mock_project_root.__truediv__ = lambda self, x: MagicMock(exists=lambda: False)

        result = create_snapshot("step_1")

        assert result == ""
        mock_run.assert_not_called()

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.PROJECT_ROOT')
    @patch('zen_mode.core.log')
    def test_restore_snapshot_success(self, mock_log, mock_project_root, mock_run):
        """restore_snapshot pops the correct stash."""
        from zen_mode.core import restore_snapshot

        mock_project_root.__truediv__ = lambda self, x: MagicMock(exists=lambda: True)

        def mock_side_effect(cmd, **kwargs):
            if "stash" in cmd and "list" in cmd:
                return Mock(returncode=0, stdout="stash@{0}: On main: zen-snapshot-step_1-123456")
            if "stash" in cmd and "pop" in cmd:
                return Mock(returncode=0, stdout="Dropped stash")
            return Mock(returncode=0, stdout="")

        mock_run.side_effect = mock_side_effect

        result = restore_snapshot("zen-snapshot-step_1-123456")

        assert result is True

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.PROJECT_ROOT')
    def test_restore_snapshot_not_found(self, mock_project_root, mock_run):
        """restore_snapshot returns False when stash not found."""
        from zen_mode.core import restore_snapshot

        mock_project_root.__truediv__ = lambda self, x: MagicMock(exists=lambda: True)
        mock_run.return_value = Mock(returncode=0, stdout="")  # Empty stash list

        result = restore_snapshot("zen-snapshot-nonexistent")

        assert result is False

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.PROJECT_ROOT')
    def test_restore_snapshot_empty_msg(self, mock_project_root, mock_run):
        """restore_snapshot returns False for empty stash message."""
        from zen_mode.core import restore_snapshot

        result = restore_snapshot("")

        assert result is False
        mock_run.assert_not_called()

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.PROJECT_ROOT')
    def test_drop_snapshot_success(self, mock_project_root, mock_run):
        """drop_snapshot removes the stash entry."""
        from zen_mode.core import drop_snapshot

        mock_project_root.__truediv__ = lambda self, x: MagicMock(exists=lambda: True)

        def mock_side_effect(cmd, **kwargs):
            if "stash" in cmd and "list" in cmd:
                return Mock(returncode=0, stdout="stash@{0}: On main: zen-snapshot-step_1-123456")
            if "stash" in cmd and "drop" in cmd:
                return Mock(returncode=0, stdout="Dropped")
            return Mock(returncode=0, stdout="")

        mock_run.side_effect = mock_side_effect

        # Should not raise
        drop_snapshot("zen-snapshot-step_1-123456")

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.PROJECT_ROOT')
    def test_drop_snapshot_empty_msg_noop(self, mock_project_root, mock_run):
        """drop_snapshot does nothing for empty message."""
        from zen_mode.core import drop_snapshot

        drop_snapshot("")

        mock_run.assert_not_called()

"""
Tests for Judge phase helper functions.
"""
import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, Mock, MagicMock

import pytest

# Import from package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from zen_mode.core import get_changed_filenames, _is_test_or_doc, should_skip_judge


class TestGetChangedFilenames:
    """Test extraction of changed file names."""

    def _mock_normal_repo(self, diff_output="", untracked_output=""):
        """Mock a normal git repo with commits."""
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
        mock_run.side_effect = self._mock_normal_repo(
            diff_output="src/file1.py\nsrc/file2.py\ntests/test_file.py\n"
        )

        result = get_changed_filenames()

        # Files are sorted alphabetically
        assert "src/file1.py" in result
        assert "src/file2.py" in result
        assert "tests/test_file.py" in result

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.BACKUP_DIR')
    def test_git_diff_empty_output(self, mock_backup_dir, mock_run):
        """When git diff returns empty, fall back to backup."""
        mock_run.side_effect = self._mock_normal_repo(diff_output="", untracked_output="")

        # Mock backup directory with no files
        mock_backup_dir.exists.return_value = True
        mock_backup_dir.rglob.return_value = []

        result = get_changed_filenames()

        # No files detected from any source
        assert result == "[No files detected]"

    def test_git_diff_failure_uses_backup(self):
        """When git fails, fall back to backup directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_path = Path(tmpdir) / "backup"
            backup_path.mkdir()

            # Create files in backup
            (backup_path / "src").mkdir()
            (backup_path / "src" / "core.py").write_text("content")
            (backup_path / "tests").mkdir()
            (backup_path / "tests" / "test_core.py").write_text("content")

            with patch('zen_mode.core.subprocess.run') as mock_run:
                with patch('zen_mode.core.BACKUP_DIR', backup_path):
                    mock_run.side_effect = Exception("git not found")

                    result = get_changed_filenames()

                    assert "src/core.py" in result or "src\\core.py" in result
                    assert "tests/test_core.py" in result or "tests\\test_core.py" in result

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.BACKUP_DIR')
    def test_no_git_no_backup(self, mock_backup_dir, mock_run):
        """When both git and backup fail, return placeholder."""
        mock_run.side_effect = Exception("git not found")
        mock_backup_dir.exists.return_value = False

        result = get_changed_filenames()

        assert result == "[No files detected]"


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


class TestShouldSkipJudge:
    """Tests for should_skip_judge() function."""

    def _mock_git_numstat(self, numstat_output, untracked_output=""):
        """Helper to mock git subprocess calls.

        Assumes a normal git repo with commits (HEAD exists).
        """
        def mock_run(cmd, **kwargs):
            # git rev-parse --git-dir (checking if is a repo) - succeeds
            if "rev-parse" in cmd and "--git-dir" in cmd:
                return Mock(returncode=0, stdout=".git")
            # git rev-parse HEAD (checking if HEAD exists) - succeeds
            if "rev-parse" in cmd and "HEAD" in cmd:
                return Mock(returncode=0, stdout="abc123")
            # cmd is a list, check if specific args are in it
            if "--numstat" in cmd:
                return Mock(returncode=0, stdout=numstat_output)
            elif "ls-files" in cmd:
                return Mock(returncode=0, stdout=untracked_output)
            return Mock(returncode=1, stdout="")
        return mock_run

    # No changes
    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.log')
    def test_no_changes_skips_judge(self, mock_log, mock_run):
        """No changes detected should skip judge."""
        mock_run.side_effect = self._mock_git_numstat("", "")

        result = should_skip_judge()

        assert result is True
        mock_log.assert_called_with("[JUDGE] Skipping: No changes detected")

    # Rule A: Trivial changes
    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.log')
    def test_trivial_change_skips_judge(self, mock_log, mock_run):
        """Less than 5 lines changed should skip judge."""
        # 2 added, 1 deleted = 3 total
        mock_run.side_effect = self._mock_git_numstat("2\t1\tREADME.md")

        result = should_skip_judge()

        assert result is True
        mock_log.assert_called_with("[JUDGE] Skipping: Trivial (3 lines)")

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.log')
    def test_five_lines_not_trivial(self, mock_log, mock_run):
        """Exactly 5 lines is not trivial (threshold is <5)."""
        mock_run.side_effect = self._mock_git_numstat("3\t2\tsrc/core.py")

        result = should_skip_judge()

        # 5 lines is not < 5, so should not be skipped as trivial
        # But may be skipped by other rules
        assert result is True  # Will be skipped as small refactor (<20 lines)

    # Rule B: Risky files
    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.log')
    def test_auth_file_requires_judge(self, mock_log, mock_run):
        """Files with 'auth' in name require judge review."""
        mock_run.side_effect = self._mock_git_numstat("10\t5\tsrc/auth.py")

        result = should_skip_judge()

        assert result is False
        mock_log.assert_called_with("[JUDGE] Required: Sensitive file (src/auth.py)")

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.log')
    def test_login_file_requires_judge(self, mock_log, mock_run):
        """Files with 'login' in name require judge review."""
        mock_run.side_effect = self._mock_git_numstat("5\t3\tviews/login.py")

        result = should_skip_judge()

        assert result is False

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.log')
    def test_security_file_requires_judge(self, mock_log, mock_run):
        """Files with 'secur' in name require judge review."""
        mock_run.side_effect = self._mock_git_numstat("8\t2\tlib/security_utils.py")

        result = should_skip_judge()

        assert result is False

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.log')
    def test_payment_file_requires_judge(self, mock_log, mock_run):
        """Files with 'payment' in name require judge review."""
        mock_run.side_effect = self._mock_git_numstat("20\t10\tservices/payment.py")

        result = should_skip_judge()

        assert result is False

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.log')
    def test_crypto_file_requires_judge(self, mock_log, mock_run):
        """Files with 'crypt' in name require judge review."""
        mock_run.side_effect = self._mock_git_numstat("15\t5\tutils/encrypt.py")

        result = should_skip_judge()

        assert result is False

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.log')
    def test_secret_file_requires_judge(self, mock_log, mock_run):
        """Files with 'secret' in name require judge review."""
        mock_run.side_effect = self._mock_git_numstat("3\t1\tconfig/secrets.py")

        result = should_skip_judge()

        assert result is False

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.log')
    def test_token_file_requires_judge(self, mock_log, mock_run):
        """Files with 'token' in name require judge review."""
        mock_run.side_effect = self._mock_git_numstat("7\t2\tauth/token_manager.py")

        result = should_skip_judge()

        assert result is False

    # Rule C: Pure docs/tests
    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.log')
    def test_only_docs_skips_judge(self, mock_log, mock_run):
        """Changes only to doc files should skip judge."""
        mock_run.side_effect = self._mock_git_numstat("50\t20\tREADME.md\n30\t10\tdocs/guide.rst")

        result = should_skip_judge()

        assert result is True
        mock_log.assert_called_with("[JUDGE] Skipping: Only docs/tests changed")

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.log')
    def test_only_tests_skips_judge(self, mock_log, mock_run):
        """Changes only to test files should skip judge."""
        mock_run.side_effect = self._mock_git_numstat("100\t50\ttests/test_core.py\n80\t40\ttest_utils.py")

        result = should_skip_judge()

        assert result is True
        mock_log.assert_called_with("[JUDGE] Skipping: Only docs/tests changed")

    # Rule D: Small refactor
    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.log')
    @patch('zen_mode.core.read_file')
    @patch('zen_mode.core.parse_steps')
    def test_simple_plan_small_changes_skips(self, mock_parse, mock_read, mock_log, mock_run):
        """2 steps and <30 lines should skip judge."""
        mock_run.side_effect = self._mock_git_numstat("15\t10\tsrc/utils.py")
        mock_read.return_value = "## Step 1: Do X\n## Step 2: Do Y"
        mock_parse.return_value = [(1, "Do X"), (2, "Do Y")]

        result = should_skip_judge()

        assert result is True
        mock_log.assert_called_with("[JUDGE] Skipping: Simple (2 steps, 25 lines)")

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.log')
    @patch('zen_mode.core.read_file')
    @patch('zen_mode.core.parse_steps')
    def test_small_refactor_skips(self, mock_parse, mock_read, mock_log, mock_run):
        """<20 lines changed should skip as small refactor."""
        mock_run.side_effect = self._mock_git_numstat("10\t5\tsrc/core.py")
        mock_read.return_value = "## Step 1\n## Step 2\n## Step 3\n## Step 4"
        mock_parse.return_value = [(1, "A"), (2, "B"), (3, "C"), (4, "D")]

        result = should_skip_judge()

        assert result is True
        mock_log.assert_called_with("[JUDGE] Skipping: Small refactor (15 lines)")

    # New code files
    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.log')
    def test_new_code_file_requires_judge(self, mock_log, mock_run):
        """New code files (untracked) should require judge."""
        mock_run.side_effect = self._mock_git_numstat("", "src/new_feature.py")

        result = should_skip_judge()

        assert result is False
        mock_log.assert_called_with("[JUDGE] Required: New code files created")

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.log')
    def test_new_test_file_skips_judge(self, mock_log, mock_run):
        """New test files (untracked) should skip judge."""
        mock_run.side_effect = self._mock_git_numstat("", "tests/test_new.py")

        result = should_skip_judge()

        assert result is True
        mock_log.assert_called_with("[JUDGE] Skipping: Only new test/doc files")

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.log')
    def test_new_doc_file_skips_judge(self, mock_log, mock_run):
        """New doc files (untracked) should skip judge."""
        mock_run.side_effect = self._mock_git_numstat("", "docs/new_guide.md")

        result = should_skip_judge()

        assert result is True
        mock_log.assert_called_with("[JUDGE] Skipping: Only new test/doc files")

    # Edge cases
    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.log')
    def test_binary_file_handled(self, mock_log, mock_run):
        """Binary files (- in numstat) should be handled gracefully."""
        # Binary files show as "-\t-\tfilename"
        mock_run.side_effect = self._mock_git_numstat("-\t-\timage.png")

        result = should_skip_judge()

        # 0 lines changed, should skip as trivial
        assert result is True

    @patch('zen_mode.core.subprocess.run')
    def test_git_failure_requires_judge(self, mock_run):
        """Git command failure should require judge (safe default)."""
        mock_run.return_value = Mock(returncode=1, stdout="")

        result = should_skip_judge()

        assert result is False

    @patch('zen_mode.core.subprocess.run')
    def test_git_exception_requires_judge(self, mock_run):
        """Git exception should require judge (safe default)."""
        mock_run.side_effect = Exception("git not found")

        result = should_skip_judge()

        assert result is False

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.log')
    def test_mixed_code_and_docs_not_skipped_if_large(self, mock_log, mock_run):
        """Mixed changes with code files and >20 lines requires judge."""
        mock_run.side_effect = self._mock_git_numstat(
            "50\t20\tsrc/core.py\n10\t5\tREADME.md"
        )

        with patch('zen_mode.core.read_file') as mock_read:
            with patch('zen_mode.core.parse_steps') as mock_parse:
                mock_read.return_value = "## Step 1\n## Step 2\n## Step 3\n## Step 4"
                mock_parse.return_value = [(1, "A"), (2, "B"), (3, "C"), (4, "D")]

                result = should_skip_judge()

        # 85 lines total, 4 steps, code files - should NOT skip
        assert result is False

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.log')
    def test_risky_file_case_insensitive(self, mock_log, mock_run):
        """Risky file detection should be case insensitive."""
        mock_run.side_effect = self._mock_git_numstat("5\t2\tsrc/AUTH_Handler.py")

        result = should_skip_judge()

        assert result is False
        mock_log.assert_called_with("[JUDGE] Required: Sensitive file (src/AUTH_Handler.py)")


class TestGitEdgeCases:
    """Tests for edge cases in git state handling.

    These tests demonstrate bugs in the current implementation when:
    - No commits exist (fresh repo with staged files)
    - Files are deleted but never committed
    - Mixed staged/unstaged states
    """

    def _mock_no_head_repo(self, staged_files="", untracked_files="", staged_numstat=""):
        """Mock a git repo with no commits (HEAD doesn't exist).

        In this state:
        - git rev-parse --git-dir succeeds (is a repo)
        - git rev-parse HEAD fails (no commits)
        - git diff HEAD fails (returncode=128, fatal: bad revision 'HEAD')
        - git diff --cached works (shows staged files)
        - git diff --cached --numstat works (shows staged file stats)
        - git ls-files --others works (shows untracked files)
        """
        def mock_run(cmd, **kwargs):
            # git rev-parse --git-dir (checking if is a repo) - succeeds
            if "rev-parse" in cmd and "--git-dir" in cmd:
                return Mock(returncode=0, stdout=".git")
            # git rev-parse HEAD (checking if HEAD exists) - fails
            if "rev-parse" in cmd and "HEAD" in cmd:
                return Mock(returncode=128, stdout="", stderr="fatal: bad revision 'HEAD'")
            # HEAD doesn't exist - diff HEAD fails
            if "diff" in cmd and "HEAD" in cmd:
                return Mock(
                    returncode=128,
                    stdout="",
                    stderr="fatal: bad revision 'HEAD'"
                )
            # git diff --cached --numstat works (for should_skip_judge)
            if "diff" in cmd and "--cached" in cmd and "--numstat" in cmd:
                return Mock(returncode=0, stdout=staged_numstat)
            # git diff --cached --name-only works (for get_changed_filenames)
            if "diff" in cmd and "--cached" in cmd:
                return Mock(returncode=0, stdout=staged_files)
            # Untracked files work
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
        mock_run.side_effect = self._mock_no_head_repo(
            staged_files="src/main.py\nsrc/utils.py\n"
        )
        mock_backup_dir.exists.return_value = False

        result = get_changed_filenames()

        # BUG: Currently returns "[No files detected]" instead of the staged files
        # This test should PASS after the fix
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
        mock_run.side_effect = self._mock_no_head_repo(
            staged_files="tests/test_main.py\n",
            staged_numstat="50\t0\ttests/test_main.py\n"
        )

        result = should_skip_judge()

        # BUG: Returns False (requires judge) because git command fails
        # Should return True since only test files are staged
        # This test should PASS after the fix
        assert result is True, "Should skip judge when only test files are staged"

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.BACKUP_DIR')
    def test_get_changed_filenames_includes_untracked_in_no_head_repo(self, mock_backup_dir, mock_run):
        """BUG: Untracked files not detected when HEAD doesn't exist.

        Even without commits, untracked files should be detected.
        """
        mock_run.side_effect = self._mock_no_head_repo(
            staged_files="",
            untracked_files="new_file.py\n"
        )
        mock_backup_dir.exists.return_value = False

        result = get_changed_filenames()

        # Should detect untracked files even without HEAD
        assert "new_file.py" in result, f"Expected untracked files, got: {result}"

    def _mock_staged_deletions(self):
        """Mock a repo with staged file deletions.

        git diff HEAD shows deleted files.
        git diff --numstat HEAD shows 0 additions, N deletions for deleted files.
        """
        def mock_run(cmd, **kwargs):
            if "--name-only" in cmd and "HEAD" in cmd:
                return Mock(returncode=0, stdout="deleted_file.py\nmodified_file.py\n")
            if "--numstat" in cmd and "HEAD" in cmd:
                # deleted_file.py: 0 adds, 50 deletes
                # modified_file.py: 10 adds, 5 deletes
                return Mock(returncode=0, stdout="0\t50\tdeleted_file.py\n10\t5\tmodified_file.py\n")
            if "ls-files" in cmd:
                return Mock(returncode=0, stdout="")
            return Mock(returncode=0, stdout="")
        return mock_run

    @patch('zen_mode.core.subprocess.run')
    def test_get_changed_filenames_shows_deleted_files(self, mock_run):
        """Verify deleted files appear in changed files list."""
        mock_run.side_effect = self._mock_staged_deletions()

        result = get_changed_filenames()

        assert "deleted_file.py" in result, "Deleted files should appear in changed list"
        assert "modified_file.py" in result

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.log')
    @patch('zen_mode.core.read_file')
    @patch('zen_mode.core.parse_steps')
    def test_should_skip_judge_counts_deletions(self, mock_parse, mock_read, mock_log, mock_run):
        """Verify deletion line counts are included in total.

        50 deleted lines should count toward the total change size.
        """
        mock_run.side_effect = self._mock_staged_deletions()
        mock_read.return_value = "## Step 1: Delete file\n## Step 2: Modify other"
        mock_parse.return_value = [(1, "Delete file"), (2, "Modify other")]

        result = should_skip_judge()

        # 50 deletes + 10 adds + 5 deletes = 65 lines total
        # Should NOT skip with 65 lines of changes
        assert result is False, "65 lines of changes should require judge review"


class TestDeletionTracking:
    """Tests for verifying file deletion tracking.

    The scout phase may identify deletion candidates, and we need
    to verify those deletions actually occurred.
    """

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.BACKUP_DIR')
    def test_deleted_file_not_in_backup_not_tracked(self, mock_backup_dir, mock_run):
        """BUG: Files created and deleted in same session leave no trace.

        Scenario:
        1. Agent creates new_file.py (not committed)
        2. Agent later deletes new_file.py
        3. No record exists that this file was ever created/deleted

        This is a limitation - we can't verify deletion of files
        that were never backed up or committed.
        """
        # Git shows no changes (file was created and deleted, never tracked)
        mock_run.return_value = Mock(returncode=0, stdout="")
        mock_backup_dir.exists.return_value = False

        result = get_changed_filenames()

        # No way to know a file was created and deleted
        assert result == "[No files detected]"
        # This test documents the limitation - not necessarily a bug to fix,
        # but important to understand the behavior


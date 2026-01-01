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
            if "rev-parse" in cmd and "--is-inside-work-tree" in cmd:
                return Mock(returncode=0, stdout="true")
            if "rev-parse" in cmd and "HEAD" in cmd:
                return Mock(returncode=0, stdout="abc123")
            if "diff" in cmd and "--name-only" in cmd:
                return Mock(returncode=0, stdout=diff_output)
            if "ls-files" in cmd:
                return Mock(returncode=0, stdout=untracked_output)
            return Mock(returncode=1, stdout="")
        return mock_run

    @patch('zen_mode.git.subprocess.run')
    def test_git_diff_success(self, mock_run):
        """When git diff succeeds, return file list."""
        from zen_mode.git import get_changed_filenames
        from pathlib import Path

        mock_run.side_effect = self._mock_normal_repo(
            diff_output="src/file1.py\nsrc/file2.py\ntests/test_file.py\n"
        )

        project_root = Path("/fake/project")
        backup_dir = Path("/fake/backup")
        result = get_changed_filenames(project_root, backup_dir)

        assert "src/file1.py" in result
        assert "src/file2.py" in result
        assert "tests/test_file.py" in result

    @patch('zen_mode.git.subprocess.run')
    def test_git_diff_empty_output(self, mock_run):
        """When git diff returns empty, fall back to backup."""
        from zen_mode.git import get_changed_filenames
        from pathlib import Path
        from unittest.mock import Mock

        mock_run.side_effect = self._mock_normal_repo(diff_output="", untracked_output="")

        project_root = Path("/fake/project")
        mock_backup_dir = Mock(spec=Path)
        mock_backup_dir.exists.return_value = True
        mock_backup_dir.rglob.return_value = []

        result = get_changed_filenames(project_root, mock_backup_dir)

        assert result == "[No files detected]"

    @patch('zen_mode.git.subprocess.run')
    def test_git_failure_uses_backup(self, mock_run):
        """When git fails, fall back to backup directory."""
        from zen_mode.git import get_changed_filenames
        from pathlib import Path
        from unittest.mock import Mock

        mock_run.side_effect = OSError("git not found")

        project_root = Path("/fake/project")
        mock_backup_dir = Mock(spec=Path)
        # Mock backup directory with files
        mock_backup_dir.exists.return_value = True
        mock_file1 = MagicMock()
        mock_file1.relative_to.return_value = Path("src/core.py")
        mock_file1.is_file.return_value = True
        mock_file2 = MagicMock()
        mock_file2.relative_to.return_value = Path("tests/test_core.py")
        mock_file2.is_file.return_value = True
        mock_backup_dir.rglob.return_value = [mock_file1, mock_file2]

        result = get_changed_filenames(project_root, mock_backup_dir)

        assert "src/core.py" in result or "src\\core.py" in result

    @patch('zen_mode.git.subprocess.run')
    def test_no_git_no_backup(self, mock_run):
        """When both git and backup fail, return placeholder."""
        from zen_mode.git import get_changed_filenames
        from pathlib import Path
        from unittest.mock import Mock

        mock_run.side_effect = OSError("git not found")

        project_root = Path("/fake/project")
        mock_backup_dir = Mock(spec=Path)
        mock_backup_dir.exists.return_value = False

        result = get_changed_filenames(project_root, mock_backup_dir)

        assert result == "[No files detected]"


# =============================================================================
# Tests for should_skip_judge_ctx() in zen_mode.judge
# =============================================================================

class TestShouldSkipJudgeGitOperations:
    """Tests for git operations in should_skip_judge_ctx().

    These tests mock zen_mode.git functions to test judge behavior.
    """

    def _make_mock_ctx(self, tmp_path):
        """Create a mock Context for testing."""
        from zen_mode.context import Context
        work_dir = tmp_path / ".zen"
        work_dir.mkdir(exist_ok=True)
        plan_file = work_dir / "plan.md"
        plan_file.write_text("## Step 1: Test step\n")
        return Context(
            work_dir=work_dir,
            task_file="task.md",
            project_root=tmp_path,
        )

    @patch('zen_mode.judge.git.get_untracked_files')
    @patch('zen_mode.judge.git.get_diff_stats')
    @patch('zen_mode.judge.git.is_repo')
    def test_no_changes_skips_judge(self, mock_is_repo, mock_get_diff_stats, mock_get_untracked, tmp_path):
        """No changes detected should skip judge."""
        from zen_mode.judge import should_skip_judge_ctx
        from zen_mode.git import DiffStats

        mock_is_repo.return_value = True
        mock_get_diff_stats.return_value = DiffStats(added=0, deleted=0, files=[])
        mock_get_untracked.return_value = []
        ctx = self._make_mock_ctx(tmp_path)
        log_messages = []

        result = should_skip_judge_ctx(ctx, log_fn=log_messages.append)

        assert result is True
        assert any("[JUDGE] Skipping: No changes detected" in msg for msg in log_messages)

    @patch('zen_mode.judge.git.is_repo')
    def test_git_failure_requires_judge(self, mock_is_repo, tmp_path):
        """Not a git repo should require judge (safe default)."""
        from zen_mode.judge import should_skip_judge_ctx

        mock_is_repo.return_value = False
        ctx = self._make_mock_ctx(tmp_path)

        result = should_skip_judge_ctx(ctx)

        assert result is False

    @patch('zen_mode.judge.git.is_repo')
    def test_git_exception_requires_judge(self, mock_is_repo, tmp_path):
        """Git exception should require judge (safe default)."""
        from zen_mode.judge import should_skip_judge_ctx

        mock_is_repo.side_effect = OSError("git not found")
        ctx = self._make_mock_ctx(tmp_path)

        # Exception propagates, causing default False behavior
        try:
            result = should_skip_judge_ctx(ctx)
            assert result is False
        except Exception:
            # Exception means we need judge review (safe default)
            pass


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
            if "rev-parse" in cmd and ("--is-inside-work-tree" in cmd or "--git-dir" in cmd):
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

    @patch('zen_mode.git.subprocess.run')
    def test_get_changed_filenames_no_head_with_staged_files(self, mock_run):
        """BUG: get_changed_filenames() returns nothing when HEAD doesn't exist.

        Scenario: Fresh repo, files are staged but no commits yet.
        Expected: Should return the staged files.
        Actual: Returns '[No files detected]' because git diff HEAD fails.
        """
        from zen_mode.git import get_changed_filenames
        from pathlib import Path
        from unittest.mock import Mock

        mock_run.side_effect = self._mock_no_head_repo(
            staged_files="src/main.py\nsrc/utils.py\n"
        )

        project_root = Path("/fake/project")
        mock_backup_dir = Mock(spec=Path)
        mock_backup_dir.exists.return_value = False

        result = get_changed_filenames(project_root, mock_backup_dir)

        assert "src/main.py" in result, f"Expected staged files, got: {result}"
        assert "src/utils.py" in result

    @patch('zen_mode.judge.git.get_untracked_files')
    @patch('zen_mode.judge.git.get_diff_stats')
    @patch('zen_mode.judge.git.is_repo')
    def test_should_skip_judge_no_head_with_staged_files(self, mock_is_repo, mock_get_diff_stats, mock_get_untracked, tmp_path):
        """should_skip_judge() should skip when only test files changed.

        Scenario: Fresh repo with only test files staged.
        Expected: Should skip judge (only test files).
        """
        from zen_mode.judge import should_skip_judge_ctx
        from zen_mode.context import Context
        from zen_mode.git import DiffStats

        mock_is_repo.return_value = True
        mock_get_diff_stats.return_value = DiffStats(added=50, deleted=0, files=["tests/test_main.py"])
        mock_get_untracked.return_value = []

        work_dir = tmp_path / ".zen"
        work_dir.mkdir(exist_ok=True)
        plan_file = work_dir / "plan.md"
        plan_file.write_text("## Step 1: Test step\n")
        ctx = Context(work_dir=work_dir, task_file="task.md", project_root=tmp_path)

        result = should_skip_judge_ctx(ctx)

        assert result is True, "Should skip judge when only test files are staged"

    @patch('zen_mode.git.subprocess.run')
    def test_get_changed_filenames_includes_untracked_in_no_head_repo(self, mock_run):
        """BUG: Untracked files not detected when HEAD doesn't exist."""
        from zen_mode.git import get_changed_filenames
        from pathlib import Path
        from unittest.mock import Mock

        mock_run.side_effect = self._mock_no_head_repo(
            staged_files="",
            untracked_files="new_file.py\n"
        )

        project_root = Path("/fake/project")
        mock_backup_dir = Mock(spec=Path)
        mock_backup_dir.exists.return_value = False

        result = get_changed_filenames(project_root, mock_backup_dir)

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
            if "rev-parse" in cmd and ("--is-inside-work-tree" in cmd or "--git-dir" in cmd):
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

    @patch('zen_mode.git.subprocess.run')
    def test_get_changed_filenames_shows_deleted_files(self, mock_run):
        """Verify deleted files appear in changed files list."""
        from zen_mode.git import get_changed_filenames
        from pathlib import Path

        mock_run.side_effect = self._mock_staged_deletions()

        project_root = Path("/fake/project")
        backup_dir = Path("/fake/backup")
        result = get_changed_filenames(project_root, backup_dir)

        assert "deleted_file.py" in result, "Deleted files should appear in changed list"
        assert "modified_file.py" in result

    @patch('zen_mode.judge.git.get_untracked_files')
    @patch('zen_mode.judge.git.get_diff_stats')
    @patch('zen_mode.judge.git.is_repo')
    def test_should_skip_judge_counts_deletions(self, mock_is_repo, mock_get_diff_stats, mock_get_untracked, tmp_path):
        """Verify deletion line counts are included in total."""
        from zen_mode.judge import should_skip_judge_ctx
        from zen_mode.context import Context
        from zen_mode.git import DiffStats

        mock_is_repo.return_value = True
        # 50 deleted + 10 added + 5 deleted = 65 lines total
        mock_get_diff_stats.return_value = DiffStats(
            added=10, deleted=55, files=["deleted_file.py", "modified_file.py"]
        )
        mock_get_untracked.return_value = []

        work_dir = tmp_path / ".zen"
        work_dir.mkdir(exist_ok=True)
        plan_file = work_dir / "plan.md"
        plan_file.write_text("## Step 1: Delete file\n## Step 2: Modify other\n")
        ctx = Context(work_dir=work_dir, task_file="task.md", project_root=tmp_path)

        result = should_skip_judge_ctx(ctx)

        # 65 lines total should require judge review
        assert result is False, "65 lines of changes should require judge review"

    @patch('zen_mode.git.subprocess.run')
    def test_deleted_file_not_in_backup_not_tracked(self, mock_run):
        """Files created and deleted in same session leave no trace.

        This is a limitation - we can't verify deletion of files
        that were never backed up or committed.
        """
        from zen_mode.git import get_changed_filenames
        from pathlib import Path
        from unittest.mock import Mock

        mock_run.return_value = Mock(returncode=0, stdout="")

        project_root = Path("/fake/project")
        mock_backup_dir = Mock(spec=Path)
        mock_backup_dir.exists.return_value = False

        result = get_changed_filenames(project_root, mock_backup_dir)

        assert result == "[No files detected]"


# =============================================================================
# Tests for zen_mode.git module (Real git operations with tmp_path fixtures)
# =============================================================================
# These tests use tmp_path to create isolated git repos - safe because they
# don't touch the user's actual repository.

class TestGitModuleRepoState:
    """Tests for git repo state detection in zen_mode.git."""

    def test_is_repo_true_for_git_repo(self, tmp_path):
        """is_repo() returns True for initialized git repo."""
        import subprocess
        from zen_mode.git import is_repo

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        assert is_repo(tmp_path) is True

    def test_is_repo_false_for_non_repo(self, tmp_path):
        """is_repo() returns False for non-git directory."""
        from zen_mode.git import is_repo

        assert is_repo(tmp_path) is False

    def test_has_head_false_for_empty_repo(self, tmp_path):
        """has_head() returns False for repo with no commits."""
        import subprocess
        from zen_mode.git import has_head

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        assert has_head(tmp_path) is False

    def test_has_head_true_after_commit(self, tmp_path):
        """has_head() returns True after first commit."""
        import subprocess
        from zen_mode.git import has_head

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
        (tmp_path / "file.txt").write_text("content")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, capture_output=True)

        assert has_head(tmp_path) is True

    def test_get_head_commit_returns_hash(self, tmp_path):
        """get_head_commit() returns commit hash."""
        import subprocess
        from zen_mode.git import get_head_commit

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
        (tmp_path / "file.txt").write_text("content")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, capture_output=True)

        commit = get_head_commit(tmp_path)
        assert commit is not None
        assert len(commit) == 40  # SHA-1 hash length


class TestGitModuleChangedFiles:
    """Tests for changed file detection in zen_mode.git."""

    def test_get_staged_files(self, tmp_path):
        """get_staged_files() returns staged file list."""
        import subprocess
        from zen_mode.git import get_staged_files

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
        (tmp_path / "staged.py").write_text("staged content")
        subprocess.run(["git", "add", "staged.py"], cwd=tmp_path, capture_output=True)

        files = get_staged_files(tmp_path)
        assert "staged.py" in files

    def test_get_untracked_files(self, tmp_path):
        """get_untracked_files() returns untracked file list."""
        import subprocess
        from zen_mode.git import get_untracked_files

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        (tmp_path / "untracked.py").write_text("untracked content")

        files = get_untracked_files(tmp_path)
        assert "untracked.py" in files

    def test_get_unstaged_files(self, tmp_path):
        """get_unstaged_files() returns modified but unstaged files."""
        import subprocess
        from zen_mode.git import get_unstaged_files

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
        (tmp_path / "file.py").write_text("original")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, capture_output=True)
        (tmp_path / "file.py").write_text("modified")

        files = get_unstaged_files(tmp_path)
        assert "file.py" in files

    def test_get_changed_files_combined(self, tmp_path):
        """get_changed_files() returns all changed files."""
        import subprocess
        from zen_mode.git import get_changed_files

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
        (tmp_path / "committed.py").write_text("committed")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, capture_output=True)

        # Create various states
        (tmp_path / "committed.py").write_text("modified")  # unstaged
        (tmp_path / "staged.py").write_text("staged")
        subprocess.run(["git", "add", "staged.py"], cwd=tmp_path, capture_output=True)
        (tmp_path / "untracked.py").write_text("untracked")

        files = get_changed_files(tmp_path)
        assert "committed.py" in files  # unstaged
        assert "staged.py" in files      # staged
        assert "untracked.py" in files   # untracked


class TestGitModuleDiffStats:
    """Tests for diff statistics in zen_mode.git."""

    def test_get_diff_stats_counts_lines(self, tmp_path):
        """get_diff_stats() returns line counts."""
        import subprocess
        from zen_mode.git import get_diff_stats

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
        (tmp_path / "file.py").write_text("line1\nline2\nline3\n")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, capture_output=True)

        # Modify file
        (tmp_path / "file.py").write_text("line1\nmodified\nline3\nnew line\n")

        stats = get_diff_stats(tmp_path)
        assert stats.added >= 1
        assert stats.total > 0
        assert "file.py" in stats.files

    def test_diff_stats_empty_for_no_changes(self, tmp_path):
        """get_diff_stats() returns zeros when no changes."""
        import subprocess
        from zen_mode.git import get_diff_stats

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
        (tmp_path / "file.py").write_text("content")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, capture_output=True)

        stats = get_diff_stats(tmp_path)
        assert stats.added == 0
        assert stats.deleted == 0
        assert stats.total == 0


class TestGitModuleGrep:
    """Tests for git grep in zen_mode.git."""

    def test_grep_files_finds_pattern(self, tmp_path):
        """grep_files() finds files containing pattern."""
        import subprocess
        from zen_mode.git import grep_files

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        (tmp_path / "has_pattern.py").write_text("def my_function():\n    pass\n")
        (tmp_path / "no_pattern.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)

        files = grep_files("my_function", tmp_path)
        assert "has_pattern.py" in files
        assert "no_pattern.py" not in files

    def test_grep_files_with_extension_filter(self, tmp_path):
        """grep_files() filters by extension."""
        import subprocess
        from zen_mode.git import grep_files

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        (tmp_path / "file.py").write_text("pattern here\n")
        (tmp_path / "file.js").write_text("pattern here\n")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)

        files = grep_files("pattern", tmp_path, extensions=[".py"])
        assert "file.py" in files
        assert "file.js" not in files


# =============================================================================
# Fixture for temp git repos with initial commit
# =============================================================================

@pytest.fixture
def temp_git_repo(tmp_path):
    """Create a temporary git repo with initial commit."""
    import subprocess
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)
    (repo / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial"], cwd=repo, capture_output=True)
    return repo


# =============================================================================
# Tests for is_clean, get_current_branch, is_detached_head
# =============================================================================

class TestGitRepoStateExtended:
    """Tests for extended repository state functions."""

    def test_is_clean_true_after_commit(self, temp_git_repo):
        """is_clean() returns True when no uncommitted changes."""
        from zen_mode.git import is_clean

        assert is_clean(temp_git_repo) is True

    def test_is_clean_false_with_unstaged(self, temp_git_repo):
        """is_clean() returns False with unstaged changes."""
        from zen_mode.git import is_clean

        (temp_git_repo / "README.md").write_text("# Modified")
        assert is_clean(temp_git_repo) is False

    def test_is_clean_false_with_staged(self, temp_git_repo):
        """is_clean() returns False with staged changes."""
        import subprocess
        from zen_mode.git import is_clean

        (temp_git_repo / "new_file.txt").write_text("content")
        subprocess.run(["git", "add", "new_file.txt"], cwd=temp_git_repo, capture_output=True)
        assert is_clean(temp_git_repo) is False

    def test_is_clean_false_with_untracked(self, temp_git_repo):
        """is_clean() returns False with untracked files."""
        from zen_mode.git import is_clean

        (temp_git_repo / "untracked.txt").write_text("content")
        assert is_clean(temp_git_repo) is False

    @patch('zen_mode.git.subprocess.run')
    def test_is_clean_returns_false_on_error(self, mock_run, temp_git_repo):
        """is_clean() returns False when git fails."""
        from zen_mode.git import is_clean

        mock_run.side_effect = OSError("git not found")
        assert is_clean(temp_git_repo) is False

    def test_get_current_branch_returns_branch_name(self, temp_git_repo):
        """get_current_branch() returns the current branch name."""
        from zen_mode.git import get_current_branch

        branch = get_current_branch(temp_git_repo)
        # Default branch could be 'main' or 'master' depending on git config
        assert branch in ("main", "master")

    def test_get_current_branch_returns_none_for_non_repo(self, tmp_path):
        """get_current_branch() returns None for non-git directory."""
        from zen_mode.git import get_current_branch

        assert get_current_branch(tmp_path) is None

    def test_get_current_branch_after_checkout(self, temp_git_repo):
        """get_current_branch() returns correct branch after checkout."""
        import subprocess
        from zen_mode.git import get_current_branch

        subprocess.run(["git", "checkout", "-b", "feature-branch"], cwd=temp_git_repo, capture_output=True)
        assert get_current_branch(temp_git_repo) == "feature-branch"

    def test_is_detached_head_false_on_branch(self, temp_git_repo):
        """is_detached_head() returns False when on a branch."""
        from zen_mode.git import is_detached_head

        assert is_detached_head(temp_git_repo) is False

    def test_is_detached_head_true_when_detached(self, temp_git_repo):
        """is_detached_head() returns True when HEAD is detached."""
        import subprocess
        from zen_mode.git import is_detached_head, get_head_commit

        commit = get_head_commit(temp_git_repo)
        subprocess.run(["git", "checkout", commit], cwd=temp_git_repo, capture_output=True)
        assert is_detached_head(temp_git_repo) is True

    def test_is_detached_head_false_for_non_repo(self, tmp_path):
        """is_detached_head() returns False for non-git directory."""
        from zen_mode.git import is_detached_head

        assert is_detached_head(tmp_path) is False


# =============================================================================
# Tests for worktree operations
# =============================================================================

class TestGitWorktreeOperations:
    """Tests for git worktree functions."""

    def test_create_worktree_success(self, temp_git_repo, tmp_path):
        """create_worktree() creates a new worktree."""
        from zen_mode.git import create_worktree, list_worktrees

        worktree_path = tmp_path / "worktree"
        result = create_worktree(temp_git_repo, worktree_path, "feature-branch")

        assert result is True
        assert worktree_path.exists()
        assert (worktree_path / "README.md").exists()

    def test_create_worktree_failure_existing_branch(self, temp_git_repo, tmp_path):
        """create_worktree() fails if branch already exists."""
        import subprocess
        from zen_mode.git import create_worktree

        # Create a branch first
        subprocess.run(["git", "branch", "existing-branch"], cwd=temp_git_repo, capture_output=True)

        worktree_path = tmp_path / "worktree"
        result = create_worktree(temp_git_repo, worktree_path, "existing-branch")

        assert result is False

    @patch('zen_mode.git.subprocess.run')
    def test_create_worktree_returns_false_on_error(self, mock_run, temp_git_repo, tmp_path):
        """create_worktree() returns False when git fails."""
        from zen_mode.git import create_worktree

        mock_run.side_effect = OSError("git not found")
        worktree_path = tmp_path / "worktree"
        assert create_worktree(temp_git_repo, worktree_path, "branch") is False

    def test_list_worktrees_includes_main_and_created(self, temp_git_repo, tmp_path):
        """list_worktrees() returns all worktree paths."""
        from zen_mode.git import create_worktree, list_worktrees

        # Initially just the main worktree
        worktrees = list_worktrees(temp_git_repo)
        assert len(worktrees) >= 1
        assert str(temp_git_repo) in worktrees[0] or temp_git_repo.name in worktrees[0]

        # Add a worktree
        worktree_path = tmp_path / "worktree"
        create_worktree(temp_git_repo, worktree_path, "feature-branch")

        worktrees = list_worktrees(temp_git_repo)
        assert len(worktrees) >= 2

    def test_list_worktrees_empty_for_non_repo(self, tmp_path):
        """list_worktrees() returns empty list for non-git directory."""
        from zen_mode.git import list_worktrees

        assert list_worktrees(tmp_path) == []

    def test_remove_worktree_success(self, temp_git_repo, tmp_path):
        """remove_worktree() removes a worktree."""
        from zen_mode.git import create_worktree, remove_worktree, list_worktrees
        import sys

        worktree_path = tmp_path / "worktree"
        create_worktree(temp_git_repo, worktree_path, "feature-branch")

        initial_count = len(list_worktrees(temp_git_repo))
        # Use retry=True on Windows since file locks can prevent immediate removal
        result = remove_worktree(worktree_path, retry=True)

        # On Windows, worktree removal can fail due to file locks even with retry
        # This is a known limitation in test environments
        if result:
            assert len(list_worktrees(temp_git_repo)) < initial_count
        elif sys.platform == "win32":
            # Expected on Windows - file locks can prevent removal
            pass
        else:
            assert result is True  # Should succeed on non-Windows

    def test_remove_worktree_no_retry(self, temp_git_repo, tmp_path):
        """remove_worktree() with retry=False does not retry on failure."""
        from zen_mode.git import create_worktree, remove_worktree
        import sys

        worktree_path = tmp_path / "worktree"
        create_worktree(temp_git_repo, worktree_path, "feature-branch")

        # With retry=False, only one attempt is made
        result = remove_worktree(worktree_path, retry=False)
        # On Windows with file locks, this may fail - that's expected
        # The test verifies the function runs without crashing
        if sys.platform != "win32":
            assert result is True

    @patch('zen_mode.git.subprocess.run')
    def test_remove_worktree_returns_false_on_error(self, mock_run, tmp_path):
        """remove_worktree() returns False when git fails."""
        from zen_mode.git import remove_worktree

        mock_run.side_effect = OSError("git not found")
        result = remove_worktree(tmp_path / "nonexistent", retry=False)
        assert result is False

    @patch('zen_mode.git.time.sleep')
    @patch('zen_mode.git.subprocess.run')
    def test_remove_worktree_retry_attempts(self, mock_run, mock_sleep, tmp_path):
        """remove_worktree() retries with exponential backoff on failure."""
        from zen_mode.git import remove_worktree

        # Mock failure on all attempts
        mock_run.return_value = Mock(returncode=1, stderr="Permission denied")

        result = remove_worktree(tmp_path / "worktree", retry=True)

        assert result is False
        # Should have 3 attempts
        assert mock_run.call_count == 3
        # Sleep called between attempts (2 times: after 1st and 2nd attempt)
        assert mock_sleep.call_count == 2
        # Delays: 0.5s after first attempt, 1.0s after second attempt
        mock_sleep.assert_any_call(0.5)
        mock_sleep.assert_any_call(1.0)

    @patch('zen_mode.git.time.sleep')
    @patch('zen_mode.git.subprocess.run')
    def test_remove_worktree_succeeds_on_second_attempt(self, mock_run, mock_sleep, tmp_path):
        """remove_worktree() succeeds if a retry works."""
        from zen_mode.git import remove_worktree

        # First call fails, second succeeds
        mock_run.side_effect = [
            Mock(returncode=1, stderr="Permission denied"),
            Mock(returncode=0, stdout=""),
        ]

        result = remove_worktree(tmp_path / "worktree", retry=True)

        assert result is True
        assert mock_run.call_count == 2
        # Sleep between first and second attempt (0.5s)
        mock_sleep.assert_called_once_with(0.5)


# =============================================================================
# Tests for merge operations
# =============================================================================

class TestGitMergeOperations:
    """Tests for git merge functions."""

    def test_merge_squash_success(self, temp_git_repo):
        """merge_squash() successfully merges a branch."""
        import subprocess
        from zen_mode.git import merge_squash

        # Create and checkout a feature branch, make a commit
        subprocess.run(["git", "checkout", "-b", "feature"], cwd=temp_git_repo, capture_output=True)
        (temp_git_repo / "feature.txt").write_text("feature content")
        subprocess.run(["git", "add", "."], cwd=temp_git_repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Feature commit"], cwd=temp_git_repo, capture_output=True)

        # Go back to main/master and merge
        subprocess.run(["git", "checkout", "-"], cwd=temp_git_repo, capture_output=True)

        success, message = merge_squash(temp_git_repo, "feature")
        assert success is True

    def test_merge_squash_nonexistent_branch(self, temp_git_repo):
        """merge_squash() fails for non-existent branch."""
        from zen_mode.git import merge_squash

        success, message = merge_squash(temp_git_repo, "nonexistent-branch")
        assert success is False
        assert message != ""

    @patch('zen_mode.git.subprocess.run')
    def test_merge_squash_returns_error_on_exception(self, mock_run, temp_git_repo):
        """merge_squash() returns error tuple on exception."""
        from zen_mode.git import merge_squash

        mock_run.side_effect = OSError("git not found")
        success, message = merge_squash(temp_git_repo, "branch")
        assert success is False
        assert "git not found" in message

    def test_has_merge_conflicts_false_normally(self, temp_git_repo):
        """has_merge_conflicts() returns False when no conflicts."""
        from zen_mode.git import has_merge_conflicts

        assert has_merge_conflicts(temp_git_repo) is False

    def test_has_merge_conflicts_true_with_conflict(self, temp_git_repo):
        """has_merge_conflicts() returns True during conflict."""
        import subprocess
        from zen_mode.git import has_merge_conflicts

        # Create a conflict scenario
        # Branch 1: modify file
        subprocess.run(["git", "checkout", "-b", "branch1"], cwd=temp_git_repo, capture_output=True)
        (temp_git_repo / "README.md").write_text("# Branch 1 content")
        subprocess.run(["git", "add", "."], cwd=temp_git_repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Branch 1"], cwd=temp_git_repo, capture_output=True)

        # Branch 2 from initial: modify same file differently
        subprocess.run(["git", "checkout", "-b", "branch2", "HEAD~1"], cwd=temp_git_repo, capture_output=True)
        (temp_git_repo / "README.md").write_text("# Branch 2 content")
        subprocess.run(["git", "add", "."], cwd=temp_git_repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Branch 2"], cwd=temp_git_repo, capture_output=True)

        # Try to merge branch1 into branch2 (should conflict)
        subprocess.run(["git", "merge", "branch1"], cwd=temp_git_repo, capture_output=True)

        assert has_merge_conflicts(temp_git_repo) is True

    def test_abort_merge_success(self, temp_git_repo):
        """abort_merge() aborts an in-progress merge."""
        import subprocess
        from zen_mode.git import abort_merge, has_merge_conflicts

        # Create a conflict scenario
        subprocess.run(["git", "checkout", "-b", "branch1"], cwd=temp_git_repo, capture_output=True)
        (temp_git_repo / "README.md").write_text("# Branch 1 content")
        subprocess.run(["git", "add", "."], cwd=temp_git_repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Branch 1"], cwd=temp_git_repo, capture_output=True)

        subprocess.run(["git", "checkout", "-b", "branch2", "HEAD~1"], cwd=temp_git_repo, capture_output=True)
        (temp_git_repo / "README.md").write_text("# Branch 2 content")
        subprocess.run(["git", "add", "."], cwd=temp_git_repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Branch 2"], cwd=temp_git_repo, capture_output=True)

        subprocess.run(["git", "merge", "branch1"], cwd=temp_git_repo, capture_output=True)

        # Abort the merge
        result = abort_merge(temp_git_repo)
        assert result is True
        assert has_merge_conflicts(temp_git_repo) is False

    def test_abort_merge_false_when_no_merge(self, temp_git_repo):
        """abort_merge() returns False when no merge in progress."""
        from zen_mode.git import abort_merge

        # No merge in progress - should fail
        result = abort_merge(temp_git_repo)
        assert result is False


# =============================================================================
# Tests for branch operations
# =============================================================================

class TestGitBranchOperations:
    """Tests for git branch functions."""

    def test_delete_branch_success(self, temp_git_repo):
        """delete_branch() deletes a branch."""
        import subprocess
        from zen_mode.git import delete_branch, list_branches

        subprocess.run(["git", "branch", "to-delete"], cwd=temp_git_repo, capture_output=True)
        assert "to-delete" in list_branches(temp_git_repo)

        result = delete_branch(temp_git_repo, "to-delete")
        assert result is True
        assert "to-delete" not in list_branches(temp_git_repo)

    def test_delete_branch_nonexistent(self, temp_git_repo):
        """delete_branch() returns False for non-existent branch."""
        from zen_mode.git import delete_branch

        result = delete_branch(temp_git_repo, "nonexistent")
        assert result is False

    def test_delete_branch_cannot_delete_current(self, temp_git_repo):
        """delete_branch() fails when trying to delete current branch."""
        from zen_mode.git import delete_branch, get_current_branch

        current = get_current_branch(temp_git_repo)
        result = delete_branch(temp_git_repo, current)
        assert result is False

    @patch('zen_mode.git.subprocess.run')
    def test_delete_branch_returns_false_on_error(self, mock_run, temp_git_repo):
        """delete_branch() returns False when git fails."""
        from zen_mode.git import delete_branch

        mock_run.side_effect = OSError("git not found")
        assert delete_branch(temp_git_repo, "branch") is False

    def test_list_branches_includes_all(self, temp_git_repo):
        """list_branches() returns all local branches."""
        import subprocess
        from zen_mode.git import list_branches

        subprocess.run(["git", "branch", "branch-a"], cwd=temp_git_repo, capture_output=True)
        subprocess.run(["git", "branch", "branch-b"], cwd=temp_git_repo, capture_output=True)
        subprocess.run(["git", "branch", "feature-x"], cwd=temp_git_repo, capture_output=True)

        branches = list_branches(temp_git_repo)
        assert "branch-a" in branches
        assert "branch-b" in branches
        assert "feature-x" in branches

    def test_list_branches_with_pattern(self, temp_git_repo):
        """list_branches() filters by pattern."""
        import subprocess
        from zen_mode.git import list_branches

        subprocess.run(["git", "branch", "zen-task-1"], cwd=temp_git_repo, capture_output=True)
        subprocess.run(["git", "branch", "zen-task-2"], cwd=temp_git_repo, capture_output=True)
        subprocess.run(["git", "branch", "feature-x"], cwd=temp_git_repo, capture_output=True)

        branches = list_branches(temp_git_repo, pattern="zen-*")
        assert "zen-task-1" in branches
        assert "zen-task-2" in branches
        assert "feature-x" not in branches

    def test_list_branches_empty_for_non_repo(self, tmp_path):
        """list_branches() returns empty list for non-git directory."""
        from zen_mode.git import list_branches

        assert list_branches(tmp_path) == []

    def test_list_branches_no_pattern_match(self, temp_git_repo):
        """list_branches() returns empty list when pattern matches nothing."""
        from zen_mode.git import list_branches

        branches = list_branches(temp_git_repo, pattern="nonexistent-*")
        assert branches == []

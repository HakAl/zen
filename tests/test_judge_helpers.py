"""
Tests for Judge phase helper functions.
"""
import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, Mock

# Import from package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from zen_mode.core import get_changed_filenames


class TestGetChangedFilenames:
    """Test extraction of changed file names."""

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.BACKUP_DIR')
    def test_git_diff_success(self, mock_backup_dir, mock_run):
        """When git diff succeeds, return file list."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="src/file1.py\nsrc/file2.py\ntests/test_file.py\n"
        )

        result = get_changed_filenames()

        assert result == "src/file1.py\nsrc/file2.py\ntests/test_file.py"
        mock_run.assert_called_once()
        # Verify git diff --name-only was called
        assert mock_run.call_args[0][0] == ["git", "diff", "--name-only", "HEAD"]

    @patch('zen_mode.core.subprocess.run')
    @patch('zen_mode.core.BACKUP_DIR')
    def test_git_diff_empty_output(self, mock_backup_dir, mock_run):
        """When git diff returns empty, fall back to backup."""
        mock_run.return_value = Mock(returncode=0, stdout="")

        # Mock backup directory with no files
        mock_backup_dir.exists.return_value = True
        mock_backup_dir.rglob.return_value = []

        result = get_changed_filenames()

        # Empty git output is returned as-is (stripped to empty string)
        assert result == ""

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


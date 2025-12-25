"""
Security tests for zen-mode.
Tests for path traversal and input sanitization.
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add src to path so zen_mode can be imported
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from zen_mode.core import run


class TestBugPathTraversalVulnerability:
    """BUG: Task file paths are not sanitized, allowing path traversal."""

    @patch('zen_mode.utils.run_claude')  # Mock to prevent actual execution
    @patch('zen_mode.core.shutil.which', return_value='/usr/bin/claude')  # Mock claude binary
    def test_currently_allows_path_outside_project(self, mock_which, mock_claude, tmp_path, monkeypatch, capsys):
        """BUG: Currently allows accessing files outside project root."""
        # Set up a project directory
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Create a task file outside the project (simulating /etc/passwd or similar)
        outside_task = tmp_path / "evil_task.md"
        outside_task.write_text("# Task to read sensitive files")

        # Change to project directory and update PROJECT_ROOT
        monkeypatch.chdir(project_dir)
        import zen_mode.core
        monkeypatch.setattr(zen_mode.core, 'PROJECT_ROOT', project_dir)

        # Mock run_claude to prevent actual execution
        mock_claude.return_value = "mocked output"

        # Currently this DOES NOT raise an error (demonstrating the bug)
        # After fix, this should raise SystemExit
        try:
            run(str(outside_task), flags=set())
            # If we get here, the bug exists (no path validation)
            pytest.fail("BUG CONFIRMED: Path traversal is allowed - no security check!")
        except SystemExit as e:
            # After fix is implemented, we should reach here
            captured = capsys.readouterr()
            if "must be within project" in captured.out or "must be within project" in str(e):
                # Good - path validation is working
                pass
            else:
                # Different error, re-raise
                raise

    @patch('zen_mode.utils.run_claude')
    @patch('zen_mode.core.shutil.which', return_value='/usr/bin/claude')
    def test_currently_allows_parent_directory_traversal(self, mock_which, mock_claude, tmp_path, monkeypatch, capsys):
        """BUG: Currently allows ../ traversal to escape project."""
        # Set up nested structure
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Create a task file outside the project
        outside_task = tmp_path / "evil_task.md"
        outside_task.write_text("# Evil task")

        # Change to project directory and update PROJECT_ROOT
        monkeypatch.chdir(project_dir)
        import zen_mode.core
        monkeypatch.setattr(zen_mode.core, 'PROJECT_ROOT', project_dir)

        # Mock run_claude
        mock_claude.return_value = "mocked output"

        # Currently this DOES NOT raise an error
        try:
            run("../evil_task.md", flags=set())
            # If we get here, the bug exists
            pytest.fail("BUG CONFIRMED: ../ path traversal is allowed!")
        except SystemExit as e:
            # After fix, should get "must be within project" error
            captured = capsys.readouterr()
            if "must be within project" in captured.out or "must be within project" in str(e):
                pass
            else:
                raise

    @patch('zen_mode.utils.run_claude')
    @patch('zen_mode.core.shutil.which', return_value='/usr/bin/claude')
    def test_should_accept_task_file_in_project(self, mock_which, mock_claude, tmp_path, monkeypatch, capsys):
        """After fix: Task files within project should still work."""
        # Set up project directory
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Create a legitimate task file inside the project
        task_file = project_dir / "task.md"
        task_file.write_text("# Legitimate task")

        # Change to project directory and update PROJECT_ROOT
        monkeypatch.chdir(project_dir)
        import zen_mode.core
        monkeypatch.setattr(zen_mode.core, 'PROJECT_ROOT', project_dir)

        # Mock run_claude
        mock_claude.return_value = "mocked output"

        # This should work (not be rejected by path validation)
        try:
            run("task.md", flags=set())
        except SystemExit as e:
            captured = capsys.readouterr()
            # Should not fail due to path validation
            assert "must be within project" not in captured.out
            # It might fail for other reasons (e.g., missing dependencies), that's ok

    @patch('zen_mode.utils.run_claude')
    @patch('zen_mode.core.shutil.which', return_value='/usr/bin/claude')
    def test_should_accept_task_in_subdirectory(self, mock_which, mock_claude, tmp_path, monkeypatch, capsys):
        """After fix: Task files in subdirectories should work."""
        # Set up project directory
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        tasks_dir = project_dir / "tasks"
        tasks_dir.mkdir()

        # Create a task file in a subdirectory
        task_file = tasks_dir / "subtask.md"
        task_file.write_text("# Subtask")

        # Change to project directory and update PROJECT_ROOT
        monkeypatch.chdir(project_dir)
        import zen_mode.core
        monkeypatch.setattr(zen_mode.core, 'PROJECT_ROOT', project_dir)

        # Mock run_claude
        mock_claude.return_value = "mocked output"

        # This should work
        try:
            run("tasks/subtask.md", flags=set())
        except SystemExit as e:
            captured = capsys.readouterr()
            # Should not fail due to path validation
            assert "must be within project" not in captured.out

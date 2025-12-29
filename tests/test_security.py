"""
Security tests for zen-mode.
Tests for path traversal and input sanitization.
"""
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add src to path so zen_mode can be imported
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from zen_mode.core import run
from zen_mode import claude
from zen_mode.exceptions import ConfigError


class TestBugPathTraversalVulnerability:
    """BUG: Task file paths are not sanitized, allowing path traversal."""

    @patch('zen_mode.claude.run_claude')  # Mock to prevent actual execution
    @patch('zen_mode.core.shutil.which', return_value='/usr/bin/claude')  # Mock claude binary
    def test_currently_allows_path_outside_project(self, mock_which, mock_claude, tmp_path, monkeypatch, caplog):
        """BUG: Currently allows accessing files outside project root."""
        import logging
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
        # After fix, this should raise ConfigError
        with caplog.at_level(logging.ERROR, logger="zen_mode"):
            try:
                run(str(outside_task), flags=set())
                # If we get here, the bug exists (no path validation)
                pytest.fail("BUG CONFIRMED: Path traversal is allowed - no security check!")
            except ConfigError as e:
                # After fix is implemented, we should reach here
                # Check that proper error message
                assert "must be within project" in str(e)

    @patch('zen_mode.claude.run_claude')
    @patch('zen_mode.core.shutil.which', return_value='/usr/bin/claude')
    def test_currently_allows_parent_directory_traversal(self, mock_which, mock_claude, tmp_path, monkeypatch, caplog):
        """BUG: Currently allows ../ traversal to escape project."""
        import logging
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
        with caplog.at_level(logging.ERROR, logger="zen_mode"):
            try:
                run("../evil_task.md", flags=set())
                # If we get here, the bug exists
                pytest.fail("BUG CONFIRMED: ../ path traversal is allowed!")
            except ConfigError as e:
                # After fix, should get "must be within project" error
                assert "must be within project" in str(e)

    @patch('zen_mode.claude.run_claude')
    @patch('zen_mode.core.shutil.which', return_value='/usr/bin/claude')
    def test_should_accept_task_file_in_project(self, mock_which, mock_claude, tmp_path, monkeypatch, caplog):
        """After fix: Task files within project should still work."""
        import logging
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
        with caplog.at_level(logging.ERROR, logger="zen_mode"):
            try:
                run("task.md", flags=set())
            except ConfigError as e:
                # Should not fail due to path validation
                assert "must be within project" not in str(e)
                # It might fail for other reasons (e.g., missing dependencies), that's ok
            except Exception:
                # Other exceptions are fine - we only care about path validation
                pass

    @patch('zen_mode.claude.run_claude')
    @patch('zen_mode.core.shutil.which', return_value='/usr/bin/claude')
    def test_should_accept_task_in_subdirectory(self, mock_which, mock_claude, tmp_path, monkeypatch, caplog):
        """After fix: Task files in subdirectories should work."""
        import logging
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
        with caplog.at_level(logging.ERROR, logger="zen_mode"):
            try:
                run("tasks/subtask.md", flags=set())
            except ConfigError as e:
                # Should not fail due to path validation
                assert "must be within project" not in str(e)
            except Exception:
                # Other exceptions are fine - we only care about path validation
                pass


class TestSkipPermissionsEnvVar:
    """Tests for ZEN_SKIP_PERMISSIONS env var gating.

    Note: These tests directly call the module's run_claude bypassing conftest's
    auto-patch by using allow_real_api marker and mocking subprocess.Popen.
    """

    @pytest.mark.allow_real_api
    @patch('zen_mode.claude.subprocess.Popen')
    @patch('zen_mode.claude._init_claude', return_value='/usr/bin/claude')
    def test_skip_permissions_flag_present_by_default(self, mock_init, mock_popen, tmp_path, monkeypatch):
        """By default, --dangerously-skip-permissions SHOULD be in command (zen is autonomous)."""
        # Ensure env var is not set (defaults to true)
        monkeypatch.delenv("ZEN_SKIP_PERMISSIONS", raising=False)

        # Mock process
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ('{"result": "test", "total_cost_usd": 0}', '')
        mock_popen.return_value = mock_proc

        # Reset cached claude exe
        claude._claude_exe = None

        # Call run_claude - directly import to bypass conftest patch
        from zen_mode.claude import run_claude
        run_claude("test prompt", "sonnet", project_root=tmp_path)

        # Check command DOES contain dangerous flag (default behavior)
        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        assert "--dangerously-skip-permissions" in cmd

    @pytest.mark.allow_real_api
    @patch('zen_mode.claude.subprocess.Popen')
    @patch('zen_mode.claude._init_claude', return_value='/usr/bin/claude')
    def test_skip_permissions_flag_absent_when_disabled(self, mock_init, mock_popen, tmp_path, monkeypatch):
        """When ZEN_SKIP_PERMISSIONS=false, flag should NOT be added."""
        # Set env var to false
        monkeypatch.setenv("ZEN_SKIP_PERMISSIONS", "false")

        # Mock process
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ('{"result": "test", "total_cost_usd": 0}', '')
        mock_popen.return_value = mock_proc

        # Reset cached claude exe
        claude._claude_exe = None

        # Call run_claude - directly import to bypass conftest patch
        from zen_mode.claude import run_claude
        run_claude("test prompt", "sonnet", project_root=tmp_path)

        # Check command does NOT contain dangerous flag when disabled
        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        assert "--dangerously-skip-permissions" not in cmd


class TestTrustRoots:
    """Tests for ZEN_TRUST_ROOTS scope-limited trust."""

    def test_no_trust_roots_falls_back_to_skip_permissions_default(self, tmp_path, monkeypatch):
        """Without ZEN_TRUST_ROOTS, falls back to ZEN_SKIP_PERMISSIONS (default true)."""
        monkeypatch.delenv("ZEN_TRUST_ROOTS", raising=False)
        monkeypatch.delenv("ZEN_SKIP_PERMISSIONS", raising=False)

        from zen_mode.claude import is_trusted_directory
        assert is_trusted_directory(tmp_path) is True

    def test_no_trust_roots_respects_skip_permissions_false(self, tmp_path, monkeypatch):
        """Without ZEN_TRUST_ROOTS, ZEN_SKIP_PERMISSIONS=false is respected."""
        monkeypatch.delenv("ZEN_TRUST_ROOTS", raising=False)
        monkeypatch.setenv("ZEN_SKIP_PERMISSIONS", "false")

        from zen_mode.claude import is_trusted_directory
        assert is_trusted_directory(tmp_path) is False

    def test_trust_roots_allows_exact_match(self, tmp_path, monkeypatch):
        """Directory exactly matching a trust root is trusted."""
        monkeypatch.setenv("ZEN_TRUST_ROOTS", str(tmp_path))

        from zen_mode.claude import is_trusted_directory
        assert is_trusted_directory(tmp_path) is True

    def test_trust_roots_allows_subdirectory(self, tmp_path, monkeypatch):
        """Subdirectory of a trust root is trusted."""
        subdir = tmp_path / "project" / "subdir"
        subdir.mkdir(parents=True)
        monkeypatch.setenv("ZEN_TRUST_ROOTS", str(tmp_path))

        from zen_mode.claude import is_trusted_directory
        assert is_trusted_directory(subdir) is True

    def test_trust_roots_rejects_outside_directory(self, tmp_path, monkeypatch):
        """Directory outside all trust roots is not trusted."""
        trusted = tmp_path / "trusted"
        trusted.mkdir()
        untrusted = tmp_path / "untrusted"
        untrusted.mkdir()
        monkeypatch.setenv("ZEN_TRUST_ROOTS", str(trusted))

        from zen_mode.claude import is_trusted_directory
        assert is_trusted_directory(untrusted) is False

    def test_trust_roots_multiple_roots(self, tmp_path, monkeypatch):
        """Multiple trust roots are all checked."""
        root1 = tmp_path / "root1"
        root1.mkdir()
        root2 = tmp_path / "root2"
        root2.mkdir()
        untrusted = tmp_path / "untrusted"
        untrusted.mkdir()

        # Use os.pathsep for platform-appropriate separator
        monkeypatch.setenv("ZEN_TRUST_ROOTS", f"{root1}{os.pathsep}{root2}")

        from zen_mode.claude import is_trusted_directory
        assert is_trusted_directory(root1) is True
        assert is_trusted_directory(root2) is True
        assert is_trusted_directory(untrusted) is False

    def test_trust_roots_ignores_skip_permissions_when_set(self, tmp_path, monkeypatch):
        """When ZEN_TRUST_ROOTS is set, ZEN_SKIP_PERMISSIONS is ignored."""
        trusted = tmp_path / "trusted"
        trusted.mkdir()
        untrusted = tmp_path / "untrusted"
        untrusted.mkdir()

        # Even with SKIP_PERMISSIONS=true, untrusted dir should be rejected
        monkeypatch.setenv("ZEN_TRUST_ROOTS", str(trusted))
        monkeypatch.setenv("ZEN_SKIP_PERMISSIONS", "true")

        from zen_mode.claude import is_trusted_directory
        assert is_trusted_directory(trusted) is True
        assert is_trusted_directory(untrusted) is False

    @pytest.mark.allow_real_api
    @patch('zen_mode.claude.subprocess.Popen')
    @patch('zen_mode.claude._init_claude', return_value='/usr/bin/claude')
    def test_trust_roots_integration_trusted_dir(self, mock_init, mock_popen, tmp_path, monkeypatch):
        """Integration: run_claude adds flag when in trusted directory."""
        monkeypatch.setenv("ZEN_TRUST_ROOTS", str(tmp_path))

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ('{"result": "test", "total_cost_usd": 0}', '')
        mock_popen.return_value = mock_proc

        claude._claude_exe = None
        from zen_mode.claude import run_claude
        run_claude("test", "sonnet", project_root=tmp_path)

        cmd = mock_popen.call_args[0][0]
        assert "--dangerously-skip-permissions" in cmd

    @pytest.mark.allow_real_api
    @patch('zen_mode.claude.subprocess.Popen')
    @patch('zen_mode.claude._init_claude', return_value='/usr/bin/claude')
    def test_trust_roots_integration_untrusted_dir(self, mock_init, mock_popen, tmp_path, monkeypatch):
        """Integration: run_claude omits flag when outside trust roots."""
        trusted = tmp_path / "trusted"
        trusted.mkdir()
        untrusted = tmp_path / "untrusted"
        untrusted.mkdir()
        monkeypatch.setenv("ZEN_TRUST_ROOTS", str(trusted))

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ('{"result": "test", "total_cost_usd": 0}', '')
        mock_popen.return_value = mock_proc

        claude._claude_exe = None
        from zen_mode.claude import run_claude
        run_claude("test", "sonnet", project_root=untrusted)

        cmd = mock_popen.call_args[0][0]
        assert "--dangerously-skip-permissions" not in cmd

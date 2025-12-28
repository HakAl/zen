"""
Tests for CLI module.

Tests cmd_init, cmd_run dispatch, main() argument parsing.
"""
import logging
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from zen_mode.cli import cmd_init, cmd_run, main, setup_logging
from zen_mode import __version__


class TestCmdInit:
    """Tests for cmd_init() function."""

    def test_creates_zen_directory(self, tmp_path, monkeypatch):
        """cmd_init creates .zen directory."""
        monkeypatch.chdir(tmp_path)

        cmd_init(SimpleNamespace())

        zen_dir = tmp_path / ".zen"
        assert zen_dir.exists()
        assert zen_dir.is_dir()

    def test_creates_claude_md(self, tmp_path, monkeypatch):
        """cmd_init creates CLAUDE.md if not exists."""
        monkeypatch.chdir(tmp_path)

        cmd_init(SimpleNamespace())

        claude_md = tmp_path / "CLAUDE.md"
        assert claude_md.exists()
        # Should contain some content from template
        content = claude_md.read_text()
        assert len(content) > 0

    def test_idempotent(self, tmp_path, monkeypatch):
        """Running cmd_init twice doesn't error."""
        monkeypatch.chdir(tmp_path)

        # First run
        cmd_init(SimpleNamespace())

        # Second run should not raise
        cmd_init(SimpleNamespace())

        assert (tmp_path / ".zen").exists()

    def test_does_not_overwrite_existing_claude_md(self, tmp_path, monkeypatch):
        """cmd_init preserves existing CLAUDE.md."""
        monkeypatch.chdir(tmp_path)

        # Create existing CLAUDE.md with custom content
        claude_md = tmp_path / "CLAUDE.md"
        custom_content = "# My Custom Rules\n\nDo not touch this."
        claude_md.write_text(custom_content)

        cmd_init(SimpleNamespace())

        # Content should be unchanged
        assert claude_md.read_text() == custom_content


class TestMain:
    """Tests for main() function argument parsing."""

    def test_no_args_shows_help(self, capsys):
        """Running with no args shows usage info."""
        with patch.object(sys, 'argv', ['zen']):
            main()

        captured = capsys.readouterr()
        assert "Usage:" in captured.out
        assert "zen init" in captured.out
        assert "zen <task.md>" in captured.out

    def test_version_flag(self, capsys):
        """--version shows version number."""
        with patch.object(sys, 'argv', ['zen', '--version']):
            main()

        captured = capsys.readouterr()
        assert __version__ in captured.out

    def test_version_flag_short(self, capsys):
        """-V shows version number."""
        with patch.object(sys, 'argv', ['zen', '-V']):
            main()

        captured = capsys.readouterr()
        assert __version__ in captured.out

    def test_init_subcommand(self, tmp_path, monkeypatch):
        """'zen init' calls cmd_init."""
        monkeypatch.chdir(tmp_path)

        with patch.object(sys, 'argv', ['zen', 'init']):
            main()

        assert (tmp_path / ".zen").exists()

    def test_help_flag(self, capsys):
        """--help shows help text."""
        with patch.object(sys, 'argv', ['zen', '--help']):
            main()

        captured = capsys.readouterr()
        assert "Usage:" in captured.out

    def test_invalid_subcommand_as_task_file(self, tmp_path, monkeypatch, capsys):
        """Invalid subcommand is treated as task file path."""
        monkeypatch.chdir(tmp_path)

        # zen some_nonexistent_file.md should try to run it as task
        # which will fail because core.run will be called on non-existent file
        with patch.object(sys, 'argv', ['zen', 'nonexistent.md']):
            with patch('zen_mode.core.run') as mock_run:
                main()
                # Should call core.run with the task file
                mock_run.assert_called_once()
                args = mock_run.call_args[0]
                assert args[0] == 'nonexistent.md'


class TestCmdRun:
    """Tests for cmd_run() function."""

    def test_local_zenpy_warning_shown_non_interactive(self, tmp_path, monkeypatch, capsys):
        """When local zen.py exists, shows warning in non-interactive mode."""
        monkeypatch.chdir(tmp_path)

        # Create a local zen.py
        local_zen = tmp_path / "zen.py"
        local_zen.write_text("# local override")

        args = SimpleNamespace(
            task_file="task.md",
            reset=False,
            retry=False,
            skip_judge=False,
            skip_verify=False,
            scout_context=None,
            allowed_files=None,
            trust_local=False,
        )

        # Mock stdin.isatty to return False (non-interactive)
        with patch.object(sys.stdin, 'isatty', return_value=False):
            with pytest.raises(SystemExit) as exc_info:
                cmd_run(args)

        # Should exit with error because can't confirm in non-interactive
        assert exc_info.value.code == 1

    def test_local_zenpy_with_trust_local(self, tmp_path, monkeypatch):
        """When --trust-local is set, executes local zen.py."""
        monkeypatch.chdir(tmp_path)

        # Create a local zen.py
        local_zen = tmp_path / "zen.py"
        local_zen.write_text("import sys; sys.exit(42)")

        args = SimpleNamespace(
            task_file="task.md",
            reset=False,
            retry=False,
            skip_judge=False,
            skip_verify=False,
            scout_context=None,
            allowed_files=None,
            trust_local=True,
        )

        with pytest.raises(SystemExit) as exc_info:
            cmd_run(args)

        # Should exit with whatever the local zen.py returns
        assert exc_info.value.code == 42

    def test_runs_core_when_no_local_zenpy(self, tmp_path, monkeypatch):
        """When no local zen.py, runs via core module."""
        monkeypatch.chdir(tmp_path)

        args = SimpleNamespace(
            task_file="task.md",
            reset=False,
            retry=False,
            skip_judge=False,
            skip_verify=False,
            scout_context=None,
            allowed_files=None,
            trust_local=False,
        )

        with patch('zen_mode.core.run') as mock_run:
            cmd_run(args)

            mock_run.assert_called_once()
            call_args, call_kwargs = mock_run.call_args
            assert call_args[0] == "task.md"

    def test_passes_flags_to_core(self, tmp_path, monkeypatch):
        """Flags are passed correctly to core.run."""
        monkeypatch.chdir(tmp_path)

        args = SimpleNamespace(
            task_file="task.md",
            reset=True,
            retry=True,
            skip_judge=True,
            skip_verify=True,
            scout_context="scout.md",
            allowed_files="src/*.py",
            trust_local=False,
        )

        with patch('zen_mode.core.run') as mock_run:
            cmd_run(args)

            call_args, call_kwargs = mock_run.call_args
            flags = call_args[1]
            assert "--reset" in flags
            assert "--retry" in flags
            assert "--skip-judge" in flags
            assert "--skip-verify" in flags
            assert call_kwargs.get('scout_context') == "scout.md"
            assert call_kwargs.get('allowed_files') == "src/*.py"


class TestSetupLogging:
    """Tests for setup_logging() function."""

    def test_verbose_sets_debug_level(self):
        """Verbose mode sets DEBUG level."""
        setup_logging(verbose=True)
        logger = logging.getLogger("zen_mode")
        assert logger.level == logging.DEBUG

    def test_non_verbose_sets_info_level(self):
        """Non-verbose mode sets INFO level."""
        setup_logging(verbose=False)
        logger = logging.getLogger("zen_mode")
        assert logger.level == logging.INFO

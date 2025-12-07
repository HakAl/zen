"""
Tests for zen-mode CLI.
Unit tests that don't spawn subprocesses.
"""
import sys
from pathlib import Path

import pytest

# Add src to path so zen_mode can be imported
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from zen_mode import __version__
from zen_mode.cli import cmd_init, cmd_eject


class TestVersion:
    def test_version_exists(self):
        assert __version__ == "0.1.0"


class TestCmdInit:
    def test_creates_zen_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        class Args:
            pass

        cmd_init(Args())
        assert (tmp_path / ".zen").exists()

    def test_creates_claude_md_if_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        class Args:
            pass

        cmd_init(Args())
        assert (tmp_path / "CLAUDE.md").exists()

    def test_does_not_overwrite_existing_claude_md(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        existing = "# My existing CLAUDE.md"
        (tmp_path / "CLAUDE.md").write_text(existing)

        class Args:
            pass

        cmd_init(Args())
        assert (tmp_path / "CLAUDE.md").read_text() == existing


class TestCmdEject:
    def test_creates_files(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        class Args:
            pass

        cmd_eject(Args())
        assert (tmp_path / "zen.py").exists()
        assert (tmp_path / "zen_lint.py").exists()

    def test_ejected_zen_has_main_block(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        class Args:
            pass

        cmd_eject(Args())
        content = (tmp_path / "zen.py").read_text(encoding="utf-8")
        assert 'if __name__ == "__main__"' in content

    def test_ejected_zen_imports_local_linter(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        class Args:
            pass

        cmd_eject(Args())
        content = (tmp_path / "zen.py").read_text(encoding="utf-8")
        assert "import zen_lint as linter" in content

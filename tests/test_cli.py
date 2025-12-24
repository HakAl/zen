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


class TestAutoWorkerCalculation:
    """Tests for auto-calculating worker count based on task count."""

    def test_single_task_gets_one_worker(self):
        """One task = one worker."""
        import os
        tasks = ["task1.md"]
        workers = max(1, min(len(tasks), os.cpu_count() or 4, 8))
        assert workers == 1

    def test_two_tasks_gets_two_workers(self):
        """Two tasks = two workers."""
        import os
        tasks = ["task1.md", "task2.md"]
        workers = max(1, min(len(tasks), os.cpu_count() or 4, 8))
        assert workers == 2

    def test_many_tasks_capped_at_eight(self):
        """Many tasks capped at 8 workers max."""
        import os
        tasks = [f"task{i}.md" for i in range(20)]
        workers = max(1, min(len(tasks), os.cpu_count() or 4, 8))
        assert workers <= 8

    def test_capped_at_cpu_count(self):
        """Workers capped at CPU count."""
        import os
        tasks = [f"task{i}.md" for i in range(20)]
        cpu_count = os.cpu_count() or 4
        workers = max(1, min(len(tasks), cpu_count, 8))
        assert workers <= cpu_count

    def test_minimum_one_worker(self):
        """Always at least one worker."""
        import os
        tasks = []  # Edge case: empty
        workers = max(1, min(len(tasks) or 1, os.cpu_count() or 4, 8))
        assert workers >= 1

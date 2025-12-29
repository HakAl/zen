"""Tests for zen_mode.files module."""
import pytest
from pathlib import Path

from zen_mode.files import (
    should_ignore_path,
    write_file,
    backup_file,
    log,
    IGNORE_DIRS,
    IGNORE_FILES,
    BINARY_EXTS,
)
# Note: load_constitution and get_full_constitution tests are in test_constitution.py


class TestShouldIgnorePath:
    """Tests for should_ignore_path() function."""

    def test_ignores_node_modules(self):
        assert should_ignore_path("node_modules/package/index.js") is True

    def test_ignores_pycache(self):
        assert should_ignore_path("src/__pycache__/module.pyc") is True

    def test_ignores_hidden_directories(self):
        assert should_ignore_path(".hidden/file.py") is True

    def test_ignores_git_directory(self):
        assert should_ignore_path(".git/objects/abc") is True

    def test_ignores_venv(self):
        assert should_ignore_path("venv/lib/python3.9/site.py") is True

    def test_ignores_build_directory(self):
        assert should_ignore_path("build/output/main.exe") is True

    def test_ignores_dist_directory(self):
        assert should_ignore_path("dist/bundle.js") is True

    def test_ignores_package_lock(self):
        assert should_ignore_path("package-lock.json") is True

    def test_ignores_ds_store(self):
        assert should_ignore_path(".DS_Store") is True

    def test_ignores_license_file(self):
        assert should_ignore_path("LICENSE") is True

    def test_ignores_png_files(self):
        assert should_ignore_path("images/logo.png") is True

    def test_ignores_jpg_files(self):
        assert should_ignore_path("assets/photo.jpg") is True

    def test_ignores_zip_files(self):
        assert should_ignore_path("downloads/archive.zip") is True

    def test_ignores_exe_files(self):
        assert should_ignore_path("bin/program.exe") is True

    def test_allows_normal_python_file(self):
        assert should_ignore_path("src/main.py") is False

    def test_allows_normal_js_file(self):
        assert should_ignore_path("src/app.js") is False

    def test_allows_normal_ts_file(self):
        assert should_ignore_path("components/Button.tsx") is False

    def test_allows_test_file(self):
        assert should_ignore_path("tests/test_main.py") is False

    def test_allows_readme(self):
        assert should_ignore_path("README.md") is False

    def test_ignores_egg_info_glob(self):
        assert should_ignore_path("mypackage.egg-info/PKG-INFO") is True

    def test_ignores_zen_directory(self):
        assert should_ignore_path(".zen/scout.md") is True


class TestWriteFile:
    """Tests for write_file() function."""

    def test_writes_new_file(self, tmp_path):
        target = tmp_path / "output.txt"
        write_file(target, "content")
        assert target.read_text() == "content"

    def test_overwrites_existing_file(self, tmp_path):
        target = tmp_path / "output.txt"
        target.write_text("old content")
        write_file(target, "new content")
        assert target.read_text() == "new content"

    def test_creates_parent_directories(self, tmp_path):
        target = tmp_path / "deep" / "nested" / "file.txt"
        write_file(target, "nested content")
        assert target.read_text() == "nested content"

    def test_uses_work_dir_for_temp(self, tmp_path):
        work_dir = tmp_path / "work"
        target = tmp_path / "output.txt"
        write_file(target, "content", work_dir=work_dir)
        assert target.read_text() == "content"
        assert work_dir.exists()

    def test_writes_utf8_content(self, tmp_path):
        target = tmp_path / "unicode.txt"
        write_file(target, "Hello 世界 🌍")
        assert target.read_text(encoding="utf-8") == "Hello 世界 🌍"


class TestBackupFile:
    """Tests for backup_file() function."""

    def test_creates_backup(self, tmp_path):
        src = tmp_path / "source.txt"
        src.write_text("original content")
        backup_dir = tmp_path / "backups"

        backup_file(src, backup_dir, tmp_path)

        backup_path = backup_dir / "source.txt"
        assert backup_path.exists()
        assert backup_path.read_text() == "original content"

    def test_preserves_directory_structure(self, tmp_path):
        subdir = tmp_path / "sub" / "dir"
        subdir.mkdir(parents=True)
        src = subdir / "file.txt"
        src.write_text("nested content")
        backup_dir = tmp_path / "backups"

        backup_file(src, backup_dir, tmp_path)

        backup_path = backup_dir / "sub" / "dir" / "file.txt"
        assert backup_path.exists()

    def test_skips_if_already_backed_up(self, tmp_path):
        src = tmp_path / "source.txt"
        src.write_text("original")
        backup_dir = tmp_path / "backups"

        # First backup
        backup_file(src, backup_dir, tmp_path)
        backup_path = backup_dir / "source.txt"
        original_mtime = backup_path.stat().st_mtime

        # Modify source and try backup again
        src.write_text("modified")
        backup_file(src, backup_dir, tmp_path)

        # Backup should not be overwritten
        assert backup_path.read_text() == "original"

    def test_skips_nonexistent_file(self, tmp_path):
        nonexistent = tmp_path / "ghost.txt"
        backup_dir = tmp_path / "backups"

        backup_file(nonexistent, backup_dir, tmp_path)

        assert not backup_dir.exists()

    def test_calls_log_fn(self, tmp_path):
        src = tmp_path / "source.txt"
        src.write_text("content")
        backup_dir = tmp_path / "backups"
        messages = []

        backup_file(src, backup_dir, tmp_path, log_fn=lambda m: messages.append(m))

        assert len(messages) == 1
        assert "BACKUP" in messages[0]


class TestLog:
    """Tests for log() function."""

    def test_writes_to_log_file(self, tmp_path):
        log_file = tmp_path / "test.log"
        work_dir = tmp_path / "work"

        log("Test message", log_file, work_dir)

        content = log_file.read_text()
        assert "Test message" in content

    def test_includes_timestamp(self, tmp_path):
        log_file = tmp_path / "test.log"
        work_dir = tmp_path / "work"

        log("Message", log_file, work_dir)

        content = log_file.read_text()
        # Should have [HH:MM:SS] format
        assert "[" in content and "]" in content

    def test_creates_work_dir(self, tmp_path):
        log_file = tmp_path / "test.log"
        work_dir = tmp_path / "nonexistent_work"

        log("Message", log_file, work_dir)

        assert work_dir.exists()

    def test_appends_multiple_messages(self, tmp_path):
        log_file = tmp_path / "test.log"
        work_dir = tmp_path / "work"

        log("First", log_file, work_dir)
        log("Second", log_file, work_dir)

        content = log_file.read_text()
        assert "First" in content
        assert "Second" in content


class TestConstants:
    """Tests for module constants."""

    def test_ignore_dirs_contains_common_dirs(self):
        assert "node_modules" in IGNORE_DIRS
        assert ".git" in IGNORE_DIRS
        assert "__pycache__" in IGNORE_DIRS
        assert "venv" in IGNORE_DIRS

    def test_ignore_files_contains_lock_files(self):
        assert "package-lock.json" in IGNORE_FILES
        assert "yarn.lock" in IGNORE_FILES
        assert "poetry.lock" in IGNORE_FILES

    def test_binary_exts_contains_images(self):
        assert ".png" in BINARY_EXTS
        assert ".jpg" in BINARY_EXTS
        assert ".gif" in BINARY_EXTS

    def test_binary_exts_contains_archives(self):
        assert ".zip" in BINARY_EXTS
        assert ".tar" in BINARY_EXTS
        assert ".gz" in BINARY_EXTS

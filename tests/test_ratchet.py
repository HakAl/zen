"""Tests for zen_mode.ratchet module."""
import json
import pytest
from pathlib import Path

from zen_mode.ratchet import (
    _make_key,
    _parse_key,
    capture_baseline,
    load_baseline,
    Baseline,
)


class TestKeyFunctions:
    """Test key serialization helpers."""

    def test_make_key_simple(self):
        assert _make_key("file.py", "TODO") == "file.py::TODO"

    def test_make_key_with_path(self):
        assert _make_key("src/utils/file.py", "API_KEY") == "src/utils/file.py::API_KEY"

    def test_parse_key_simple(self):
        assert _parse_key("file.py::TODO") == ("file.py", "TODO")

    def test_parse_key_with_path(self):
        assert _parse_key("src/utils/file.py::API_KEY") == ("src/utils/file.py", "API_KEY")

    def test_parse_key_no_separator(self):
        # Edge case: malformed key
        assert _parse_key("no_separator") == ("no_separator", "")

    def test_roundtrip(self):
        """Key should survive make->parse roundtrip."""
        file, rule = "src/deep/nested/file.py", "HARDCODED_IP"
        key = _make_key(file, rule)
        parsed_file, parsed_rule = _parse_key(key)
        assert parsed_file == file
        assert parsed_rule == rule


class TestCaptureBaselineEmpty:
    """Test capture_baseline with no files."""

    def test_empty_paths_returns_empty(self, tmp_path):
        baseline_file = tmp_path / "baseline.json"
        result = capture_baseline([], baseline_file)
        assert result == {}
        assert not baseline_file.exists()

    def test_nonexistent_files_returns_empty(self, tmp_path):
        baseline_file = tmp_path / "baseline.json"
        result = capture_baseline(["/nonexistent/file.py"], baseline_file)
        assert result == {}

    def test_logs_no_files(self, tmp_path):
        baseline_file = tmp_path / "baseline.json"
        logs = []
        capture_baseline([], baseline_file, log_fn=logs.append)
        assert any("No files" in msg for msg in logs)


class TestCaptureBaselineClean:
    """Test capture_baseline with clean files."""

    def test_clean_file_returns_empty_baseline(self, tmp_path):
        # Create a clean Python file
        clean_file = tmp_path / "clean.py"
        clean_file.write_text("def hello():\n    return 'world'\n")

        baseline_file = tmp_path / "baseline.json"
        result = capture_baseline([str(clean_file)], baseline_file)

        assert result == {}
        # File should still be written (empty baseline)
        assert baseline_file.exists()
        assert json.loads(baseline_file.read_text()) == {}

    def test_logs_clean(self, tmp_path):
        clean_file = tmp_path / "clean.py"
        clean_file.write_text("def hello():\n    return 'world'\n")

        baseline_file = tmp_path / "baseline.json"
        logs = []
        capture_baseline([str(clean_file)], baseline_file, log_fn=logs.append)
        assert any("Clean" in msg or "no pre-existing" in msg for msg in logs)


class TestCaptureBaselineWithViolations:
    """Test capture_baseline with files containing violations."""

    def test_captures_todo(self, tmp_path):
        file_with_todo = tmp_path / "has_todo.py"
        file_with_todo.write_text("# TODO: fix this\ndef foo(): pass\n")

        baseline_file = tmp_path / "baseline.json"
        result = capture_baseline([str(file_with_todo)], baseline_file)

        # Should have captured the TODO violation
        assert len(result) >= 1
        assert any("TODO" in key for key in result)

    def test_captures_multiple_same_rule(self, tmp_path):
        file_with_todos = tmp_path / "many_todos.py"
        file_with_todos.write_text("# TODO: first\n# TODO: second\n# TODO: third\n")

        baseline_file = tmp_path / "baseline.json"
        result = capture_baseline([str(file_with_todos)], baseline_file)

        # Count should be 3 for the same (file, rule) pair
        todo_keys = [k for k in result if "TODO" in k]
        assert len(todo_keys) == 1
        assert result[todo_keys[0]] == 3

    def test_captures_multiple_rules(self, tmp_path):
        file = tmp_path / "mixed.py"
        file.write_text("# TODO: task\n# FIXME: bug\n")

        baseline_file = tmp_path / "baseline.json"
        result = capture_baseline([str(file)], baseline_file)

        # Should have both TODO and FIXME
        assert any("TODO" in k for k in result)
        assert any("FIXME" in k for k in result)

    def test_captures_from_multiple_files(self, tmp_path):
        file1 = tmp_path / "file1.py"
        file1.write_text("# TODO: in file1\n")

        file2 = tmp_path / "file2.py"
        file2.write_text("# FIXME: in file2\n")

        baseline_file = tmp_path / "baseline.json"
        result = capture_baseline([str(file1), str(file2)], baseline_file)

        # Should have violations from both files
        keys = list(result.keys())
        assert len(keys) == 2
        assert any("file1" in k for k in keys)
        assert any("file2" in k for k in keys)

    def test_writes_json_file(self, tmp_path):
        file = tmp_path / "has_todo.py"
        file.write_text("# TODO: fix\n")

        baseline_file = tmp_path / "baseline.json"
        capture_baseline([str(file)], baseline_file)

        assert baseline_file.exists()
        data = json.loads(baseline_file.read_text())
        assert isinstance(data, dict)
        assert len(data) >= 1

    def test_logs_violation_count(self, tmp_path):
        file = tmp_path / "has_todo.py"
        file.write_text("# TODO: one\n# TODO: two\n")

        baseline_file = tmp_path / "baseline.json"
        logs = []
        capture_baseline([str(file)], baseline_file, log_fn=logs.append)

        assert any("2 pre-existing" in msg for msg in logs)

    def test_creates_parent_directory(self, tmp_path):
        file = tmp_path / "test.py"
        file.write_text("# TODO: test\n")

        # Baseline file in nested directory that doesn't exist
        baseline_file = tmp_path / "nested" / "deep" / "baseline.json"
        capture_baseline([str(file)], baseline_file)

        assert baseline_file.exists()


class TestLoadBaseline:
    """Test load_baseline function."""

    def test_missing_file_returns_empty(self, tmp_path):
        baseline_file = tmp_path / "nonexistent.json"
        result = load_baseline(baseline_file)
        assert result == {}

    def test_valid_json_file(self, tmp_path):
        baseline_file = tmp_path / "baseline.json"
        data = {"file.py::TODO": 3, "other.py::FIXME": 1}
        baseline_file.write_text(json.dumps(data))

        result = load_baseline(baseline_file)
        assert result == data

    def test_invalid_json_returns_empty(self, tmp_path):
        baseline_file = tmp_path / "baseline.json"
        baseline_file.write_text("not valid json {{{")

        result = load_baseline(baseline_file)
        assert result == {}

    def test_empty_file_returns_empty(self, tmp_path):
        baseline_file = tmp_path / "baseline.json"
        baseline_file.write_text("")

        result = load_baseline(baseline_file)
        assert result == {}


class TestBaselineIntegration:
    """Integration tests for baseline capture and load."""

    def test_capture_then_load_roundtrip(self, tmp_path):
        file = tmp_path / "code.py"
        file.write_text("# TODO: item1\n# TODO: item2\n# FIXME: bug\n")

        baseline_file = tmp_path / "baseline.json"
        captured = capture_baseline([str(file)], baseline_file)

        loaded = load_baseline(baseline_file)
        assert loaded == captured

    def test_multiple_captures_overwrite(self, tmp_path):
        file = tmp_path / "code.py"
        file.write_text("# TODO: original\n")

        baseline_file = tmp_path / "baseline.json"
        capture_baseline([str(file)], baseline_file)

        # Modify file and recapture
        file.write_text("# TODO: one\n# TODO: two\n# TODO: three\n")
        capture_baseline([str(file)], baseline_file)

        loaded = load_baseline(baseline_file)
        todo_keys = [k for k in loaded if "TODO" in k]
        assert loaded[todo_keys[0]] == 3  # New count, not old

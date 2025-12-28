"""
Tests for detect_no_tests() and project_has_tests() - detecting when no tests exist.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from zen_mode.verify import detect_no_tests, project_has_tests
import zen_mode.verify as verify


class TestPytestNoTests:
    """Detect no tests from pytest output."""

    def test_no_tests_ran(self):
        output = "no tests ran"
        assert detect_no_tests(output) is True

    def test_collected_0_items(self):
        output = """
============================= test session starts ==============================
collected 0 items

============================= no tests ran in 0.01s =============================
"""
        assert detect_no_tests(output) is True

    def test_no_tests_collected(self):
        output = "no tests collected"
        assert detect_no_tests(output) is True


class TestJestNoTests:
    """Detect no tests from Jest output."""

    def test_no_tests_found(self):
        output = "No tests found"
        assert detect_no_tests(output) is True

    def test_zero_test_suites(self):
        output = "Test Suites: 0 total"
        assert detect_no_tests(output) is True


class TestCargoNoTests:
    """Detect no tests from cargo test output."""

    def test_running_0_tests(self):
        output = "running 0 tests"
        assert detect_no_tests(output) is True

    def test_zero_all(self):
        output = "test result: ok. 0 passed; 0 failed; 0 ignored"
        assert detect_no_tests(output) is True


class TestGoNoTests:
    """Detect no tests from Go test output."""

    def test_no_test_files(self):
        output = "?   \texample.com/foo\t[no test files]"
        assert detect_no_tests(output) is True

    def test_no_test_files_simple(self):
        output = "no test files"
        assert detect_no_tests(output) is True


class TestGenericNoTests:
    """Generic patterns for no tests."""

    def test_zero_tests(self):
        output = "0 tests"
        assert detect_no_tests(output) is True

    def test_no_tests_found(self):
        output = "no tests found"
        assert detect_no_tests(output) is True

    def test_no_tests_exist(self):
        output = "no tests exist"
        assert detect_no_tests(output) is True

    def test_no_test_defined(self):
        output = "no test defined"
        assert detect_no_tests(output) is True


class TestShouldNotMatch:
    """Cases that should NOT be detected as 'no tests'."""

    def test_normal_pass(self):
        output = "10 passed in 2.5s"
        assert detect_no_tests(output) is False

    def test_failures(self):
        output = "3 failed, 7 passed"
        assert detect_no_tests(output) is False

    def test_empty_string(self):
        assert detect_no_tests("") is False

    def test_unrelated_output(self):
        output = "Build completed successfully"
        assert detect_no_tests(output) is False


class TestProjectHasTests:
    """Tests for project_has_tests() filesystem detection."""

    def test_detects_tests_dir(self, tmp_path):
        """Detects tests/ directory."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_foo.py").touch()
        assert project_has_tests(tmp_path) is True

    def test_detects_test_file_pattern(self, tmp_path):
        """Detects test_*.py files."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "test_utils.py").touch()
        assert project_has_tests(tmp_path) is True

    def test_detects_spec_file(self, tmp_path):
        """Detects *.spec.js files."""
        (tmp_path / "Button.spec.js").touch()
        assert project_has_tests(tmp_path) is True

    def test_no_tests_empty_project(self, tmp_path):
        """Returns False for empty project."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").touch()
        assert project_has_tests(tmp_path) is False

    def test_no_tests_code_only(self, tmp_path):
        """Returns False when only code files exist."""
        (tmp_path / "app.py").touch()
        (tmp_path / "utils.py").touch()
        (tmp_path / "config.json").touch()
        assert project_has_tests(tmp_path) is False

    def test_skips_node_modules(self, tmp_path):
        """Skips node_modules even if it contains test files."""
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "test_foo.py").touch()
        (tmp_path / "app.js").touch()
        assert project_has_tests(tmp_path) is False

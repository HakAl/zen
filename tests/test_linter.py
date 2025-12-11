"""Tests for zen_mode.linter behavior."""
import pytest
from pathlib import Path

from zen_mode.linter import (
    check_file,
    run_lint,
    split_code_comment,
    find_string_ranges,
    is_binary,
    IGNORE_DIRS,
    IGNORE_FILES,
    IGNORE_EXTS,
    TEST_EXEMPT_RULES,
    TEST_FILE_PATTERNS,
)


class TestIgnoreDirs:
    """Test that IGNORE_DIRS skips expected directories."""

    def test_zen_in_ignore_dirs(self):
        assert ".zen" in IGNORE_DIRS

    def test_git_in_ignore_dirs(self):
        assert ".git" in IGNORE_DIRS

    def test_node_modules_in_ignore_dirs(self):
        assert "node_modules" in IGNORE_DIRS

    def test_pycache_in_ignore_dirs(self):
        assert "__pycache__" in IGNORE_DIRS

    def test_venv_in_ignore_dirs(self):
        assert "venv" in IGNORE_DIRS


class TestIgnoreFiles:
    """Test that IGNORE_FILES skips expected files."""

    def test_package_lock_ignored(self):
        assert "package-lock.json" in IGNORE_FILES

    def test_env_files_ignored(self):
        assert ".env" in IGNORE_FILES
        assert ".env.local" in IGNORE_FILES

    def test_license_ignored(self):
        assert "LICENSE" in IGNORE_FILES


class TestIgnoreExts:
    """Test that IGNORE_EXTS skips expected extensions."""

    def test_images_ignored(self):
        assert ".png" in IGNORE_EXTS
        assert ".jpg" in IGNORE_EXTS

    def test_markdown_ignored(self):
        assert ".md" in IGNORE_EXTS

    def test_binaries_ignored(self):
        assert ".exe" in IGNORE_EXTS
        assert ".dll" in IGNORE_EXTS


class TestTestFilePatterns:
    """Test that TEST_FILE_PATTERNS matches test files correctly."""

    def test_test_prefix_file(self):
        # Pattern requires path separator before test_
        assert TEST_FILE_PATTERNS.search("/test_routes.py")
        assert TEST_FILE_PATTERNS.search("src/test_routes.py")

    def test_test_suffix_file(self):
        # *_test.ext pattern
        assert TEST_FILE_PATTERNS.search("routes_test.py")
        assert TEST_FILE_PATTERNS.search("src/routes_test.py")

    def test_tests_directory(self):
        assert TEST_FILE_PATTERNS.search("api/tests/test_routes.py")
        assert TEST_FILE_PATTERNS.search("tests/unit/foo.py")
        assert TEST_FILE_PATTERNS.search("/tests/foo.py")

    def test_spec_directory(self):
        assert TEST_FILE_PATTERNS.search("spec/models/user_spec.rb")
        assert TEST_FILE_PATTERNS.search("/spec/foo.rb")

    def test_jest_test_file(self):
        # *.test.ext and *.spec.ext patterns
        assert TEST_FILE_PATTERNS.search("Button.test.js")
        assert TEST_FILE_PATTERNS.search("utils.spec.ts")
        assert TEST_FILE_PATTERNS.search("src/Button.test.js")

    def test_dunder_tests_directory(self):
        assert TEST_FILE_PATTERNS.search("__tests__/Button.js")
        assert TEST_FILE_PATTERNS.search("src/__tests__/foo.js")

    def test_regular_file_no_match(self):
        assert not TEST_FILE_PATTERNS.search("src/routes.py")
        assert not TEST_FILE_PATTERNS.search("lib/utils.js")
        assert not TEST_FILE_PATTERNS.search("config.py")

    def test_testimony_not_matched(self):
        # "testimony" contains "test" but shouldn't match
        assert not TEST_FILE_PATTERNS.search("src/testimony.py")

    def test_pytest_temp_dir_not_matched(self):
        # pytest creates dirs like test_foo0/ - these shouldn't match
        # unless followed by another path separator (making it a test dir)
        assert not TEST_FILE_PATTERNS.search("test_foo0/config.py")


class TestTestExemptRules:
    """Test that TEST_EXEMPT_RULES contains expected rules."""

    def test_api_key_exempt(self):
        assert "API_KEY" in TEST_EXEMPT_RULES

    def test_possible_secret_exempt(self):
        assert "POSSIBLE_SECRET" in TEST_EXEMPT_RULES

    def test_example_data_exempt(self):
        assert "EXAMPLE_DATA" in TEST_EXEMPT_RULES


class TestCheckFileHighSeverity:
    """Test HIGH severity rule detection."""

    def test_detects_placeholder(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text('api_key = "YOUR_KEY_HERE"\n')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        assert "PLACEHOLDER" in rules

    def test_detects_conflict_marker(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text('<<<<<<< HEAD\nsome code\n')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        assert "CONFLICT_MARKER" in rules

    def test_detects_truncation_marker(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text('def foo():\n    ... rest of implementation\n')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        assert "TRUNCATION_MARKER" in rules

    def test_detects_incomplete_impl(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text('def foo():\n    # TODO: implement this\n    pass\n')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        assert "INCOMPLETE_IMPL" in rules

    def test_detects_overly_generic_except(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text('try:\n    foo()\nexcept:\n    pass\n')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        assert "OVERLY_GENERIC_EXCEPT" in rules


class TestCheckFileMediumSeverity:
    """Test MEDIUM severity rule detection."""

    def test_detects_todo_in_comment(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text('x = 1  # TODO fix later\n')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        assert "TODO" in rules

    def test_detects_fixme(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text('# FIXME: broken\nx = 1\n')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        assert "FIXME" in rules

    def test_detects_stub_impl(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text('def foo():\n    pass\n')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        assert "STUB_IMPL" in rules

    def test_detects_not_implemented(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text('def foo():\n    raise NotImplementedError\n')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        assert "NOT_IMPLEMENTED" in rules


class TestCheckFileLowSeverity:
    """Test LOW severity rule detection."""

    def test_detects_debug_print_python(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text('print("debug")\n')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        assert "DEBUG_PRINT" in rules

    def test_detects_console_log_js(self, tmp_path):
        f = tmp_path / "code.js"
        f.write_text('console.log("debug");\n')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        assert "DEBUG_PRINT" in rules

    def test_detects_lint_disable(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text('x = 1  # noqa\n')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        assert "LINT_DISABLE" in rules

    def test_detects_magic_number(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text('timeout = 86400\n')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        assert "MAGIC_NUMBER" in rules


class TestCheckFileTestExemption:
    """Test that test files are exempt from secret detection rules."""

    def test_test_file_skips_api_key_rule(self, tmp_path):
        # Create file in tests directory
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        f = tests_dir / "test_api.py"
        f.write_text('API_KEY = "test_secret_key_12345"\n')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        assert "API_KEY" not in rules
        assert "POSSIBLE_SECRET" not in rules

    def test_test_prefix_file_skips_secrets(self, tmp_path):
        f = tmp_path / "test_routes.py"
        f.write_text('password = "fake_password_123"\n')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        assert "POSSIBLE_SECRET" not in rules

    def test_spec_file_skips_secrets(self, tmp_path):
        f = tmp_path / "auth.spec.js"
        f.write_text('const apiKey = "test_api_key_value";\n')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        assert "API_KEY" not in rules

    def test_non_test_file_detects_secrets(self, tmp_path):
        f = tmp_path / "config.py"
        f.write_text('password = "real_password_123"\n')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        assert "POSSIBLE_SECRET" in rules

    def test_test_file_still_detects_other_rules(self, tmp_path):
        f = tmp_path / "test_utils.py"
        f.write_text('# TODO: fix this test\ndef test_foo():\n    pass\n')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        # Should still detect TODO and STUB_IMPL
        assert "TODO" in rules
        assert "STUB_IMPL" in rules


class TestInlineSuppression:
    """Test inline suppression with # lint:ignore."""

    def test_suppress_all_rules(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text('print("debug")  # lint:ignore\n')
        violations = check_file(str(f))
        assert len(violations) == 0

    def test_suppress_specific_rule(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text('x = 86400  # lint:ignore MAGIC_NUMBER\nprint("test")\n')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        assert "MAGIC_NUMBER" not in rules
        assert "DEBUG_PRINT" in rules

    def test_suppress_disable_syntax(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text('print("debug")  # lint:disable\n')
        violations = check_file(str(f))
        assert len(violations) == 0


class TestSeverityFiltering:
    """Test min_severity parameter."""

    def test_high_only(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text('# TODO: later\nprint("debug")\nYOUR_KEY_HERE\n')
        violations = check_file(str(f), min_severity="HIGH")
        severities = {v["severity"] for v in violations}
        assert severities == {"HIGH"}

    def test_medium_and_above(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text('# TODO: later\nprint("debug")\n')
        violations = check_file(str(f), min_severity="MEDIUM")
        severities = {v["severity"] for v in violations}
        assert "LOW" not in severities
        assert "MEDIUM" in severities


class TestSplitCodeComment:
    """Test code/comment splitting."""

    def test_python_line_comment(self):
        code, comment = split_code_comment('x = 1  # comment', '.py')
        assert code == 'x = 1  '
        assert comment == ' comment'

    def test_js_line_comment(self):
        code, comment = split_code_comment('x = 1; // comment', '.js')
        assert code == 'x = 1; '
        assert comment == ' comment'

    def test_no_comment(self):
        code, comment = split_code_comment('x = 1', '.py')
        assert code == 'x = 1'
        assert comment == ''

    def test_hash_in_string_not_comment(self):
        code, comment = split_code_comment('x = "foo#bar"', '.py')
        assert code == 'x = "foo#bar"'
        assert comment == ''

    def test_comment_after_string_with_hash(self):
        code, comment = split_code_comment('x = "foo#bar"  # real comment', '.py')
        assert 'real comment' in comment


class TestFindStringRanges:
    """Test string literal detection."""

    def test_double_quotes(self):
        ranges = find_string_ranges('x = "hello"')
        assert len(ranges) == 1
        assert ranges[0] == (4, 11)

    def test_single_quotes(self):
        ranges = find_string_ranges("x = 'hello'")
        assert len(ranges) == 1

    def test_multiple_strings(self):
        ranges = find_string_ranges('x = "a" + "b"')
        assert len(ranges) == 2

    def test_no_strings(self):
        ranges = find_string_ranges('x = 1 + 2')
        assert len(ranges) == 0


class TestBinaryDetection:
    """Test binary file detection."""

    def test_text_file_not_binary(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text('print("hello")\n' * 100)
        assert not is_binary(f)

    def test_file_with_nulls_is_binary(self, tmp_path):
        f = tmp_path / "data.bin"
        # Write content with lots of null bytes
        f.write_bytes(b'\x00' * 1000 + b'some text' + b'\x00' * 1000)
        assert is_binary(f)

    def test_small_file_assumed_text(self, tmp_path):
        f = tmp_path / "tiny.bin"
        f.write_bytes(b'\x00\x00\x00')  # Only 3 bytes
        assert not is_binary(f)  # Below min_size threshold


class TestRunLint:
    """Test the run_lint API function."""

    def test_clean_file_passes(self, tmp_path):
        f = tmp_path / "clean.py"
        f.write_text('def add(a, b):\n    return a + b\n')
        passed, output = run_lint([str(f)])
        assert passed
        assert "PASS" in output

    def test_dirty_file_fails_on_high(self, tmp_path):
        f = tmp_path / "dirty.py"
        f.write_text('YOUR_KEY_HERE = "secret"\n')
        passed, output = run_lint([str(f)])
        assert not passed
        assert "FAIL" in output

    def test_directory_scan(self, tmp_path):
        (tmp_path / "a.py").write_text('x = 1\n')
        (tmp_path / "b.py").write_text('y = 2\n')
        passed, output = run_lint([str(tmp_path)])
        assert passed

    def test_ignores_zen_directory(self, tmp_path):
        zen_dir = tmp_path / ".zen" / "backup"
        zen_dir.mkdir(parents=True)
        (zen_dir / "old.py").write_text('YOUR_KEY_HERE = "x"\n')
        (tmp_path / "main.py").write_text('x = 1\n')
        passed, output = run_lint([str(tmp_path)])
        assert passed  # Should not find the violation in .zen


class TestViolationDetails:
    """Test violation dict structure."""

    def test_violation_has_required_fields(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text('# TODO: test\n')
        violations = check_file(str(f))
        assert len(violations) == 1
        v = violations[0]
        assert "rule" in v
        assert "severity" in v
        assert "file" in v
        assert "line" in v
        assert "content" in v

    def test_violation_line_number_correct(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text('x = 1\ny = 2\n# TODO: here\nz = 3\n')
        violations = check_file(str(f))
        todo_violation = [v for v in violations if v["rule"] == "TODO"][0]
        assert todo_violation["line"] == 3


# =============================================================================
# BUG TESTS - These demonstrate known issues in the linter
# =============================================================================

class TestBugEggInfoGlobPattern:
    """BUG: *.egg-info in IGNORE_DIRS uses glob syntax but check is exact match."""

    def test_egg_info_directory_should_be_ignored(self, tmp_path):
        """Files in .egg-info directories should be ignored."""
        egg_dir = tmp_path / "mypackage.egg-info"
        egg_dir.mkdir()
        # Use .py file to ensure it's scanned (PKG-INFO has no recognized extension)
        f = egg_dir / "setup_info.py"
        f.write_text('# TODO: this should be ignored\n')

        passed, output = run_lint([str(tmp_path)])
        # BUG: Currently fails because "mypackage.egg-info" != "*.egg-info"
        # run_lint returns True (no HIGH issues) but still finds violations
        assert "No issues" in output, f"egg-info should be ignored but got: {output}"


class TestBugAbstractMethodsFlaggedAsStubs:
    """BUG: ABSTRACT_PATTERNS is defined but never used - abstract methods flagged."""

    def test_abstract_method_not_flagged_as_stub(self, tmp_path):
        """Abstract methods with pass/... should not be flagged as STUB_IMPL."""
        f = tmp_path / "base.py"
        f.write_text('''from abc import ABC, abstractmethod

class Base(ABC):
    @abstractmethod
    def must_implement(self):
        pass
''')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        # BUG: Currently fails because ABSTRACT_PATTERNS is never checked
        assert "STUB_IMPL" not in rules, "Abstract methods should not be flagged as stubs"

    def test_protocol_method_not_flagged_as_stub(self, tmp_path):
        """Protocol methods with ... should not be flagged as STUB_IMPL."""
        f = tmp_path / "protocol.py"
        f.write_text('''from typing import Protocol

class Drawable(Protocol):
    def draw(self) -> None:
        ...
''')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        # BUG: Currently fails
        assert "STUB_IMPL" not in rules, "Protocol methods should not be flagged as stubs"


class TestBugSuppressionOnlyWorksForHash:
    """BUG: lint:ignore suppression only works for # comments."""

    def test_js_suppression_with_double_slash(self, tmp_path):
        """JS files should support // lint:ignore syntax."""
        f = tmp_path / "code.js"
        f.write_text('console.log("debug"); // lint:ignore\n')
        violations = check_file(str(f))
        # BUG: Currently fails because pattern only matches #
        assert len(violations) == 0, "JS suppression should work with //"

    def test_sql_suppression_with_double_dash(self, tmp_path):
        """SQL files should support -- lint:ignore syntax."""
        f = tmp_path / "query.sql"
        f.write_text('-- TODO: optimize this -- lint:ignore\n')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        # BUG: Currently fails because pattern only matches #
        assert "TODO" not in rules, "SQL suppression should work with --"


class TestTripleQuoteHandling:
    """Test that triple-quoted strings are handled correctly."""

    def test_triple_quote_unclosed_returns_empty(self):
        """Unclosed triple-quote on a single line returns empty ranges."""
        from zen_mode.linter import find_string_ranges

        line = '"""'
        ranges = find_string_ranges(line)
        # Unclosed triple quote should not be treated as a complete string
        assert ranges == [], f"Unclosed triple quote should return empty, got {ranges}"

    def test_triple_quote_closed_same_line(self):
        """Triple-quoted string closed on same line is detected."""
        from zen_mode.linter import find_string_ranges

        line = '"""hello"""'
        ranges = find_string_ranges(line)
        assert ranges == [(0, 11)], f"Should detect triple-quoted string, got {ranges}"

    def test_todo_in_docstring_is_flagged(self, tmp_path):
        """TODO in a docstring IS flagged (indicates incomplete documentation).

        Python docstrings are treated as block comments by the linter.
        TODOs inside them indicate incomplete documentation and should be caught.
        """
        f = tmp_path / "module.py"
        f.write_text('''def example():
    """
    TODO: Document the return value better.
    """
    return 42
''')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        # Docstrings are treated as comments, TODOs inside are flagged
        assert "TODO" in rules, "TODO in docstring should be flagged"


class TestBugInvalidIPAddressMatches:
    """BUG: HARDCODED_IP regex matches invalid IP addresses."""

    def test_invalid_ip_not_matched(self, tmp_path):
        """999.999.999.999 is not a valid IP and should not be flagged."""
        f = tmp_path / "code.py"
        f.write_text('invalid = "999.999.999.999"\n')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        # BUG: Currently fails - regex doesn't validate octet ranges
        assert "HARDCODED_IP" not in rules, "Invalid IPs should not be flagged"

    def test_valid_public_ip_matched(self, tmp_path):
        """Valid public IPs should still be flagged."""
        f = tmp_path / "code.py"
        f.write_text('server = "8.8.8.8"\n')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        assert "HARDCODED_IP" in rules, "Valid public IPs should be flagged"

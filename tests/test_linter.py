"""Tests for zen_mode.linter behavior."""
import pytest
from pathlib import Path

from zen_mode.linter import (
    check_file,
    run_lint,
    split_code_comment,
    find_string_ranges,
    is_binary,
    load_config,
    format_report,
    print_rules,
    LINT_SKIP_EXTS,
    TEST_EXEMPT_RULES,
    TEST_FILE_PATTERNS,
    QUALITY_RULES,
)
from zen_mode.utils import IGNORE_DIRS, IGNORE_FILES, BINARY_EXTS


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
    """Test that BINARY_EXTS and LINT_SKIP_EXTS skip expected extensions."""

    def test_images_in_binary_exts(self):
        assert ".png" in BINARY_EXTS
        assert ".jpg" in BINARY_EXTS

    def test_markdown_in_lint_skip_exts(self):
        assert ".md" in LINT_SKIP_EXTS

    def test_binaries_in_binary_exts(self):
        assert ".exe" in BINARY_EXTS
        assert ".dll" in BINARY_EXTS


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
    """Test inline suppression with # lint:ignore and # zenlint: ignore."""

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

    def test_zenlint_suppress_all_rules(self, tmp_path):
        """zenlint: ignore should suppress all rules on the line."""
        f = tmp_path / "code.py"
        f.write_text('print("debug")  # zenlint: ignore\n')
        violations = check_file(str(f))
        assert len(violations) == 0

    def test_zenlint_suppress_specific_rule(self, tmp_path):
        """zenlint: ignore RULE should suppress only that rule."""
        f = tmp_path / "code.py"
        f.write_text('secret = "abc123"  # zenlint: ignore POSSIBLE_SECRET\nprint("test")\n')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        assert "POSSIBLE_SECRET" not in rules
        assert "DEBUG_PRINT" in rules

    def test_zenlint_disable_syntax(self, tmp_path):
        """zenlint: disable should also work."""
        f = tmp_path / "code.py"
        f.write_text('print("debug")  # zenlint: disable\n')
        violations = check_file(str(f))
        assert len(violations) == 0

    def test_zenlint_case_insensitive(self, tmp_path):
        """Suppression should be case-insensitive."""
        f = tmp_path / "code.py"
        f.write_text('print("debug")  # ZENLINT: IGNORE\n')
        violations = check_file(str(f))
        assert len(violations) == 0

    def test_zenlint_with_extra_spaces(self, tmp_path):
        """Suppression should handle variable spacing."""
        f = tmp_path / "code.py"
        f.write_text('print("debug")  #  zenlint:  ignore\n')
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

    def test_ignores_node_modules_directory(self, tmp_path):
        """BUG FIX TEST: node_modules should be excluded from scanning."""
        # Create node_modules with violations
        node_modules = tmp_path / "node_modules" / "@babel" / "core"
        node_modules.mkdir(parents=True)
        (node_modules / "index.js").write_text('<<<<<<< HEAD\nconsole.log("conflict");\n// TODO: fix\n')

        # Create normal project file
        (tmp_path / "app.js").write_text('const x = 1;\n')

        passed, output = run_lint([str(tmp_path)])
        # Should pass because node_modules violations are ignored
        assert passed, f"node_modules should be ignored but got: {output}"
        assert "node_modules" not in output, "node_modules should not appear in lint output"

    def test_ignores_build_directories(self, tmp_path):
        """All build/cache/coverage directories should be ignored."""
        # Create various build/cache directories with violations
        ignore_dirs = ["build", "dist", ".cache", "coverage", "__pycache__", ".pytest_cache"]

        for dirname in ignore_dirs:
            dir_path = tmp_path / dirname
            dir_path.mkdir()
            (dir_path / "file.py").write_text('YOUR_KEY_HERE = "secret"\n')

        # Create normal file
        (tmp_path / "main.py").write_text('x = 1\n')

        passed, output = run_lint([str(tmp_path)])
        assert passed, f"Build dirs should be ignored but got: {output}"
        for dirname in ignore_dirs:
            assert dirname not in output, f"{dirname} should not appear in lint output"

    def test_ignores_nested_node_modules(self, tmp_path):
        """node_modules nested deep in project should be ignored."""
        # Create nested node_modules (not at root)
        nested = tmp_path / "packages" / "frontend" / "node_modules" / "react"
        nested.mkdir(parents=True)
        (nested / "index.js").write_text('<<<<<<< CONFLICT\n')

        # Normal file
        (tmp_path / "app.py").write_text('x = 1\n')

        passed, output = run_lint([str(tmp_path)])
        assert passed, f"Nested node_modules should be ignored but got: {output}"
        assert "node_modules" not in output

    def test_does_not_ignore_similar_names(self, tmp_path):
        """Directories with similar names to ignored dirs should NOT be ignored."""
        # Create dirs with similar but not exact names
        (tmp_path / "node_modules_backup").mkdir()
        (tmp_path / "node_modules_backup" / "test.py").write_text('YOUR_KEY_HERE = "x"\n')

        (tmp_path / "my_build").mkdir()
        (tmp_path / "my_build" / "test.py").write_text('YOUR_KEY_HERE = "x"\n')

        passed, output = run_lint([str(tmp_path)])
        # Should fail because these directories should be scanned
        assert not passed, "Similar-named directories should be scanned"
        assert "node_modules_backup" in output or "my_build" in output

    def test_ignores_deeply_nested_violations(self, tmp_path):
        """Violations deeply nested in ignored dirs should be skipped."""
        deep = tmp_path / "node_modules" / "pkg" / "lib" / "vendor" / "src" / "internal"
        deep.mkdir(parents=True)
        (deep / "module.js").write_text('<<<<<<< HEAD\n' * 100)  # Many violations

        (tmp_path / "app.js").write_text('const x = 1;\n')

        passed, output = run_lint([str(tmp_path)])
        assert passed, "Deeply nested node_modules should be ignored"

    def test_ignores_hidden_directories(self, tmp_path):
        """Directories starting with . should be ignored."""
        hidden_dirs = [".git", ".vscode", ".idea", ".mypy_cache"]

        for dirname in hidden_dirs:
            dir_path = tmp_path / dirname
            dir_path.mkdir()
            (dir_path / "file.py").write_text('YOUR_KEY_HERE = "x"\n')

        (tmp_path / "main.py").write_text('x = 1\n')

        passed, output = run_lint([str(tmp_path)])
        assert passed, f"Hidden directories should be ignored but got: {output}"

    def test_scans_normal_directories(self, tmp_path):
        """Normal project directories should still be scanned."""
        # Create normal project structure
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text('YOUR_KEY_HERE = "secret"\n')

        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test.py").write_text('x = 1\n')

        passed, output = run_lint([str(tmp_path)])
        # Should fail because src/ has violations
        assert not passed, "Normal directories should be scanned"
        assert "src" in output or "app.py" in output


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


class TestBugHardcodedIPFalsePositives:
    """BUG: HARDCODED_IP regex incorrectly flags private/reserved IPs."""

    def test_private_ip_192_168_not_flagged(self, tmp_path):
        """Private IPs like 192.168.x.x should not be flagged."""
        f = tmp_path / "code.py"
        f.write_text('local_server = "192.168.1.1"\n')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        assert "HARDCODED_IP" not in rules, "192.168.x.x should not be flagged (private IP)"

    def test_private_ip_10_not_flagged(self, tmp_path):
        """Private IPs like 10.x.x.x should not be flagged."""
        f = tmp_path / "code.py"
        f.write_text('vpn_server = "10.0.0.1"\n')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        assert "HARDCODED_IP" not in rules, "10.x.x.x should not be flagged (private IP)"

    def test_private_ip_172_16_not_flagged(self, tmp_path):
        """Private IPs like 172.16-31.x.x should not be flagged."""
        f = tmp_path / "code.py"
        f.write_text('docker_network = "172.16.0.1"\n')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        assert "HARDCODED_IP" not in rules, "172.16-31.x.x should not be flagged (private IP)"

    def test_localhost_not_flagged(self, tmp_path):
        """Loopback address 127.0.0.1 should not be flagged."""
        f = tmp_path / "code.py"
        f.write_text('localhost = "127.0.0.1"\n')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        assert "HARDCODED_IP" not in rules, "127.0.0.1 should not be flagged (loopback)"

    def test_link_local_not_flagged(self, tmp_path):
        """Link-local addresses 169.254.x.x should not be flagged."""
        f = tmp_path / "code.py"
        f.write_text('link_local = "169.254.1.1"\n')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        assert "HARDCODED_IP" not in rules, "169.254.x.x should not be flagged (link-local)"

    def test_public_ip_flagged(self, tmp_path):
        """Public IPs like 8.8.8.8 should still be flagged."""
        f = tmp_path / "code.py"
        f.write_text('dns_server = "8.8.8.8"\n')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        assert "HARDCODED_IP" in rules, "8.8.8.8 should be flagged (public IP)"

    def test_another_public_ip_flagged(self, tmp_path):
        """Public IPs like 1.1.1.1 should be flagged."""
        f = tmp_path / "code.py"
        f.write_text('cloudflare_dns = "1.1.1.1"\n')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        assert "HARDCODED_IP" in rules, "1.1.1.1 should be flagged (public IP)"


class TestInvalidIPAddressHandling:
    """Test that invalid IP addresses are flagged correctly."""

    def test_invalid_ip_is_flagged(self, tmp_path):
        """Invalid IPs like 999.999.999.999 should be flagged as suspicious."""
        f = tmp_path / "code.py"
        f.write_text('invalid = "999.999.999.999"\n')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        # Invalid IPs are suspicious and should be flagged
        assert "HARDCODED_IP" in rules, "Invalid IPs should be flagged as suspicious"

    def test_valid_public_ip_matched(self, tmp_path):
        """Valid public IPs should still be flagged."""
        f = tmp_path / "code.py"
        f.write_text('server = "8.8.8.8"\n')
        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        assert "HARDCODED_IP" in rules, "Valid public IPs should be flagged"


class TestBugLargeFilesNotSkipped:
    """BUG: Files larger than 1MB are not skipped, may cause hangs/crashes."""

    def test_large_file_should_be_skipped(self, tmp_path):
        """Files > 1MB should be skipped to avoid performance issues."""
        f = tmp_path / "large.py"
        # Create a file > 1MB with violations
        # 1MB = 1,048,576 bytes. Create content just over that.
        line = "# TODO: this should be ignored because file is too large\n"
        lines_needed = (1_000_001 // len(line)) + 1
        content = line * lines_needed
        f.write_text(content)

        # Verify file is indeed > 1MB
        assert f.stat().st_size > 1_000_000, "Test file should be > 1MB"

        violations = check_file(str(f))
        # BUG: Currently fails - large files are not skipped
        assert len(violations) == 0, "Files > 1MB should be skipped entirely"

    def test_normal_file_still_scanned(self, tmp_path):
        """Files < 1MB should still be scanned normally."""
        f = tmp_path / "normal.py"
        f.write_text("# TODO: this should be caught\n")

        # Verify file is small
        assert f.stat().st_size < 1_000_000, "Test file should be < 1MB"

        violations = check_file(str(f))
        rules = [v["rule"] for v in violations]
        assert "TODO" in rules, "Normal files should still be scanned"


class TestLanguageSpecificRuleScoping:
    """Test that rules only apply to relevant file extensions."""

    def test_overly_generic_except_only_python(self, tmp_path):
        """OVERLY_GENERIC_EXCEPT should only apply to Python files."""
        # Python file - should be flagged
        py_file = tmp_path / "code.py"
        py_file.write_text('try:\n    foo()\nexcept:\n    pass\n')
        py_violations = check_file(str(py_file))
        py_rules = [v["rule"] for v in py_violations]
        assert "OVERLY_GENERIC_EXCEPT" in py_rules

        # JS file - should NOT be flagged (same pattern but wrong language)
        js_file = tmp_path / "code.js"
        js_file.write_text('try {\n    foo();\n} except: {\n    pass\n}\n')
        js_violations = check_file(str(js_file))
        js_rules = [v["rule"] for v in js_violations]
        assert "OVERLY_GENERIC_EXCEPT" not in js_rules

    def test_stub_impl_only_python(self, tmp_path):
        """STUB_IMPL (pass/...) should only apply to Python files."""
        # Python file - should be flagged
        py_file = tmp_path / "code.py"
        py_file.write_text('def foo():\n    pass\n')
        py_violations = check_file(str(py_file))
        py_rules = [v["rule"] for v in py_violations]
        assert "STUB_IMPL" in py_rules

        # JS file - should NOT be flagged
        js_file = tmp_path / "code.js"
        js_file.write_text('function foo() {\n    pass\n}\n')
        js_violations = check_file(str(js_file))
        js_rules = [v["rule"] for v in js_violations]
        assert "STUB_IMPL" not in js_rules

    def test_bare_return_in_catch_only_js(self, tmp_path):
        """BARE_RETURN_IN_CATCH should only apply to JS/TS files."""
        # JS file - should be flagged
        js_file = tmp_path / "code.js"
        js_file.write_text('try { foo(); } catch(e) { return; }\n')
        js_violations = check_file(str(js_file))
        js_rules = [v["rule"] for v in js_violations]
        assert "BARE_RETURN_IN_CATCH" in js_rules

        # Python file - should NOT be flagged (different language)
        py_file = tmp_path / "code.py"
        py_file.write_text('# catch(e) { return; } in a comment\n')
        py_violations = check_file(str(py_file))
        py_rules = [v["rule"] for v in py_violations]
        assert "BARE_RETURN_IN_CATCH" not in py_rules

    def test_inline_import_only_supported_languages(self, tmp_path):
        """INLINE_IMPORT should only apply to languages with import statements."""
        # Python file - should be flagged
        py_file = tmp_path / "code.py"
        py_file.write_text('def foo():\n    import os\n')
        py_violations = check_file(str(py_file))
        py_rules = [v["rule"] for v in py_violations]
        assert "INLINE_IMPORT" in py_rules

        # Markdown file - should NOT be flagged
        md_file = tmp_path / "README.md"
        md_file.write_text('   import os  # example code\n')
        md_violations = check_file(str(md_file))
        md_rules = [v["rule"] for v in md_violations]
        assert "INLINE_IMPORT" not in md_rules

    def test_empty_docstring_only_python(self, tmp_path):
        """EMPTY_DOCSTRING should only apply to Python files."""
        # Python file - should be flagged
        py_file = tmp_path / "code.py"
        py_file.write_text('def foo():\n    """"""\n    return 1\n')
        py_violations = check_file(str(py_file))
        py_rules = [v["rule"] for v in py_violations]
        assert "EMPTY_DOCSTRING" in py_rules

        # JS file - should NOT be flagged
        js_file = tmp_path / "code.js"
        js_file.write_text('const x = """""";\n')
        js_violations = check_file(str(js_file))
        js_rules = [v["rule"] for v in js_violations]
        assert "EMPTY_DOCSTRING" not in js_rules

    def test_universal_rules_apply_everywhere(self, tmp_path):
        """Rules without extension restrictions should apply to all files."""
        # TODO rule should apply to any language
        py_file = tmp_path / "code.py"
        py_file.write_text('# TODO: fix this\n')
        py_violations = check_file(str(py_file))
        assert "TODO" in [v["rule"] for v in py_violations]

        js_file = tmp_path / "code.js"
        js_file.write_text('// TODO: fix this\n')
        js_violations = check_file(str(js_file))
        assert "TODO" in [v["rule"] for v in js_violations]

        rb_file = tmp_path / "code.rb"
        rb_file.write_text('# TODO: fix this\n')
        rb_violations = check_file(str(rb_file))
        assert "TODO" in [v["rule"] for v in rb_violations]


class TestLoadConfig:
    """Tests for load_config() function."""

    def test_load_valid_json_config(self, tmp_path, monkeypatch):
        """Load a valid JSON config file."""
        monkeypatch.chdir(tmp_path)
        config_file = tmp_path / ".lintrc.json"
        config_file.write_text('{"ignore_rules": ["TODO"], "min_severity": "MEDIUM"}')

        config = load_config(str(config_file))

        assert config is not None
        assert config["ignore_rules"] == ["TODO"]
        assert config["min_severity"] == "MEDIUM"

    def test_load_default_config_file(self, tmp_path, monkeypatch):
        """Auto-discover default config file names."""
        monkeypatch.chdir(tmp_path)
        config_file = tmp_path / ".lintrc.json"
        config_file.write_text('{"custom": true}')

        # Pass None to trigger auto-discovery
        config = load_config(None)

        assert config is not None
        assert config["custom"] is True

    def test_load_lintrc_without_extension(self, tmp_path, monkeypatch):
        """Auto-discover .lintrc file."""
        monkeypatch.chdir(tmp_path)
        config_file = tmp_path / ".lintrc"
        config_file.write_text('{"from_lintrc": true}')

        config = load_config(None)

        assert config is not None
        assert config["from_lintrc"] is True

    def test_nonexistent_config_returns_none(self, tmp_path, monkeypatch):
        """Non-existent config file returns None."""
        monkeypatch.chdir(tmp_path)

        config = load_config("nonexistent.json")

        assert config is None

    def test_invalid_json_returns_none(self, tmp_path, monkeypatch, capsys):
        """Invalid JSON returns None and prints warning."""
        monkeypatch.chdir(tmp_path)
        config_file = tmp_path / "bad.json"
        config_file.write_text('{"invalid json')

        config = load_config(str(config_file))

        assert config is None
        captured = capsys.readouterr()
        assert "Warning" in captured.err

    def test_no_config_returns_none(self, tmp_path, monkeypatch):
        """No config file in directory returns None."""
        monkeypatch.chdir(tmp_path)

        config = load_config(None)

        assert config is None


class TestFormatReport:
    """Tests for format_report() function."""

    def test_text_format_no_violations(self):
        """Text format with no violations shows PASS."""
        output, exit_code = format_report([], "text")

        assert "[PASS]" in output
        assert exit_code == 0

    def test_text_format_with_violations(self):
        """Text format lists violations and shows summary."""
        violations = [
            {"file": "test.py", "line": 10, "rule": "TODO", "severity": "MEDIUM", "content": "TODO: fix"},
            {"file": "test.py", "line": 20, "rule": "PLACEHOLDER", "severity": "HIGH", "content": "XXX"},
        ]

        output, exit_code = format_report(violations, "text")

        assert "Found 2 issue(s)" in output
        assert "[HIGH] test.py:20" in output
        assert "[MEDIUM] test.py:10" in output
        assert "Summary:" in output
        assert "[FAIL]" in output
        assert exit_code == 1

    def test_text_format_medium_only_passes(self):
        """Text format with only MEDIUM violations passes."""
        violations = [
            {"file": "test.py", "line": 10, "rule": "TODO", "severity": "MEDIUM", "content": "TODO: fix"},
        ]

        output, exit_code = format_report(violations, "text")

        assert "[FAIL]" not in output
        assert exit_code == 0

    def test_json_format_structure(self):
        """JSON format has correct structure."""
        import json
        violations = [
            {"file": "test.py", "line": 10, "rule": "TODO", "severity": "MEDIUM", "content": "TODO: fix"},
        ]

        output, exit_code = format_report(violations, "json")
        data = json.loads(output)

        assert "violations" in data
        assert "count" in data
        assert data["count"] == 1
        assert len(data["violations"]) == 1
        assert exit_code == 0

    def test_json_format_exit_code_on_high(self):
        """JSON format returns exit code 1 on HIGH severity."""
        violations = [
            {"file": "test.py", "line": 10, "rule": "PLACEHOLDER", "severity": "HIGH", "content": "XXX"},
        ]

        output, exit_code = format_report(violations, "json")

        assert exit_code == 1

    def test_sarif_format_structure(self):
        """SARIF format has correct schema structure."""
        import json
        violations = [
            {"file": "test.py", "line": 10, "rule": "TODO", "severity": "MEDIUM", "content": "TODO: fix"},
        ]

        output, exit_code = format_report(violations, "sarif")
        data = json.loads(output)

        assert data["$schema"] == "https://json.schemastore.org/sarif-2.1.0.json"
        assert data["version"] == "2.1.0"
        assert "runs" in data
        assert len(data["runs"]) == 1
        assert "tool" in data["runs"][0]
        assert "results" in data["runs"][0]

    def test_sarif_format_severity_mapping(self):
        """SARIF maps severity to correct level."""
        import json
        violations = [
            {"file": "a.py", "line": 1, "rule": "R1", "severity": "HIGH", "content": "x"},
            {"file": "b.py", "line": 2, "rule": "R2", "severity": "MEDIUM", "content": "y"},
            {"file": "c.py", "line": 3, "rule": "R3", "severity": "LOW", "content": "z"},
        ]

        output, _ = format_report(violations, "sarif")
        data = json.loads(output)
        results = data["runs"][0]["results"]

        levels = [r["level"] for r in results]
        assert "error" in levels      # HIGH
        assert "warning" in levels    # MEDIUM
        assert "note" in levels       # LOW

    def test_sarif_format_exit_code_on_high(self):
        """SARIF format returns exit code 1 on HIGH severity."""
        violations = [
            {"file": "test.py", "line": 10, "rule": "PLACEHOLDER", "severity": "HIGH", "content": "XXX"},
        ]

        output, exit_code = format_report(violations, "sarif")

        assert exit_code == 1


class TestPrintRules:
    """Tests for print_rules() function."""

    def test_print_rules_shows_all_severities(self, capsys):
        """print_rules() shows rules grouped by severity."""
        print_rules()
        output = capsys.readouterr().out

        assert "[HIGH]" in output
        assert "[MEDIUM]" in output
        assert "[LOW]" in output

    def test_print_rules_shows_rule_names(self, capsys):
        """print_rules() shows rule names."""
        print_rules()
        output = capsys.readouterr().out

        # Check some known rules exist
        assert "TODO" in output or "PLACEHOLDER" in output

    def test_print_rules_shows_patterns(self, capsys):
        """print_rules() shows rule patterns (truncated)."""
        print_rules()
        output = capsys.readouterr().out

        # Should have rule: pattern format
        assert ":" in output

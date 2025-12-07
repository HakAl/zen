"""
Tests for extract_failure_count() - language-agnostic failure extraction.
"""
import sys
from pathlib import Path

# Import from package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from zen_mode.core import extract_failure_count


class TestPythonPytest:
    """Extract failure counts from pytest output."""

    def test_pytest_simple_failure(self):
        output = """
============================= test session starts ==============================
collected 10 items

tests/test_foo.py .........F

============================== 1 failed, 9 passed ==============================
"""
        assert extract_failure_count(output) == 1

    def test_pytest_multiple_failures(self):
        output = """
============================== 5 failed, 3 passed ==============================
"""
        assert extract_failure_count(output) == 5

    def test_pytest_all_pass(self):
        output = """
============================== 10 passed in 2.5s ===============================
"""
        assert extract_failure_count(output) is None


class TestJavaScriptJest:
    """Extract failure counts from Jest output."""

    def test_jest_failures(self):
        output = """
Test Suites: 2 passed, 2 total
Tests:       3 failed, 7 passed, 10 total
Snapshots:   0 total
Time:        2.5s
"""
        assert extract_failure_count(output) == 3

    def test_jest_all_pass(self):
        output = """
Tests: 10 passed, 10 total
"""
        assert extract_failure_count(output) is None


class TestRustCargo:
    """Extract failure counts from cargo test output."""

    def test_cargo_failures(self):
        output = """
running 10 tests
test tests::test_one ... ok
test tests::test_two ... FAILED

failures:

---- tests::test_two stdout ----
assertion failed

test result: FAILED. 8 passed; 2 failed; 0 ignored
"""
        assert extract_failure_count(output) == 2

    def test_cargo_all_pass(self):
        output = """
test result: ok. 10 passed; 0 failed; 0 ignored
"""
        # "0 failed" - should return 0 or None?
        # Current implementation will find "0" near "failed"
        result = extract_failure_count(output)
        assert result == 0 or result is None


class TestGoTesting:
    """Extract failure counts from Go test output."""

    def test_go_failure(self):
        output = """
=== RUN   TestFoo
--- FAIL: TestFoo (0.00s)
    foo_test.go:10: expected 2, got 3
FAIL
exit status 1
FAIL	example.com/foo	0.005s
"""
        # Go doesn't typically show count, but should extract from FAIL
        result = extract_failure_count(output)
        # Implementation will find first number near "FAIL"
        assert result is not None


class TestUnicodeNormalization:
    """Test unicode normalization handles smart quotes, dashes, etc."""

    def test_smart_quotes(self):
        # Using smart quotes around "failed"
        output = "Tests: 5 'failed', 3 passed"
        assert extract_failure_count(output) == 5

    def test_em_dash(self):
        # Em dash instead of hyphen
        output = "Result: 3 failed — 7 passed"
        assert extract_failure_count(output) == 3


class TestBottomUpScanning:
    """Test that scanning from bottom finds summary, not noise."""

    def test_prefers_summary_at_bottom(self):
        output = """
Starting test run...
[INFO] 100 tests to run
[DEBUG] Test framework initialized

test_foo.py::test_one PASSED
test_foo.py::test_two FAILED
test_foo.py::test_three PASSED

============================== 1 failed, 2 passed ==============================
"""
        # Should find "1 failed" from summary, not "100" from debug log
        assert extract_failure_count(output) == 1

    def test_ignores_non_failure_numbers(self):
        output = """
Running tests in 5 threads
Loaded 100 test cases
[ERROR] Connection failed at line 42

============================== 3 failed, 97 passed ==============================
"""
        # Should find "3 failed" not "5", "100", or "42"
        assert extract_failure_count(output) == 3


class TestEdgeCases:
    """Edge cases and robustness."""

    def test_empty_output(self):
        assert extract_failure_count("") is None

    def test_no_failures_mentioned(self):
        output = "All tests passed successfully!"
        assert extract_failure_count(output) is None

    def test_failure_word_no_number(self):
        output = "Tests failed - see above for details"
        assert extract_failure_count(output) is None

    def test_multiple_fail_clauses_returns_first_from_bottom(self):
        output = """
Early in log: 10 failures detected
Middle of log: 5 failures remaining

Summary: 2 failed, 8 passed
"""
        # Scans from bottom, finds "2 failed" first
        assert extract_failure_count(output) == 2

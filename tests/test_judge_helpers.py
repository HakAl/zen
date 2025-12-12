"""
Tests for Judge phase helper functions (non-git related).

For git-related tests (get_changed_filenames, should_skip_judge, etc.),
see test_git.py which consolidates all git operations with proper mocking.
"""
import sys
from pathlib import Path

import pytest

# Import from package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from zen_mode.core import _is_test_or_doc


class TestIsTestOrDoc:
    """Tests for _is_test_or_doc() helper function."""

    # Documentation files
    def test_markdown_file(self):
        assert _is_test_or_doc("README.md") is True

    def test_txt_file(self):
        assert _is_test_or_doc("CHANGELOG.txt") is True

    def test_rst_file(self):
        assert _is_test_or_doc("docs/index.rst") is True

    def test_nested_doc_file(self):
        assert _is_test_or_doc("docs/api/overview.md") is True

    # Test files - various patterns
    def test_test_directory(self):
        assert _is_test_or_doc("tests/test_core.py") is True

    def test_test_in_path(self):
        assert _is_test_or_doc("src/test/helpers.py") is True

    def test_file_starting_with_test(self):
        assert _is_test_or_doc("test_utils.py") is True

    def test_underscore_test_pattern(self):
        assert _is_test_or_doc("core_test.py") is True

    def test_test_underscore_pattern(self):
        assert _is_test_or_doc("test_core.py") is True

    # Non-test/doc files
    def test_regular_python_file(self):
        assert _is_test_or_doc("src/core.py") is False

    def test_auth_file(self):
        assert _is_test_or_doc("src/auth.py") is False

    def test_config_file(self):
        assert _is_test_or_doc("config.json") is False

    def test_javascript_file(self):
        assert _is_test_or_doc("src/app.js") is False

    # Edge cases
    def test_file_with_test_in_name_but_not_pattern(self):
        # "contest.py" contains "test" but not as a test pattern
        assert _is_test_or_doc("contest.py") is False

    def test_testimony_file(self):
        # "testimony" starts with "test" so it matches the test pattern
        # This is expected behavior per the spec (startswith('test'))
        assert _is_test_or_doc("testimony.py") is True

    def test_attestation_file(self):
        assert _is_test_or_doc("attestation.py") is False

    def test_empty_string(self):
        assert _is_test_or_doc("") is False

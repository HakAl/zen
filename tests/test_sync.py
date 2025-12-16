"""
Tests to ensure scripts/zen.py and src/zen_mode/core.py stay in sync.

We maintain two copies of the code:
- scripts/zen.py: Standalone script users can copy into any project
- src/zen_mode/core.py: Pip-installable package

This test ensures key functions don't drift apart.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

# Paths to the two files
REPO_ROOT = Path(__file__).parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "zen.py"
PACKAGE_PATH = REPO_ROOT / "src" / "zen_mode" / "core.py"

# Functions that MUST stay in sync between script and package
# These are the core logic functions that have no intentional differences
SYNCED_FUNCTIONS = [
    # Git helpers
    "_git_has_head",
    "_git_is_repo",
    "get_changed_filenames",
    "should_skip_judge",
    "_is_test_or_doc",
    # Test output parsing
    "verify_test_output",
    "extract_failure_count",
    "parse_test_output",
    # File utilities
    "read_file",
    "write_file",
    "backup_file",
    "backup_scout_files",
    # Plan parsing
    "parse_steps",
    "get_completed_steps",
    # Cost tracking
    "_extract_cost",
    "_parse_json_response",
    "_record_cost",
    "_write_cost_summary",
    # Phases (core workflow)
    "phase_scout",
    "phase_plan",
    "phase_implement",
    "phase_verify",
    "phase_judge",
    "validate_plan_efficiency",
]

# Functions that are INTENTIONALLY different
# Document why each is different
INTENTIONALLY_DIFFERENT = {
    "run_linter": "Package imports from .linter module, script finds external file",
    "run_claude": "Package has lazy _init_claude(), script checks at import time",
    "log": "Same logic but may have minor differences",
    "main": "Script has CLI, package has run() API",
    "run": "Package-only public API",
    "_init_claude": "Package-only lazy initialization",
    "find_linter": "Script-only external linter discovery",
}

# Configuration constants that should have same defaults
SYNCED_CONFIG = [
    "MODEL_BRAIN",
    "MODEL_HANDS",
    "MODEL_EYES",
    "TIMEOUT_EXEC",
    "TIMEOUT_LINTER",
    "TIMEOUT_SUMMARY",
    "MAX_RETRIES",
    "MAX_JUDGE_LOOPS",
    "JUDGE_TRIVIAL_LINES",
    "JUDGE_SMALL_REFACTOR_LINES",
    "JUDGE_SIMPLE_PLAN_LINES",
    "JUDGE_SIMPLE_PLAN_STEPS",
    "PARSE_TEST_THRESHOLD",
]


def get_function_source(tree: ast.AST, func_name: str) -> ast.FunctionDef | None:
    """Extract a function definition from an AST."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return node
    return None


def normalize_ast(node: ast.AST) -> str:
    """Normalize an AST node to a comparable string.

    Removes line numbers and column offsets so we compare logic, not formatting.
    """
    # Clear location info
    for child in ast.walk(node):
        for attr in ('lineno', 'col_offset', 'end_lineno', 'end_col_offset'):
            if hasattr(child, attr):
                setattr(child, attr, 0)
    return ast.dump(node, annotate_fields=True, include_attributes=False)


def get_config_value(tree: ast.AST, name: str) -> str | None:
    """Extract a configuration assignment value from AST."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.dump(node.value)
    return None


class TestScriptPackageSync:
    """Test that script and package stay synchronized."""

    @pytest.fixture(scope="class")
    def script_ast(self):
        """Parse the script file."""
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        return ast.parse(source)

    @pytest.fixture(scope="class")
    def package_ast(self):
        """Parse the package file."""
        source = PACKAGE_PATH.read_text(encoding="utf-8")
        return ast.parse(source)

    @pytest.mark.parametrize("func_name", SYNCED_FUNCTIONS)
    def test_function_in_sync(self, script_ast, package_ast, func_name):
        """Verify that synced functions have identical logic."""
        script_func = get_function_source(script_ast, func_name)
        package_func = get_function_source(package_ast, func_name)

        assert script_func is not None, f"Function {func_name} missing from scripts/zen.py"
        assert package_func is not None, f"Function {func_name} missing from src/zen_mode/core.py"

        script_normalized = normalize_ast(script_func)
        package_normalized = normalize_ast(package_func)

        if script_normalized != package_normalized:
            # Provide helpful diff info
            pytest.fail(
                f"Function '{func_name}' differs between script and package.\n"
                f"Please update both files to keep them in sync.\n"
                f"Files:\n"
                f"  - scripts/zen.py\n"
                f"  - src/zen_mode/core.py\n"
            )

    @pytest.mark.parametrize("config_name", SYNCED_CONFIG)
    def test_config_defaults_match(self, script_ast, package_ast, config_name):
        """Verify configuration defaults are the same."""
        script_value = get_config_value(script_ast, config_name)
        package_value = get_config_value(package_ast, config_name)

        assert script_value is not None, f"Config {config_name} missing from scripts/zen.py"
        assert package_value is not None, f"Config {config_name} missing from src/zen_mode/core.py"

        if script_value != package_value:
            pytest.fail(
                f"Config '{config_name}' has different defaults:\n"
                f"  scripts/zen.py:        {script_value}\n"
                f"  src/zen_mode/core.py:  {package_value}\n"
            )

    def test_synced_functions_list_is_current(self, script_ast, package_ast):
        """Verify SYNCED_FUNCTIONS list covers all shared functions."""
        script_funcs = {
            node.name for node in ast.walk(script_ast)
            if isinstance(node, ast.FunctionDef)
        }
        package_funcs = {
            node.name for node in ast.walk(package_ast)
            if isinstance(node, ast.FunctionDef)
        }

        # Functions in both files
        shared = script_funcs & package_funcs

        # Should be either synced or intentionally different
        tracked = set(SYNCED_FUNCTIONS) | set(INTENTIONALLY_DIFFERENT.keys())
        untracked = shared - tracked

        if untracked:
            pytest.fail(
                f"Functions exist in both files but aren't tracked:\n"
                f"  {sorted(untracked)}\n\n"
                f"Add them to either SYNCED_FUNCTIONS or INTENTIONALLY_DIFFERENT in test_sync.py"
            )

    def test_intentionally_different_documented(self):
        """Verify all intentionally different functions have documentation."""
        for func_name, reason in INTENTIONALLY_DIFFERENT.items():
            assert reason.strip(), f"No reason documented for {func_name} being different"
            assert len(reason) > 10, f"Reason for {func_name} too short: '{reason}'"

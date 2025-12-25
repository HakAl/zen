"""
Zen Mode Verification: Test running and fix cycle.

Separates test verification (haiku) from test fixing (sonnet).
"""
from __future__ import annotations

import os
import re
import shutil
import unicodedata
from enum import Enum, auto
from pathlib import Path
from typing import Optional, Tuple

from zen_mode.config import (
    MODEL_EYES,
    MODEL_HANDS,
    TIMEOUT_VERIFY,
    TIMEOUT_FIX,
    MAX_FIX_ATTEMPTS,
    MAX_TEST_OUTPUT_PROMPT,
    PARSE_TEST_THRESHOLD,
    PROJECT_ROOT,
    WORK_DIR,
    TEST_OUTPUT_PATH_STR,
)

# Import from linter for test file detection
from zen_mode import linter
from zen_mode.utils import log as utils_log, read_file, run_claude as utils_run_claude

# -----------------------------------------------------------------------------
# Regex constants (copied from core for independence)
# -----------------------------------------------------------------------------
_FAIL_STEM = re.compile(r"\bfail", re.IGNORECASE)
_CLAUSE_SPLIT = re.compile(r"[,;|()\[\]{}\n]")
_DIGIT = re.compile(r"\d+")
_FILE_LINE_PATTERN = re.compile(r'File "([^"]+)", line (\d+)')


# -----------------------------------------------------------------------------
# Exceptions
# -----------------------------------------------------------------------------
class VerifyTimeout(Exception):
    """Raised when Claude times out during verification."""
    pass


# -----------------------------------------------------------------------------
# Enums
# -----------------------------------------------------------------------------
class TestState(Enum):
    """Result of running tests."""
    PASS = auto()           # All tests passed
    FAIL = auto()           # Tests ran, some failed
    NONE = auto()           # No tests found
    ERROR = auto()          # Command crashed / couldn't run
    RUNTIME_MISSING = auto() # Required runtime not installed


class FixResult(Enum):
    """Result of attempting to fix tests."""
    APPLIED = auto()
    BLOCKED = auto()


# -----------------------------------------------------------------------------
# Path Constants (derived from config)
# -----------------------------------------------------------------------------
TEST_OUTPUT_FILE = WORK_DIR / "test_output.txt"
PLAN_FILE = WORK_DIR / "plan.md"
LOG_FILE = WORK_DIR / "log.md"


# -----------------------------------------------------------------------------
# Wrappers for utils.py functions (use config globals)
# -----------------------------------------------------------------------------
def _log(msg: str) -> None:
    """Log message using config globals."""
    utils_log(msg, LOG_FILE, WORK_DIR)


def _run_claude(prompt: str, model: str, *, phase: str = "unknown", timeout: Optional[int] = None) -> Optional[str]:
    """Run Claude using config globals."""
    return utils_run_claude(
        prompt,
        model=model,
        phase=phase,
        timeout=timeout,
        project_root=PROJECT_ROOT,
        dry_run=False,
        log_fn=_log,
    )


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------
def truncate_preserve_tail(text: str, max_chars: int = 2000) -> str:
    """
    Truncate text while preserving the tail (where stack traces live).
    Keeps 30% head, 70% tail.
    """
    if len(text) <= max_chars:
        return text

    head_size = int(max_chars * 0.3)
    tail_size = max_chars - head_size - 20  # 20 for marker

    return text[:head_size] + "\n... (truncated) ...\n" + text[-tail_size:]


def extract_filenames(test_output: str) -> list[str]:
    """
    Extract unique filenames from test tracebacks.
    Returns list of file paths mentioned in 'File "...", line N' patterns.
    """
    matches = _FILE_LINE_PATTERN.findall(test_output)
    # Get unique filenames, preserve order
    seen = set()
    result = []
    for filepath, _ in matches:
        if filepath not in seen:
            seen.add(filepath)
            result.append(filepath)
    return result


def verify_test_output(output: str) -> bool:
    """
    Verify that agent output contains real test results, not just claims.
    Returns True if genuine test output is detected.
    """
    real_test_patterns = [
        # pytest
        r"=+\s+\d+\s+passed",
        r"=+\s+passed in \d+",
        r"\d+\s+passed",
        r"passed in [\d.]+s",
        r"PASSED|FAILED|ERROR",
        # npm/jest
        r"Tests:\s+\d+\s+passed",
        r"Test Suites:\s+\d+\s+passed",
        # cargo
        r"test result: ok\.",
        r"running \d+ tests?",
        r"\d+ passed; \d+ failed",
        # go
        r"^ok\s+\S+\s+[\d.]+s",
        r"^PASS$",
        # gradle/java
        r"BUILD SUCCESSFUL",
        r"tests? passed",
        r"\d+ tests? completed",
        # generic
        r"\d+\s+tests?\s+(passed|succeeded|ok)",
        r"All \d+ tests? passed",
    ]

    for pattern in real_test_patterns:
        if re.search(pattern, output, re.MULTILINE | re.IGNORECASE):
            return True

    return False


def detect_no_tests(output: str) -> bool:
    """
    Detect if test output indicates no tests exist or were collected.
    Returns True if no tests were found.
    """
    if not output:
        return False

    no_test_patterns = [
        r"no tests ran",
        r"collected 0 items",
        r"no tests collected",
        r"no tests found",
        r"Test Suites:\s+0",
        r"running 0 tests",
        r"0 passed; 0 failed; 0 ignored",
        r"\?\s+.*no test files",
        r"no test files",
        r"^0 tests",
        r"no tests? (found|exist|defined|available)",
    ]

    for pattern in no_test_patterns:
        if re.search(pattern, output, re.MULTILINE | re.IGNORECASE):
            return True

    return False


def project_has_tests() -> bool:
    """Quick filesystem scan to detect if project has any test files."""
    skip_dirs = {'.git', 'node_modules', 'venv', '.venv', '__pycache__', '.zen'}

    for root, dirs, files in os.walk(PROJECT_ROOT):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith('.')]

        depth = len(Path(root).relative_to(PROJECT_ROOT).parts)
        if depth > 3:
            dirs.clear()
            continue

        for f in files:
            if linter.TEST_FILE_PATTERNS.search(str(Path(root) / f)):
                return True

    return False


def detect_project_runtime() -> Tuple[Optional[str], bool]:
    """
    Detect project type from config files and check if runtime is available.

    Returns (runtime_name, is_available). If no config detected, returns (None, True)
    to allow fallback to Python/pytest.
    """
    # Config file -> runtime command mapping
    # Order matters: more specific first
    checks = [
        ("package.json", "node"),
        ("go.mod", "go"),
        ("build.gradle", "gradle"),
        ("build.gradle.kts", "gradle"),
        ("pom.xml", "mvn"),
        ("Cargo.toml", "cargo"),
        ("*.csproj", "dotnet"),
        ("*.fsproj", "dotnet"),
        ("mix.exs", "elixir"),
        ("Gemfile", "ruby"),
        ("composer.json", "php"),
        ("pubspec.yaml", "dart"),
        ("Package.swift", "swift"),
        ("build.zig", "zig"),
        ("build.sbt", "sbt"),
        ("CMakeLists.txt", "cmake"),
        ("*.cabal", "cabal"),
    ]

    for config_pattern, runtime in checks:
        if list(PROJECT_ROOT.glob(config_pattern)):
            return runtime, shutil.which(runtime) is not None

    # No specific config found - assume Python (always available)
    return None, True


def extract_failure_count(output: str) -> Optional[int]:
    """Extract failure count from test output. Language-agnostic."""
    if not output:
        return None

    norm = unicodedata.normalize("NFKC", output)
    norm = norm.translate({0x2013: 0x2D, 0x2014: 0x2D,
                           0x2019: 0x27, 0x2018: 0x27,
                           0x201C: 0x22, 0x201D: 0x22})

    clauses = _CLAUSE_SPLIT.split(norm)

    for clause in reversed(clauses):
        if not _FAIL_STEM.search(clause):
            continue

        m = _DIGIT.search(clause)
        if m:
            return int(m.group(0))

    return None


def parse_test_output(raw_output: str) -> str:
    """
    Use Haiku to extract actionable failure info from verbose test output.
    Reduces token count for Sonnet fix prompts.
    """
    if len(raw_output) < PARSE_TEST_THRESHOLD:
        return raw_output

    prompt = """Extract key failure information from this test output.
Return a concise summary with:
- Failed test names
- Error type and message for each failure
- Relevant file:line locations
- Last 2-3 stack frames (if present)

Keep under 400 words. Preserve exact error messages.

<test_output>
""" + raw_output[:4000] + """
</test_output>"""

    parsed = _run_claude(prompt, model=MODEL_EYES, phase="parse_tests", timeout=45)

    if not parsed or len(parsed) > len(raw_output):
        return truncate_preserve_tail(raw_output, MAX_TEST_OUTPUT_PROMPT)

    _log(f"[PARSE] Reduced test output: {len(raw_output)} -> {len(parsed)} chars")
    return parsed


# -----------------------------------------------------------------------------
# Phase Functions
# -----------------------------------------------------------------------------
def phase_verify() -> Tuple[TestState, str]:
    """
    Run tests once, no fixing. Returns (state, raw_output).

    Uses MODEL_EYES (haiku) - only runs tests, doesn't fix.
    """
    _log("\n[VERIFY] Running tests...")

    # Ensure work dir exists
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    # Pre-check: detect project runtime and verify it's installed
    runtime, available = detect_project_runtime()
    if not available:
        _log(f"[VERIFY] Runtime '{runtime}' not installed, skipping tests.")
        return TestState.RUNTIME_MISSING, f"Runtime '{runtime}' not found"

    # Get plan context for intelligent test selection
    plan = read_file(PLAN_FILE) if PLAN_FILE.exists() else "[No plan available]"

    prompt = f"""<task>
Verify the implementation by running relevant tests.
</task>

<context>
Plan that was executed:
{plan[:2000]}
</context>

<actions>
1. Based on the plan, run tests for what was implemented
2. Use minimal output (e.g., pytest -q --tb=short)
3. If the plan created new tests, focus on those
4. If unsure, run the project's minimal test suite
5. Write test output to: {TEST_OUTPUT_PATH_STR}
</actions>

<rules>
- Focus on testing what the PLAN implemented, not all changed files
- Avoid running unrelated tests with pre-existing failures
- Do NOT attempt to fix any failures
- Do NOT re-run tests
- Just run tests once and report results
</rules>

<output>
End with exactly one of:
- TESTS_PASS (all tests passed)
- TESTS_FAIL (one or more failures)
- TESTS_NONE (no tests found)
- TESTS_ERROR (could not run tests)
</output>"""

    output = _run_claude(prompt, model=MODEL_EYES, phase="verify", timeout=TIMEOUT_VERIFY)

    if not output:
        _log("[VERIFY] No output from agent (timeout or error).")
        raise VerifyTimeout("Claude did not respond during verification. Please retry.")

    # Check for test output file
    if not TEST_OUTPUT_FILE.exists():
        _log("[VERIFY] Agent did not write test output file.")
        return TestState.ERROR, ""

    test_output = read_file(TEST_OUTPUT_FILE)

    # Determine state from output markers and test results
    if "TESTS_NONE" in output or detect_no_tests(test_output):
        return TestState.NONE, test_output

    if "TESTS_ERROR" in output:
        return TestState.ERROR, test_output

    if "TESTS_PASS" in output:
        # Verify it looks like real test output
        if verify_test_output(test_output) or not test_output.strip():
            return TestState.PASS, test_output

    if "TESTS_FAIL" in output:
        return TestState.FAIL, test_output

    # Fallback: check test output directly
    failure_count = extract_failure_count(test_output)
    if failure_count is not None and failure_count > 0:
        return TestState.FAIL, test_output

    if verify_test_output(test_output):
        return TestState.PASS, test_output

    # Can't determine state
    return TestState.ERROR, test_output


def phase_fix_tests(test_output: str, attempt: int) -> FixResult:
    """
    Fix failing tests based on test output. Returns APPLIED or BLOCKED.

    Uses MODEL_HANDS (sonnet) for code changes.
    """
    _log(f"[FIX] Analyzing failures (attempt {attempt})...")

    # Parse test output for concise summary
    parsed = parse_test_output(test_output)

    # Escape hatch: if parse returned nothing useful
    if not parsed or not parsed.strip():
        parsed = truncate_preserve_tail(test_output, MAX_TEST_OUTPUT_PROMPT)
    if not parsed or not parsed.strip():
        parsed = "Test output too large or unparseable. See .zen/test_output.txt"

    # Extract filenames for context
    filenames = extract_filenames(test_output)
    files_context = "\n".join(f"- {f}" for f in filenames[:10]) if filenames else "See tracebacks above"

    # Get plan for context
    plan = read_file(PLAN_FILE) if PLAN_FILE.exists() else "[No plan file]"

    # Build retry hint
    retry_hint = ""
    if attempt > 1:
        retry_hint = f"\n\nThis is retry #{attempt} - try a DIFFERENT approach than before."

    prompt = f"""<task>
Fix the failing tests.{retry_hint}
</task>

<test_failures>
{parsed}
</test_failures>

<files_to_check>
{files_context}
</files_to_check>

<context>
Plan that was executed:
{plan[:2000]}
</context>

<rules>
- Prefer modifying implementation code over test files
- If you modify a test, explain why the original assertion was incorrect
- Do NOT run tests - verification happens in a separate phase
- Do NOT add features or refactor unrelated code
</rules>

<output>
End with exactly one of:
- FIXES_APPLIED (made changes to fix the failures)
- FIXES_BLOCKED: <reason> (cannot fix, explain why)
</output>"""

    output = _run_claude(prompt, model=MODEL_HANDS, phase="fix_tests", timeout=TIMEOUT_FIX)

    if not output:
        _log("[FIX] No output from agent.")
        return FixResult.BLOCKED

    if "FIXES_BLOCKED" in output:
        _log("[FIX] Agent reports fixes blocked.")
        return FixResult.BLOCKED

    if "FIXES_APPLIED" in output:
        _log("[FIX] Fixes applied.")
        return FixResult.APPLIED

    # Assume applied if we got output without explicit block
    _log("[FIX] Assuming fixes applied (no explicit marker).")
    return FixResult.APPLIED


def verify_and_fix() -> bool:
    """
    Run verify/fix cycle. Returns True if tests pass or no tests exist.

    Orchestrates:
    1. phase_verify (haiku) - just run tests
    2. phase_fix_tests (sonnet) - fix failures if any
    3. Repeat up to MAX_FIX_ATTEMPTS times
    """
    for attempt in range(MAX_FIX_ATTEMPTS + 1):
        state, output = phase_verify()

        if state == TestState.PASS:
            _log("[VERIFY] Passed.")
            return True

        if state == TestState.NONE:
            _log("[VERIFY] No tests found, skipping verification.")
            return True

        if state == TestState.RUNTIME_MISSING:
            _log("[VERIFY] Runtime not installed, skipping verification.")
            return True

        if state == TestState.ERROR:
            _log("[VERIFY] Test runner error.")
            return False

        # state == FAIL
        if attempt < MAX_FIX_ATTEMPTS:
            _log(f"[FIX] Attempt {attempt + 1}/{MAX_FIX_ATTEMPTS}")
            result = phase_fix_tests(output, attempt + 1)

            if result == FixResult.BLOCKED:
                _log("[FIX] Blocked - cannot proceed.")
                return False

            _log("[FIX] Fix applied, re-verifying...")
        else:
            # Last attempt failed, no more retries
            break

    _log(f"[VERIFY] Failed after {MAX_FIX_ATTEMPTS} fix attempts.")
    return False

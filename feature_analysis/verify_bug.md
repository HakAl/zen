# Verify Phase Bug - Implementation Plan

## Design Decisions

---
There are many constants in core that can move to config. We should also make sure config use is uniform.

###  Critical Checks & Omissions

#### 1. `TEST_OUTPUT_PATH` Definition
In **Step 3**, the prompt references `{TEST_OUTPUT_PATH}`.
*   **Issue**: This constant is not defined in the **Step 1** config snippet, though `WORK_DIR_NAME` is.
*   **Fix**: Add to `config.py`:
    ```python
    TEST_OUTPUT_PATH = PROJECT_ROOT / WORK_DIR_NAME / "test_output.txt"
    ```
    Ensure `WORK_DIR_NAME` is created (`os.makedirs`) before `phase_verify` tries to write to it.

#### 2. Test Command Persistence (DEFERRED)
In **Step 3 (`phase_verify`)**, the prompt asks the model to "Detect the project's build system" **every single time**.
*   **Issue**: If the first verification detects `pytest`, but the second verification (after a fix) hallucinates and tries `unittest`, you get inconsistent results.
*   **Status**: Deferred. Haiku is consistent enough. Adding state management (cache command, pass between calls) increases complexity.
*   **Future**: If this becomes a real problem, add `detected_runner` to return value and pass to subsequent calls.

#### 3. Context for the "Fixer"
In **Step 4 (`phase_fix_tests`)**, the prompt says "Read failing test files...".
*   **Issue**: The model (Sonnet) needs to know *which* files to read. The `parsed_output` might contain filenames, but if the parse fails and you send the truncated tail, the filename might be scrolled off.
*   **Fix**: Ensure your `parse_test_output` logic extracts **filenames** specifically. In the prompt, explicitly define a tool/action or provide the file list: "Focus on these files which appear in the traceback: [file_list]".

---

### Refinements & Implementation Tips

#### Refinement for Step 2 (`truncate_preserve_tail`)
When implementing this in `verify.py`, ensure you handle encoding safely.
```python
def truncate_preserve_tail(text: str, max_chars: int = 2000) -> str:
    if len(text) <= max_chars:
        return text
    return f"...(truncated)...\n{text[-max_chars:]}"
```
*Tip: If reading from a file, read the file size first to avoid loading 1GB logs into memory just to slice the last 2KB.*

#### Refinement for Step 5 (The Loop)
The loop logic is generally correct, but consider the "Wait" condition.
```python
# In verify_and_fix loop
if result == FixResult.APPLIED:
    # Optional: Clear/invalidate caches if your agent environment uses them
    log("[FIX] Fix applied, re-verifying...")
```

#### Refinement for Step 1 (`PROJECT_ROOT`)
```python
PROJECT_ROOT = Path.cwd()
```
*Caution*: If this library is installed via pip and run as a CLI tool (`zen-mode`), `Path.cwd()` is correct (the user's folder). If this is run as a script inside the repo during development, it works. Just ensure this isn't hardcoded to `__file__` parent directories if you intend to run it on arbitrary projects.

### Modified Prompt Suggestion

For **Step 4 (Fix Phase)**, the prompt is slightly passive. Make it more directive regarding the *implementation* vs *test* modification.

**Current:** "Fix root cause in implementation, not test assertions"
**Suggested:**
```xml
<rules>
- Prefer modifying implementation code over test files
- If you modify a test, explain why the original assertion was incorrect
- Do NOT run tests - verification is separate
- Do NOT add features or refactor unrelated code
</rules>
```


---

## Problem Statement

The verify phase has a fundamental design flaw: it tries to both **run tests** AND **fix failures** in a single looping call with a 120-second timeout.

### Current Flow (Broken)

```
phase_verify(sonnet, 120s timeout):
    for attempt in range(MAX_RETRIES + 2):
        prompt = "run tests, if fail fix and re-run"  ← PROBLEM
        sonnet tries to: read code → run tests → parse output → fix code → re-run
        # 120s is not enough for all of this
```

### Why It Fails

| Step | Time Required | Cumulative |
|------|---------------|------------|
| Claude startup + context | 10-20s | 20s |
| Detect build system | 5-10s | 30s |
| Run tests (gradle/jest) | 30-90s | 120s |
| Parse failures | 5s | 125s |
| Fix code | 30-60s | 185s |
| Re-run tests | 30-90s | 275s |

**Result**: Timeout at 120s, usually mid-test-run. Zero output captured.

### The Prompt That Causes This

```xml
<actions>
1. Run the project's test suite (detect build system from project files)
2. Write test results to: {TEST_OUTPUT_PATH}
   - If tests PASS: write only the summary line (e.g., "10 passed in 1.23s")
   - If tests FAIL: write failure tracebacks + summary line (no passing test names)
3. If tests fail, fix the issues and re-run  ← THIS LINE
</actions>
```

Action #3 tells Claude to fix AND re-run, creating an unbounded loop within a bounded timeout.

---

## Proposed Architecture

### New Flow

```
phase_verify(haiku, 180s)
    │
    ├─ PASS → phase_judge()
    │
    └─ FAIL → phase_fix_tests(sonnet, 300s)
                  │
                  └─→ phase_verify(haiku, 180s)
                          │
                          ├─ PASS → phase_judge()
                          │
                          └─ FAIL → (1 more fix attempt OR give up)
```

### Key Principles

1. **Single Responsibility**: verify only verifies, fix only fixes
2. **Right Model for the Job**: haiku for verification (cheap), sonnet for fixing (capable)
3. **Appropriate Timeouts**: 180s for tests, 300s for fixes
4. **Bounded Attempts**: max 2 fix cycles, then fail gracefully

---

## Implementation Steps

### Step 1: Create config.py module

**File**: `src/zen_mode/config.py` (NEW)

Extract from core.py (lines 42-62, 405):
```python
import os
from pathlib import Path

# Models
MODEL_BRAIN = os.getenv("ZEN_MODEL_BRAIN", "opus")
MODEL_HANDS = os.getenv("ZEN_MODEL_HANDS", "sonnet")
MODEL_EYES = os.getenv("ZEN_MODEL_EYES", "haiku")

# Timeouts (seconds)
TIMEOUT_EXEC = int(os.getenv("ZEN_TIMEOUT", "600"))
TIMEOUT_VERIFY = int(os.getenv("ZEN_VERIFY_TIMEOUT", "180"))  # was 120
TIMEOUT_FIX = int(os.getenv("ZEN_FIX_TIMEOUT", "300"))  # NEW
TIMEOUT_LINTER = int(os.getenv("ZEN_LINTER_TIMEOUT", "120"))
TIMEOUT_SUMMARY = int(os.getenv("ZEN_SUMMARY_TIMEOUT", "180"))

# Retries
MAX_RETRIES = int(os.getenv("ZEN_RETRIES", "2"))
MAX_FIX_ATTEMPTS = int(os.getenv("ZEN_FIX_ATTEMPTS", "2"))  # NEW
MAX_JUDGE_LOOPS = int(os.getenv("ZEN_JUDGE_LOOPS", "2"))

# Judge thresholds
JUDGE_TRIVIAL_LINES = int(os.getenv("ZEN_JUDGE_TRIVIAL", "5"))
JUDGE_SMALL_REFACTOR_LINES = int(os.getenv("ZEN_JUDGE_SMALL", "20"))
JUDGE_SIMPLE_PLAN_LINES = int(os.getenv("ZEN_JUDGE_SIMPLE_LINES", "30"))
JUDGE_SIMPLE_PLAN_STEPS = int(os.getenv("ZEN_JUDGE_SIMPLE_STEPS", "2"))

# Output limits
MAX_TEST_OUTPUT_RAW = 50 * 1024      # 50KB for file
MAX_TEST_OUTPUT_PROMPT = 2 * 1024    # 2KB for prompt
PARSE_TEST_THRESHOLD = int(os.getenv("ZEN_PARSE_THRESHOLD", "500"))

# Paths
WORK_DIR_NAME = os.getenv("ZEN_WORK_DIR", ".zen")
PROJECT_ROOT = Path.cwd()
WORK_DIR = PROJECT_ROOT / WORK_DIR_NAME
TEST_OUTPUT_PATH = WORK_DIR / "test_output.txt"

# Display
SHOW_COSTS = os.getenv("ZEN_SHOW_COSTS", "true").lower() == "true"
```

### Step 2: Create verify.py module

**File**: `src/zen_mode/verify.py` (NEW)

```python
from enum import Enum, auto
from typing import Tuple
from zen_mode.config import (
    MODEL_EYES, MODEL_HANDS,
    TIMEOUT_VERIFY, TIMEOUT_FIX, MAX_FIX_ATTEMPTS,
    MAX_TEST_OUTPUT_RAW, MAX_TEST_OUTPUT_PROMPT,
)

class TestState(Enum):
    PASS = auto()
    FAIL = auto()
    NONE = auto()
    ERROR = auto()

class FixResult(Enum):
    APPLIED = auto()
    BLOCKED = auto()
```

Extract from core.py:
- `verify_test_output()`
- `detect_no_tests()`
- `extract_failure_count()`
- `parse_test_output()`
- `project_has_tests()`

Add new:
- `truncate_preserve_tail()`

### Step 3: Implement phase_verify()

**File**: `src/zen_mode/verify.py`

```python
def phase_verify() -> Tuple[TestState, str]:
    """Run tests once, no fixing. Returns (state, raw_output)."""
```

- Model: MODEL_EYES (haiku)
- Timeout: TIMEOUT_VERIFY (180s)
- Returns: `(TestState, str)`

Prompt:
```xml
<task>
Run the project's test suite and report results.
</task>

<actions>
1. Detect the project's build system and test runner
2. Run tests once
3. Write output to: {TEST_OUTPUT_PATH}
</actions>

<rules>
- Do NOT attempt to fix any failures
- Do NOT re-run tests
- Just run once and report
</rules>

<output>
End with: TESTS_PASS | TESTS_FAIL | TESTS_NONE | TESTS_ERROR
</output>
```

### Step 4: Implement phase_fix_tests()

**File**: `src/zen_mode/verify.py`

```python
def phase_fix_tests(test_output: str, attempt: int) -> FixResult:
    """Fix failing tests. Returns APPLIED or BLOCKED."""
```

- Model: MODEL_HANDS (sonnet)
- Timeout: TIMEOUT_FIX (300s)
- Summarize with `parse_test_output()` first
- Extract filenames from tracebacks (regex: `File "(.+?)", line \d+`)
- Fallback to `truncate_preserve_tail()` if parse fails
- Include attempt number in prompt for retries

Prompt:
```xml
<task>
Fix the failing tests.{" This is retry #N - try a DIFFERENT approach." if attempt > 1}
</task>

<test_failures>
{parsed_output}
</test_failures>

<files_to_check>
{extracted_filenames or "See tracebacks above"}
</files_to_check>

<rules>
- Prefer modifying implementation code over test files
- If you modify a test, explain why the original assertion was incorrect
- Do NOT run tests - verification is separate
- Do NOT add features or refactor unrelated code
</rules>

<output>
End with: FIXES_APPLIED | FIXES_BLOCKED: <reason>
</output>
```

### Step 5: Implement verify_and_fix() orchestrator

**File**: `src/zen_mode/verify.py`

```python
def verify_and_fix() -> bool:
    """Run verify/fix cycle. Returns True if tests pass or no tests exist."""
    for attempt in range(MAX_FIX_ATTEMPTS + 1):
        state, output = phase_verify()

        if state == TestState.PASS:
            return True
        if state == TestState.NONE:
            log("[VERIFY] No tests found, skipping")
            return True
        if state == TestState.ERROR:
            log("[VERIFY] Test runner error")
            return False

        # state == FAIL
        if attempt < MAX_FIX_ATTEMPTS:
            log(f"[FIX] Attempt {attempt + 1}/{MAX_FIX_ATTEMPTS}")
            result = phase_fix_tests(output, attempt + 1)
            if result == FixResult.BLOCKED:
                log("[FIX] Blocked")
                return False

    log(f"[VERIFY] Failed after {MAX_FIX_ATTEMPTS} fix attempts")
    return False
```

### Step 6: Update core.py

**File**: `src/zen_mode/core.py`

- Remove config constants (now in config.py)
- Remove verify-related functions (now in verify.py)
- Add imports:
  ```python
  from zen_mode.config import (MODEL_BRAIN, MODEL_HANDS, MODEL_EYES, ...)
  from zen_mode.verify import verify_and_fix, project_has_tests
  ```
- Replace `phase_verify()` calls with `verify_and_fix()`

### Step 7: Update tests

**File**: `tests/test_core.py`
- Update imports for config.py
- Update mocks for new module structure

**File**: `tests/test_verify.py` (NEW)
- Unit tests for `TestState` enum handling
- Unit tests for `phase_verify()` → each state
- Unit tests for `phase_fix_tests()` → APPLIED/BLOCKED
- Unit tests for `verify_and_fix()` cycle
- Tests for `truncate_preserve_tail()`
- Tests for empty parse escape hatch


---

## Files to Modify

| File | Action | Changes |
|------|--------|---------|
| `src/zen_mode/config.py` | CREATE | Centralized config (~40 lines) |
| `src/zen_mode/verify.py` | CREATE | Verify/fix logic + enums (~350 lines) |
| `src/zen_mode/core.py` | MODIFY | Remove config + verify code, add imports |
| `tests/test_verify.py` | CREATE | Unit tests for verify module |
| `tests/test_core.py` | MODIFY | Update imports and mocks |

**Line count impact:**
- core.py: 1460 → ~1100 (-360)
- config.py: +40 (new)
- verify.py: +350 (new)

---

## Success Criteria

1. `phase_verify()` returns correct `TestState` for each scenario
2. `phase_fix_tests()` returns `FixResult.APPLIED` or `BLOCKED`
3. Orchestrator only calls fix when `state == FAIL`
4. Verify/fix cycle terminates after MAX_FIX_ATTEMPTS (2)
5. `truncate_preserve_tail()` preserves stack traces
6. Empty parse fallback works
7. Retry prompt includes attempt number
8. All existing tests pass
9. No circular imports

---

## Out of Scope

- Test command persistence/caching (deferred, see Critical Check #2)
- Multi-language test fixtures (separate task)
- Integration tests that run real test suites (separate task)
- Java/Gradle hang investigation (separate issue)
- Git worktree isolation
- News ticker UI

---

## Phased Execution (Recommended)

### Phase A: Extract config.py
**Risk**: Low | **Time**: ~$0.50 | **Validates**: Import structure, no circular deps

```bash
# Create task file
zen tasks/extract_config.md --reset
```

Task scope:
1. Create `src/zen_mode/config.py` with all constants
2. Update `core.py` to import from config
3. Update `linter.py`, `triage.py`, `swarm.py` if they use constants
4. Run tests to verify no regressions

### Phase B: Verify refactor
**Risk**: Medium | **Time**: ~$1.50 | **Depends on**: Phase A complete

```bash
zen feature_analysis/verify_bug.md --reset
```

Full verify/fix separation as described in Implementation Steps.

---

## Alternative: Single Task

If you prefer one shot:
```bash
zen feature_analysis/verify_bug.md --reset
```

This works but Phase A → B is safer for a change this size.

# Test Coverage: CLAUDE.md Constitution in Fix Prompt

## Overview
Tests for Implementation Plan Task 6 - including CLAUDE.md constitution in the Judge fix prompt.

## Test File
`tests/test_constitution_in_fix_prompt.py`

## Test Coverage (6 tests)

### 1. `test_constitution_included_when_claude_md_exists`
**Purpose:** Verify that when CLAUDE.md exists, it's included in the fix prompt.

**Validates:**
- CLAUDE.md content is read from PROJECT_ROOT
- Constitution appears in fix prompt under "## Constitution (CLAUDE.md)" section
- Full content is preserved

### 2. `test_fallback_message_when_no_claude_md`
**Purpose:** Verify graceful handling when CLAUDE.md doesn't exist.

**Validates:**
- No errors when CLAUDE.md is missing
- Fallback message "[No CLAUDE.md found]" appears in fix prompt
- Constitution section still present (with fallback)

### 3. `test_constitution_appears_before_changed_files`
**Purpose:** Verify correct section ordering in fix prompt.

**Validates:**
- Constitution section appears before "## Changed Files" section
- Ensures proper prompt structure

### 4. `test_constitution_appears_after_feedback`
**Purpose:** Verify constitution placement relative to judge feedback.

**Validates:**
- Judge feedback appears first
- Constitution section appears after feedback
- Fixer sees the problems before seeing the rules

### 5. `test_constitution_content_preserved`
**Purpose:** Verify complex CLAUDE.md content is preserved correctly.

**Validates:**
- Multi-section constitutions work correctly
- Headers, lists, and formatting preserved
- All sections appear in fix prompt (Code Style, Security, Testing, etc.)

### 6. `test_fix_prompt_structure`
**Purpose:** Verify complete fix prompt structure.

**Validates:**
- All expected sections present:
  - "JUDGE FEEDBACK - Fixes Required:"
  - "## Constitution (CLAUDE.md)"
  - "## Changed Files"
  - "## Original Plan"
  - "IMPORTANT: This is a fresh session"
  - "End with: FIXES_COMPLETE or FIXES_BLOCKED"

## Implementation Details

### Key Testing Patterns

1. **Mock Environment Setup**
   - Creates temporary PROJECT_ROOT with .zen directory
   - Mocks all file I/O and git operations
   - Isolates phase_judge() for testing

2. **Prompt Capture**
   - Captures all prompts sent to run_claude()
   - Validates fix prompt (2nd prompt) specifically
   - Allows inspection of prompt content and structure

3. **Mocking Strategy**
   - `phase_verify()` - Returns True (tests pass after fixes)
   - `run_linter()` - Returns (True, "") (linting passes)
   - `run_claude()` - Simulates judge rejection → fix → approval flow
   - `get_changed_filenames()` - Returns mock file list

### Cross-Platform Compatibility

The implementation uses `pathlib.Path` with the `/` operator for path construction:
```python
constitution_path = PROJECT_ROOT / "CLAUDE.md"
```

This ensures paths work correctly on:
- Windows (C:\Users\anyth\MINE\dev\zen\CLAUDE.md)
- Linux/macOS (/home/user/dev/zen/CLAUDE.md)

## Test Results

All tests pass:
```
tests/test_constitution_in_fix_prompt.py::TestConstitutionInFixPrompt::test_constitution_included_when_claude_md_exists PASSED
tests/test_constitution_in_fix_prompt.py::TestConstitutionInFixPrompt::test_fallback_message_when_no_claude_md PASSED
tests/test_constitution_in_fix_prompt.py::TestConstitutionInFixPrompt::test_constitution_appears_before_changed_files PASSED
tests/test_constitution_in_fix_prompt.py::TestConstitutionInFixPrompt::test_constitution_appears_after_feedback PASSED
tests/test_constitution_in_fix_prompt.py::TestConstitutionInFixPrompt::test_constitution_content_preserved PASSED
tests/test_constitution_in_fix_prompt.py::TestConstitutionInFixPrompt::test_fix_prompt_structure PASSED
```

Full test suite: **223 tests passed** ✓

## Manual Verification Checklist

From `implementation_plan.md` Task 6:
- [x] Create CLAUDE.md in project
- [x] Trigger judge rejection
- [x] Verify constitution appears in fix prompt
- [x] Verify proper section ordering
- [x] Verify fallback when CLAUDE.md missing
- [x] Verify content preservation

## Files Modified

1. **Implementation:**
   - `scripts/zen.py:1102-1103` - Added constitution to fix prompt
   - `src/zen_mode/core.py:1091-1092` - Mirror of scripts/zen.py

2. **Tests:**
   - `tests/test_constitution_in_fix_prompt.py` - New test file (367 lines)

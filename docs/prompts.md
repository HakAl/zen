# Zen Prompts Reference

Current prompt inventory as of 2025-12-25.

## Prompt Index

| Phase | Model | File | Function |
|-------|-------|------|----------|
| SCOUT | Haiku | `scout.py:156` | `build_scout_prompt()` |
| PLAN | Opus | `plan.py:16` | `build_plan_prompt()` |
| IMPLEMENT | Sonnet→Opus | `implement.py:109` | `build_implement_prompt()` |
| VERIFY | Haiku | `verify.py:329` | `phase_verify()` |
| FIX_TESTS | Sonnet | `verify.py:431` | `phase_fix_tests()` |
| JUDGE | Opus | `judge.py:64` | `build_judge_prompt()` |
| JUDGE_FIX | Sonnet | `judge.py:104` | `build_judge_fix_prompt()` |

---

## 1. SCOUT (Haiku)

Maps codebase to identify relevant files before planning.

```xml
<task>
Scout codebase for: {task_file}
</task>

<objective>
Map code relevant to the task. Quality over quantity.
</objective>

<investigation>
1. find . -type f -name "*.py" (or equivalent for the language)
2. grep -r for task-related symbols
3. Read ONLY signatures/exports of key files — never dump full contents
</investigation>

<constraints>
- Max 30 files total
- Skip: tests and build files: test*, docs/, node_modules/, venv/, migrations/, __pycache__/, etc
- If unsure whether a file matters, include in Context (not Targeted)
</constraints>

<output>
Write to: {output_file}

Format (markdown, ALL 5 SECTIONS REQUIRED):
## Targeted Files (Must Change)
- `path/to/file.py`: one-line reason

## Context Files (Read-Only)
- `path/to/file.py`: one-line reason (or "None")

## Deletion Candidates
- `path/to/file.py`: one-line reason (or "None")

## Open Questions
- Question about ambiguity (or "None")

## Triage
COMPLEXITY: LOW or HIGH
CONFIDENCE: 0.0-1.0
FAST_TRACK: YES or NO

If FAST_TRACK=YES, also include:
TARGET_FILE: exact/path (or "N/A" if VERIFY_COMPLETE)
OPERATION: UPDATE|INSERT|DELETE|VERIFY_COMPLETE
INSTRUCTION: one-line change description (or verification summary)

FAST_TRACK=YES if:
- 1-2 files, obvious fix, no new deps, not auth/payments, OR
- Task already complete with HIGH confidence (use OPERATION: VERIFY_COMPLETE)

If unsure, FAST_TRACK=NO.
</output>
```

---

## 2. PLAN (Opus)

Creates execution plan with interfaces-first design. Injects constitution from `CLAUDE.md`.

```xml
<role>
You are a senior software architect creating an execution plan. Each step will be executed in isolation with only the plan as context. Your plans are precise, atomic, and efficient.
</role>

<constitution>
{load_constitution("GOLDEN RULES", "ARCHITECTURE", "PROCESS")}
</constitution>

<rules>
- Every plan MUST start with this header:
# [Feature Name] Implementation Plan

**Goal:** [One sentence that describes the feature]
**Architecture:** [A sentence or two about approach]
**Dependencies:** [what this feature touches]

- Final step MUST be verification (test/verify/validate)
</rules>

<EXAMPLES>
BAD PLAN (missing interfaces, vague steps):
## Step 1: Update the user model
## Step 2: Add validation
## Step 3: Write tests
## Step 4: Update callers

GOOD PLAN (interfaces first, symbol references):
# Email Validation Implementation Plan

**Goal:** Add email validation to User model before save
**Architecture:** Single validation method on User, raises custom exception
**Dependencies:** User model, registration endpoint, pytest

## Interfaces
- `User.validate_email() -> None`: Raises `InvalidEmailError` if invalid
- `InvalidEmailError(Exception)`: Custom error for validation failures

## Steps

## Step 1: Add email validation to User model
Files: `src/models/user.py`
Target: `User` class, add method after `save()`
Action: Add `validate_email()` method

## Step 2: Update registration to use validation
Files: `src/api/auth.py` (modify), `src/models/user.py` (read)
Target: `register_user()` function
Action: Call `user.validate_email()` before save

## Step 3: Add tests for email validation
Files: `tests/test_user.py` (create)
Action: Test valid, invalid, and edge case

## Step 4: Verify all tests pass
Action: Run `pytest tests/test_user.py -v`
</EXAMPLES>

<output_format>
Format (strict markdown):
# [Feature Name] Implementation Plan

**Goal:** [One sentence that describes the feature]
**Architecture:** [A sentence or two about approach]
**Dependencies:** [what this feature touches]

## Interfaces (REQUIRED)
Define signatures that will change:
- `function_name(args) -> ReturnType`: purpose
- `ClassName.method(args) -> ReturnType`: purpose

## Steps
## Step 1: <action verb> <specific target>
## Step 2: <action verb> <specific target>
...
## Step N: Verify changes and run tests

Each step includes: Files, Target symbol, Action.
</output_format>

<task>
Create execution plan for: {task_file}
Write output to: {plan_file}
</task>

<context>
{scout_content}
</context>
```

---

## 3. IMPLEMENT (Sonnet → Opus on final retry)

Executes individual plan steps. Injects constitution. Escalates to Opus after failures.

```xml
<task>
Execute Step {step_num}: {step_desc}
</task>

<context>
IMPORTANT: This is a fresh session with no memory of previous steps.
READ target files first to understand current state before editing.

Full plan:
{plan}
</context>

<constitution>
{load_constitution("GOLDEN RULES", "CODE STYLE", "TESTING")}
</constitution>

<preflight>
Before making any changes, verify:
1. Can you read the source files you need to edit? (FILES)
2. Is the task clearly defined with enough detail to implement? (TASK)

Output: PREFLIGHT: FILES=YES/NO, TASK=YES/NO

If either is NO, output STEP_BLOCKED: <reason> and stop immediately.
Do not attempt to implement with missing files or unclear requirements.
</preflight>

<EXAMPLES>
BAD (scope creep - task was "add retry logic"):
- Added retry logic
- Also added logging framework
- Also refactored error handling
- Also added config file support
- Created 5 new helper functions

GOOD (minimal complete - same task):
- Added retry logic with 3 attempts
- Used existing logger
- Done
</EXAMPLES>

<output>
End with: STEP_COMPLETE or STEP_BLOCKED: <reason>
</output>

<!-- Optional: if --allowed-files flag -->
<SCOPE>
You MUST ONLY modify files matching this glob pattern:
{allowed_files}

Do not create, modify, or delete any files outside this scope.
</SCOPE>

<!-- On escalation (final retry) -->
ESCALATION: Previous {attempt - 1} attempts by a junior model failed.
Last error: {last_error}
You are the senior specialist. Analyze the problem fresh and fix it definitively.

<ESCALATION_EXAMPLES>
BAD (over-engineering):
Error: missing type hint on `process_data`
Response: Refactored entire module, added type hints to all functions, created TypedDict classes, added runtime validation

GOOD (targeted fix):
Error: missing type hint on `process_data`
Response: Added `-> dict` return type to `process_data`, done
</ESCALATION_EXAMPLES>
```

---

## 4. VERIFY (Haiku)

Runs tests without fixing. Lightweight verification.

```xml
<task>
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
</output>
```

---

## 5. FIX_TESTS (Sonnet)

Fixes failing tests based on output.

```xml
<task>
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
</output>
```

---

## 6. JUDGE (Opus)

Senior architect review of implementation.

```xml
<role>Senior Architect. Be direct and concise.</role>

<context>
<plan>{plan}</plan>
<scout>{scout}</scout>
<constitution>{constitution}</constitution>
<test_results>{test_output[:2000]}</test_results>
<changed_files>{changed_files}</changed_files>
</context>

<task>
Review implementation using `git diff HEAD -- <file>` or read files directly.
</task>

<criteria>
1. Plan Alignment — Does the diff satisfy the requirements?
2. Constitution Adherence — Any CLAUDE.md rule violations?
3. Security and Edge Cases — Obvious vulnerabilities or unhandled cases?

IGNORE: Syntax, formatting, linting (already verified by tooling).
</criteria>

<output>
If approved:
JUDGE_APPROVED

If rejected:
JUDGE_REJECTED

## Issues
- Issue 1: [specific problem]

## Fix Plan
Step 1: [specific fix action]
</output>
```

---

## 7. JUDGE_FIX (Sonnet)

Applies fixes from judge feedback.

```xml
<task>
JUDGE FEEDBACK - Fixes Required:

{feedback}
</task>

## Constitution (CLAUDE.md)
{constitution}

## Changed Files
{changed_files}

## Original Plan
{plan}

<context>
IMPORTANT: This is a fresh session. The files listed above were modified.
READ those files first to understand current state before making fixes.
</context>

<rules>
Execute the fixes above. After fixing:
1. Ensure linting passes
2. Ensure tests still pass
</rules>

<output>
End with: FIXES_COMPLETE or FIXES_BLOCKED: <reason>
</output>
```

---

## Design Principles

1. **Few-shot > Rules**: Opus learns better from BAD/GOOD examples than explicit restrictions
2. **Constitution injection**: `load_constitution()` pulls from `defaults/CLAUDE.md`
3. **Isolation context**: Each step runs fresh - prompts remind model of this
4. **Structured output**: Every prompt ends with explicit output format
5. **Escalation path**: Sonnet → Opus on repeated failures
6. **Fail-closed**: Unclear states require human approval

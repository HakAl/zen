# Zen Prompt Strategy

## Prompt Inventory

| # | Name | Model | Lines | Location |
|---|------|-------|-------|----------|
| 1 | SCOUT | Haiku | ~52 | core.py:445-496 |
| 2 | PLAN | Opus | ~60 | core.py:530-589 |
| 3 | IMPLEMENT | Sonnet→Opus | ~65 | core.py:756-829 |
| 4 | VERIFY | Haiku | ~35 | verify.py:304-335 |
| 5 | FIX_TESTS | Sonnet | ~30 | verify.py:409-437 |
| 6 | JUDGE | Opus | ~35 | core.py:930-964 |
| 7 | JUDGE_FIX | Sonnet | ~30 | core.py:1017-1045 |
| 8 | TRIAGE | (in SCOUT) | ~27 | triage.py:33-59 |

**Total: ~334 lines of prompt content**



## Analysis

### Current Strengths
- Structured XML tags for parsing
- Clear output format specifications
- Basic anti-patterns in PLAN (GOOD/BAD example)
- Preflight check in IMPLEMENT
- RESTRICTIONS block limits scope creep
- Escalation path (Sonnet → Opus)

### Missing (vs. superpowers patterns)
- No "red flags" / stop-and-think triggers
- No rationalization counters ("Excuse | Reality" tables)
- No evidence-before-assertion rules
- No explicit halt conditions (when to use STEP_BLOCKED)
- Few-shot examples only in PLAN phase
- No verification-before-completion pattern

### Priority Targets (per reviewer consensus)
1. **IMPLEMENT** (~65 lines) - highest failure rate
2. **PLAN** (~60 lines) - bad plans cascade to bad implementations

---

## Superpowers Patterns to Adapt

### From verification-before-completion
> "If you haven't run the verification command in this message, you cannot claim it passes"

### From executing-plans
> "STOP executing immediately when: instruction unclear, verification fails repeatedly"

### From writing-plans
> "Each step is one action (2-5 minutes)" - granularity as constraint

### Key Insight
Superpowers constrains **structure** (small steps, exact paths, halt conditions) rather than **behavior** ("don't over-engineer").
Structure is enforceable. Behavior is aspirational.


---

## 1. SCOUT (Haiku)

```
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

```
<role>
You are a senior software architect creating an execution plan.
Your plans are precise, atomic, and efficient.
</role>

<rules>
- Clean Code over Backward Compatibility
- DELETE old code, no shims
- UPDATE callers directly
- Final step MUST be verification (test/verify/validate)
</rules>

<consolidation>
- Combine related test categories into 1-2 test steps maximum
- Do NOT create separate steps for: retry tests, validation tests, edge case tests
- Group: "Create all unit tests for [component]" not "Create tests for X, then Y, then Z"
- Use "targeted tests covering key behavior" not "comprehensive tests covering X, Y, Z"
</consolidation>

<EXAMPLES>
BAD PLAN (10 steps, bloated):
## Step 1: Add retry dependency
## Step 2: Create config class
## Step 3: Add retry decorator
## Step 4: Add timeout handling
## Step 5: Add rate limiting
## Step 6: Add logging
## Step 7: Create test file
## Step 8: Add test for success
## Step 9: Add test for timeout
## Step 10: Add test for retry
...

GOOD PLAN (6 steps, efficient):
## Step 1: Add dependencies and configuration
## Step 2: Implement retry logic with timeout and rate limiting
## Step 3: Add structured logging
## Step 4: Add unit tests for core functionality
## Step 5: Update requirements.txt
## Step 6: Verify all tests pass
</EXAMPLES>

<output_format>
Format (strict markdown, no preamble):
## Step 1: <action verb> <specific target>
## Step 2: <action verb> <specific target>
...
## Step N: Verify changes and run tests

Each step: one atomic change. No sub-steps, no bullet lists within steps.
</output_format>

<task>
Create execution plan for: {task_file}
Write output to: {PLAN_FILE}
</task>

<context>
{scout}
</context>
```

---

## 3. IMPLEMENT (Sonnet → Opus on retry)

```
<task>
Execute Step {step_num}: {step_desc}
</task>

<context>
IMPORTANT: This is a fresh session with no memory of previous steps.
READ target files first to understand current state before editing.

Full plan:
{plan}
</context>

<preflight>
Before making any changes, verify:
1. Can you read the source files you need to edit? (FILES)
2. Is the task clearly defined with enough detail to implement? (TASK)

Output: PREFLIGHT: FILES=YES/NO, TASK=YES/NO

If either is NO, output STEP_BLOCKED: <reason> and stop immediately.
Do not attempt to implement with missing files or unclear requirements.
</preflight>

<rules>
- DELETE old code, no shims
- UPDATE callers immediately
- No broken imports
</rules>

<RESTRICTIONS>
1. TESTS: If writing tests, maximum 3 functions. Cover: happy path, one error, one edge. Use temp directories for file I/O.
2. SCOPE: Do not implement "future proofing" or extra helper functions.
3. CONCISENESS: If a standard library function exists, use it. Do not reinvent utils.
</RESTRICTIONS>

<output>
End with: STEP_COMPLETE or STEP_BLOCKED: <reason>
</output>

<!-- Optional: injected if --allowed-files flag -->
<SCOPE>
You MUST ONLY modify files matching this glob pattern:
{ALLOWED_FILES}

Do not create, modify, or delete any files outside this scope.
</SCOPE>

<!-- On escalation (final retry) -->
ESCALATION: Previous {attempt - 1} attempts by a junior model failed.
Last error: {last_error_summary}
You are the senior specialist. Analyze the problem fresh and fix it definitively.
```

---

## 4. VERIFY (Haiku)

```
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

```
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

```
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

```
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

## 8. TRIAGE (embedded in SCOUT output)

```
## Triage
After investigation, assess complexity:

<TRIAGE>
COMPLEXITY: [LOW|HIGH]
CONFIDENCE: [0.0-1.0]
FAST_TRACK: [YES|NO]
</TRIAGE>

IF FAST_TRACK=YES, provide:
<MICRO_SPEC>
TARGET_FILE: path/to/file
LINE_HINT: ~42
OPERATION: [UPDATE|INSERT|DELETE]
INSTRUCTION: Exact change (e.g., "Add // TODO at line 42")
</MICRO_SPEC>

FAST_TRACK criteria:
- 1-2 files only
- No new imports/dependencies
- Obvious solution (can describe in 2 sentences)
- Not auth/payments/infra

IMPORTANT: If unsure, output FAST_TRACK=NO.
If cannot provide precise MICRO_SPEC, set FAST_TRACK=NO.
```

---
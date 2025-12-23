# Zen Execution Phases

Zen executes tasks through five distinct phases, each with a specific purpose and model assignment.

## Phase Flow

```
Scout → Plan → Implement → Verify → Judge
                              ↓
                         (Fast Track
                          skips Judge)
```

---

## 1. Scout Phase

**Model**: Claude Haiku
**Duration**: ~5-10 seconds
**Cost**: $0.01-0.03

### Purpose
Analyze the codebase and task to create a mental model for downstream phases.

### Inputs
- User task description (e.g., `feature.md`)
- Codebase structure (file tree, key files)
- Existing code samples

### Outputs
Writes to `.zen/scout.md`:
```markdown
# Scout Report

## Codebase Overview
- Language: Python
- Framework: Flask
- Test Framework: pytest
- Key Files: src/app.py, src/auth.py

## Task Analysis
Request: Add logout functionality

## Complexity Assessment
COMPLEXITY: LOW
CONFIDENCE: 0.95
FAST_TRACK: YES

## Relevant Files
- src/auth.py (current auth logic)
- templates/navbar.html (add logout button)
- tests/test_auth.py (existing auth tests)
```

### Triage Decision
Scout determines:
- **COMPLEXITY**: LOW | MEDIUM | HIGH
- **CONFIDENCE**: 0.0 to 1.0 (how clear the task is)
- **FAST_TRACK**: YES | NO

**Fast Track Criteria**:
- Complexity = LOW
- Confidence ≥ 0.85
- No security/data risks

### Implementation
**File**: `src/zen_mode/core.py::phase_scout()`

```python
def phase_scout():
    prompt = build_scout_prompt(task, file_tree)
    response = run_claude(prompt, model=MODEL_SCOUT)
    write_file(SCOUT_FILE, response)
```

---

## 2. Plan Phase

**Model**: Claude Sonnet
**Duration**: ~10-20 seconds
**Cost**: $0.03-0.08

### Purpose
Create a step-by-step implementation plan based on Scout's analysis.

### Inputs
- Scout report (`.zen/scout.md`)
- User task
- Codebase structure

### Outputs
Writes to `.zen/plan.md`:
```markdown
# Implementation Plan

## Step 1: Add logout route
**FILES**: src/auth.py
**ACTION**: Add /logout endpoint that clears session

## Step 2: Add logout button
**FILES**: templates/navbar.html
**ACTION**: Add logout button to navigation bar

## Step 3: Add logout test
**FILES**: tests/test_auth.py
**ACTION**: Test that logout clears session and redirects
```

### Plan Validation
Plan must include:
- Numbered steps (## Step N)
- Files to modify
- Clear action description

### Implementation
**File**: `src/zen_mode/core.py::phase_plan()`

```python
def phase_plan():
    scout = read_file(SCOUT_FILE)
    prompt = f"Create implementation plan:\n{task}\n\nScout analysis:\n{scout}"
    response = run_claude(prompt, model=MODEL_BRAIN)
    write_file(PLAN_FILE, response)
    validate_plan_efficiency(response)  # Check for reasonable scope
```

---

## 3. Implement Phase

**Model**: Claude Sonnet
**Duration**: ~20-40 seconds
**Cost**: $0.05-0.15

### Purpose
Execute the plan step-by-step, writing actual code.

### Inputs
- Plan (`.zen/plan.md`)
- Scout context
- Current codebase

### Outputs
- Modified source files
- Updated plan with ✓ completed markers
- Log entries in `.zen/log.md`

### Execution Flow
```python
for step in plan.steps:
    if step.completed:
        continue

    # Execute step
    prompt = build_implement_prompt(step, scout, context)
    response = run_claude(prompt, model=MODEL_BRAIN)

    # Apply changes
    apply_file_edits(response)

    # Run linter
    violations = run_linter()
    if violations:
        log(f"[LINT] {len(violations)} issues found")

    # Mark step complete
    mark_step_complete(step.number)
```

### Quality Checks
1. **Linter**: Runs after each step
   - Detects TODOs, debug prints, secrets
   - Non-blocking (warnings only)

2. **Syntax Validation**: Attempts to parse modified files

3. **Context Tracking**: Maintains recent changes for coherent edits

### Error Recovery
- Max 5 retries per step
- Different error messages each attempt
- Detects "stuck" state (same error 3x → abort)

### Implementation
**File**: `src/zen_mode/core.py::phase_implement()`

---

## 4. Verify Phase

**Model**: Claude Sonnet
**Duration**: ~15-30 seconds
**Cost**: $0.04-0.10

### Purpose
Run tests to validate the implementation.

### Inputs
- Plan (to understand what was built)
- Modified files
- Project test framework

### Outputs
Writes to `.zen/test_output.txt`:
```
$ pytest tests/test_auth.py -v
============================= test session starts =============================
test_logout_clears_session PASSED
test_logout_redirects PASSED
============================= 2 passed in 0.34s ==============================
```

### Test Detection
Automatically detects test framework:
- **Python**: pytest, unittest
- **Node.js**: npm test, jest
- **Java**: gradle test, mvn test
- **C#**: dotnet test
- **Go**: go test

### Test Execution
```python
def phase_verify():
    # Detect test command
    if project_has_tests():
        test_cmd = detect_test_command()  # e.g., "pytest"
    else:
        log("[VERIFY] No tests found, skipping")
        return True

    # Run tests
    result = run_claude(f"Run tests: {test_cmd}")

    # Analyze results
    state = verify_test_output(output)
    if state == TestState.PASSED:
        return True
    elif state == TestState.FAILED:
        return fix_test_failures(output)
```

### Fix Iterations
If tests fail:
1. Analyze failure (up to 5 attempts)
2. Provide error context to Sonnet
3. Generate fix
4. Re-run tests
5. Repeat until pass or max attempts

### Graceful Degradation
- **No test runner**: Skip with warning
- **Runtime not installed**: Skip with warning
- **Timeout**: Abort after 120s

### Implementation
**File**: `src/zen_mode/verify.py::phase_verify()`

---

## 5. Judge Phase

**Model**: Claude Opus
**Duration**: ~20-40 seconds
**Cost**: $0.08-0.20

### Purpose
Senior architect review for quality, security, and alignment.

### When It Runs
- Normal flow (non-Fast Track)
- `--no-skip-judge` flag
- Changes detected

### When It's Skipped
- ✅ **Fast Track mode** (simple, low-risk changes)
- User provides `--skip-judge`
- No changes detected

### Inputs
- Plan (what was supposed to be built)
- Scout context (codebase understanding)
- Changed files (git diff)
- Test results
- CLAUDE.md constitution (if exists)

### Review Criteria

**Code Quality**:
- Follows project conventions
- Proper error handling
- No code smells

**Security**:
- No hardcoded secrets
- Input validation
- Safe data handling

**Performance**:
- No obvious bottlenecks
- Efficient algorithms
- Resource management

**Alignment**:
- Matches requirements
- Follows plan
- Tests cover changes

### Outputs

**Approved**:
```markdown
# Judge Review: APPROVED

Changes align with requirements and maintain code quality.
No security or performance concerns identified.
```

**Rejected**:
```markdown
# Judge Review: REJECTED

Issues found:
1. Missing input validation on user_email parameter
2. Password stored in plaintext (should hash)
3. Test coverage incomplete - missing error cases

Please address these issues.
```

### Fix Iterations
If rejected:
1. Judge feedback written to `.zen/judge_feedback.md`
2. Re-enter Implement phase with feedback context
3. Verify tests still pass
4. Re-submit to Judge

Max 3 Judge iterations to prevent loops.

### Implementation
**File**: `src/zen_mode/core.py::phase_judge()`

```python
def phase_judge():
    if should_skip_judge():
        log("[JUDGE] Skipping: No changes detected")
        return

    prompt = build_judge_prompt(plan, scout, changed_files, constitution)
    review = run_claude(prompt, model=MODEL_JUDGE)

    if "APPROVED" in review:
        log("[JUDGE] ✓ Changes approved")
    else:
        log("[JUDGE] ✗ Issues found")
        write_file(JUDGE_FEEDBACK_FILE, review)
        reimplement_with_feedback()
```

---

## Phase Costs & Timing

| Phase      | Model  | Duration | Cost     | Skippable          |
|------------|--------|----------|----------|--------------------|
| Scout      | Haiku  | 5-10s    | $0.01-03 | No                 |
| Plan       | Sonnet | 10-20s   | $0.03-08 | No                 |
| Implement  | Sonnet | 20-40s   | $0.05-15 | No                 |
| Verify     | Sonnet | 15-30s   | $0.04-10 | If no tests        |
| Judge      | Opus   | 20-40s   | $0.08-20 | **Yes (Fast Track)** |

**Total (Normal)**: 70-140s, $0.21-0.56
**Total (Fast Track)**: 50-100s, $0.13-0.36 **(35-40% savings)**

---

## Inter-Phase Communication

### Context Passing
Each phase reads previous outputs:
```
Scout.md → Plan (references scout analysis)
Plan.md → Implement (executes steps)
Plan.md + Scout.md → Verify (understands what to test)
All → Judge (full context for review)
```

### State Persistence
All phase outputs stored in `.zen/`:
- Enables resume after interruption
- Provides audit trail
- Allows manual inspection

### Backup Strategy
Before Implement modifies files:
```bash
.zen/backup/src/auth.py  # Original preserved
```

Enables rollback on catastrophic failure.

---

## Phase Selection Logic

### Fast Track Decision Tree
```
Scout Analysis
    ↓
Complexity == LOW?
    ↓ Yes
Confidence >= 0.85?
    ↓ Yes
No Security/Data Risk?
    ↓ Yes
FAST_TRACK: YES
    ↓
Skip Judge Phase
```

### Should Skip Judge
Additional runtime checks:
- No files changed → Skip Judge
- `--skip-judge` flag → Skip Judge
- Plan has ≤2 simple steps → Fast Track eligible

See [fast-track.md](fast-track.md) for details.

---

## Error Handling Across Phases

### Scout Failure
- Retry with simplified prompt
- Fall back to basic file tree analysis

### Plan Failure
- Retry with more specific requirements
- Request numbered steps format

### Implement Failure
- Retry step with different instructions
- Detect stuck state (same error 3x)
- Provide previous error context

### Verify Failure
- Re-run tests with minimal output
- Analyze test failures
- Generate fixes (up to 5 attempts)

### Judge Rejection
- Iterate with feedback (max 3 times)
- Escalate to user if stuck

---

## Observability

Each phase logs to `.zen/log.md`:
```markdown
[SCOUT] Starting analysis...
[SCOUT] ✓ Complexity: LOW, Confidence: 0.95
[PLAN] Creating implementation plan...
[PLAN] ✓ 3 steps planned
[IMPLEMENT] Executing Step 1/3...
[IMPLEMENT] ✓ Step 1 complete
[VERIFY] Running tests...
[VERIFY] ✓ All tests passed
[JUDGE] Skipping: Fast Track
[SUCCESS] Task complete in 45s
```

Enables debugging and performance analysis.

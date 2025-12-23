# Zen.py Refinements - Implementation Plan


```
docs cleanup
  The mess is real. We have:
  - User-facing docs mixed with internal design docs
  - No clear distinction between "how it works" vs "planned improvements"
  - No Fast Track documentation at all
  - No index/navigation

```

Changes organized by priority.

## P1: High Priority

---
Detect task completion at beginning of zen run from previous zen run
---
---
create number of workers based on task, why flag?
---

  Problems:
  1. False conflict detection - backup/, log.md, plan.md, scout.md are internal zen files, not real conflicts
  2. Exit code 1 - tasks failed but we don't know why
  3. Ticker display bug - showed "2/3 done" then "1/3 done" (went backwards)

--

---
## REFINEMENT

  Current Implementation

  | Aspect               | Current              | Requirement     |
  |----------------------|----------------------|-----------------|
  | Max attempts         | MAX_RETRIES + 2 = 4  | 5               |
  | Per-attempt timeout  | 600s (10 min)        | 120s            |
  | Stuck detection      | Same error 2x → exit | Same error 3x   |
  | "No tests" detection | ❌ None              | Skip gracefully |
  | --skip-verify flag   | ❌ None              | For infra tasks |

  Gaps & Solutions

  1. "No tests found" detection
  The agent can loop forever if tests don't exist. Need to detect patterns like:
  "no tests ran"
  "collected 0 items"
  "no test files found"

  Options:
  - A) Prompt-level: Tell agent to output NO_TESTS_FOUND marker → we skip verify
  - B) Output parsing: Check test_output for "0 collected" / "no tests ran" patterns
  - C) Both: Parse + fallback marker

  3. --skip-verify flag - Simple CLI flag. Just skip phase_verify() if set.

---


**Gap #1 ("No tests found")** is the highest risk because it causes infinite loops and token waste.

### 1. The "No Tests Found" Strategy
**Recommendation: Option C (Hybrid Approach)**

Reling solely on the LLM (Option A) is expensive and non-deterministic. Relying solely on regex (Option B) is brittle across languages. You need a tiered approach.

*   **Layer 1: Hard-coded Heuristics (Fast & Cheap)**
    Before sending the output to the LLM, run a lightweight check on `stdout/stderr`.
    *   *Pytest:* Exit code 5 usually means "no tests collected."
    *   *Jest/Mocha:* Regex for `0 matching` or `Test Suites: 0 failed, 0 passed, 0 total`.
    *   **Action:** If these are detected, immediate early exit from the loop with a status of `SKIPPED_VERIFICATION`.

*   **Layer 2: Prompt Instruction (The Safety Net)**
    If the regex misses it (e.g., a weird custom test runner), update the system prompt for the verification phase.
    *   *Prompt:* "Analyze the output. If the test runner executed successfully but found no tests to run (e.g., '0 collected'), output `NO_TESTS_FOUND` and stop. Do not try to write new tests."

**Why this direction?** It solves the "loop" problem deterministically for 90% of cases (Layer 1) while handling edge cases with intelligence (Layer 2).

---


### 3. The `--skip-verify` Flag
**Recommendation: explicit state handling.**

Don't just skip the function call. You must inject this context into the Agent's prompt or state.

*   If you just skip `phase_verify()`, the Agent might finish `phase_implement()` and think, "Wait, I should run tests to be sure," and try to run them manually in the implementation phase.
*   **Fix:** If `--skip-verify` is on, add a system prompt line: "User has explicitly requested to skip testing. Do not run test commands. Mark the task as complete once code changes are applied."

---


### Pre-flight
Machine-parseable `[YES/NO]` is good. Simpler format for regex:
```
PREFLIGHT: FILES=YES, TASK=YES
```
<PREFLIGHT>
Verification required before coding:
1. Do you have the source code for the files you need to edit? [YES/NO]
2. Is the task clearly defined? [YES/NO]

If NO to either, stop and output: STEP_BLOCKED: <reason>
</PREFLIGHT>


### Problem 4: Agree with B
Zen already has `MAX_RETRIES` - just need pause logic.
### Failure-triggered pause
```python
# After 2 consecutive retries on different steps, pause
if consecutive_retries >= 2:
    log("[CHECKPOINT] Multiple retries detected. Something may be wrong with plan.")
```

What to do when preflight fails.
- Abort + log reason. User can `--retry` after fixing plan.

---

## P2: Medium Priority (Cost & Quality)

### 2.2 Linter: Per-Line Disable Comments

**Problem:** No way to suppress false positives inline.

**Location:** `src/zen_mode/linter.py` - main check loop

**Syntax:**
```python
secret = "not-a-secret"  # zenlint: ignore POSSIBLE_SECRET
```

**Implementation:**
```python
IGNORE_PATTERN = re.compile(r'#\s*zenlint:\s*ignore\s+(\w+)')

def get_ignored_rules(line: str) -> set[str]:
    """Extract rule names to ignore from line comment."""
    match = IGNORE_PATTERN.search(line)
    return {match.group(1)} if match else set()

# In check loop:
ignored = get_ignored_rules(line)
if rule_name in ignored:
    continue
```

**Effort:** ~20 LOC | **Risk:** Low

---

### 2.3 Linter: Language-Specific Rule Scoping

**Problem:** Rules like `INLINE_IMPORT` trigger on non-applicable languages.

**Location:** `src/zen_mode/linter.py` - rule definitions

**Implementation:**
```python
RULE_EXTENSIONS = {
    "INLINE_IMPORT": {"py", "js", "ts", "tsx", "jsx"},
    "POSSIBLE_SECRET": {"*"},  # All files
    "HARDCODED_IP": {"*"},
    "TODO_FIXME": {"*"},
    # ... map each rule
}

def rule_applies_to_file(rule_name: str, filepath: Path) -> bool:
    extensions = RULE_EXTENSIONS.get(rule_name, {"*"})
    if "*" in extensions:
        return True
    return filepath.suffix.lstrip(".").lower() in extensions
```

**Effort:** ~40 LOC | **Risk:** Low

---

## P3: Low Priority (Nice to Have)

### 3.1 File Size Annotations in Scout

**Problem:** Model may waste tokens reading massive files.

**Implementation:** Add `[LARGE]` / `[MASSIVE]` tags to file tree in scout prompt.

**Effort:** ~25 LOC | **Defer until:** P1-P2 complete

---

### 3.2 Dry Run Mode Enhancement

**Problem:** `--dry-run` output is minimal.

**Improvements:**
- Print prompts that would be sent
- Show which files would be created
- Add `--verbose` flag

**Effort:** ~30 LOC | **Defer until:** User requests

---

### 3.3 Documentation & --help

**Problem:** No built-in help or examples.

**Improvements:**
- Add `--help` with usage examples
- Sample task file in repo
- Link to CLAUDE.md

**Effort:** ~20 LOC | **Defer until:** Public release

---

### 3.4 Break Up God Class

**Problem:** `core.py` is 1000+ LOC single file.

**Target Structure:**
```
├── state.py       # WorkDir, TaskState
├── planner.py     # Scout, Plan phases
├── runner.py      # Implement phase
├── judge.py       # Judge phase
└── files.py       # File helpers
```

**Effort:** ~200+ LOC refactor | **Defer until:** Pain point or major feature

---


  For cost savings, the only levers are:
  1. Fewer tokens: Shorter prompts, truncate context
  2. Cache hits: Prompt prefix caching (when it works)

Track context and start new sessions when we reach threshold(s) instead of new context for each step.
 The tradeoff:

  Stateless (current)          vs    Stateful with threshold reset
  ─────────────────────────────────────────────────────────────────
  + Predictable, resumable          + Could batch work across steps
  + Easy to debug/retry             + Model builds on its own context
  + Consistent results              + Fewer "re-read the plan" overhead
  ─────────────────────────────────────────────────────────────────
  - Each step re-discovers state    - Results become path-dependent
  - Can't learn from step N-1       - Harder to resume mid-run
  - Repeated context overhead       - Context drift risk

---

# Zen Implementation Roadmap

Based on compiled findings and consensus.

## Scope

**In scope:** Refactor core.py, then PLAN and IMPLEMENT prompt enhancements
**Out of scope:** VERIFY/JUDGE prompt updates (later phase)

---

## Phase 0: Refactor core.py

**Rationale:** core.py is ~1200 lines mixing orchestration with phase logic. Extract each phase before modifying it. Smaller files are easier to test and maintain.

### Current State

```
core.py (~1200 lines)
├── phase_scout()
├── phase_plan()
├── phase_implement()
├── phase_judge()
├── helpers (run_claude, log, read_file, write_file, backup_file)
└── orchestration (run)

Already extracted:
├── verify.py      ✓ (phase_verify, phase_fix_tests, verify_and_fix)
├── triage.py      ✓ (parse_triage, should_fast_track)
├── linter.py      ✓
├── swarm.py       ✓
├── config.py      ✓
├── utils.py       ✓
```

### Target State

```
src/zen_mode/
├── core.py          # orchestration only (~300 lines)
├── scout.py         # phase_scout, build_scout_prompt
├── plan.py          # phase_plan, parse_steps, validate_plan_efficiency
├── implement.py     # phase_implement, run_linter integration
├── judge.py         # phase_judge
├── verify.py        ✓ already done
├── triage.py        ✓ already done
├── linter.py        ✓ already done
├── utils.py         # shared: run_claude, log, read_file, write_file, cost tracking
├── config.py        ✓ already done
└── defaults/
    └── CLAUDE.md    # zen constitution
```

### Extraction Order

Each extraction follows: **Extract → Test → Commit**
Consistency in Signatures
Signatures like phase_scout(task_file: str) -> None, but Step 0.1 introduces the Context object.
Action: Ensure all phase signatures are updated to phase_scout(ctx: Context) -> None. The task_file should be read from ctx.task_file

| Step | Extract | From | To | Functions |
|------|---------|------|-----|-----------|
| 0.1 | Shared helpers | core.py | utils.py | `run_claude`, `log`, `read_file`, `write_file`, `backup_file`, cost tracking |
| 0.2 | Scout | core.py | scout.py | `phase_scout`, `build_scout_prompt` |
| 0.3 | Plan | core.py | plan.py | `phase_plan`, `parse_steps`, `validate_plan_efficiency`, `get_completed_steps` |
| 0.4 | Implement | core.py | implement.py | `phase_implement`, `run_linter`, `backup_scout_files` |
| 0.5 | Judge | core.py | judge.py | `phase_judge`, `should_skip_judge` |
| 0.6 | Grep impact | NEW | scout.py | `grep_impact()`, `expand_dependencies()` |
| 0.7 | Interface-first | NEW | plan.py | Output format enforcement |

### Step 0.1: Extract shared helpers to utils.py + Context

**Move to utils.py:**
- `run_claude()` - core Claude CLI wrapper
- `log()` - logging to log.md
- `read_file()` / `write_file()` - file I/O
- `backup_file()` - backup before modification

**Add Context dataclass (replaces global state):**

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any

@dataclass
class Context:
    """Execution context passed to all phases. Enables testing."""
    work_dir: Path
    task_file: str
    flags: set = field(default_factory=set)
    costs: List[Dict[str, Any]] = field(default_factory=list)
    tokens: int = 0

    def record_cost(self, phase: str, cost: float, tokens: int) -> None:
        self.costs.append({"phase": phase, "cost": cost, "tokens": tokens})
        self.tokens += tokens
```

**Usage in core.py:**

```python
ctx = Context(work_dir=WORK_DIR, task_file=task_file, flags=flags)
phase_scout(ctx)
phase_plan(ctx)
phase_implement(ctx)
```

**Benefits:**
- No global state to mock in tests
- Each phase receives explicit dependencies
- Easy to inject test fixtures

### Step 0.2: Extract scout.py

**Move:**
```python
# scout.py
from zen_mode.utils import run_claude, log, read_file, write_file
from zen_mode.config import MODEL_EYES, WORK_DIR

def build_scout_prompt(task_file: str, output_file: str) -> str: ...
def phase_scout(task_file: str) -> None: ...
```

**Test:** `pytest tests/test_*.py -v`

### Step 0.3: Extract plan.py

**Move:**
```python
# plan.py
from zen_mode.utils import run_claude, log, read_file, write_file, extract_sections
from zen_mode.config import MODEL_BRAIN, WORK_DIR

def parse_steps(plan: str) -> List[Tuple[int, str]]: ...
def validate_plan_efficiency(steps) -> Tuple[bool, str]: ...
def get_completed_steps() -> set: ...
def phase_plan(task_file: str) -> None: ...
```

**Test:** `pytest tests/test_*.py -v`

### Step 0.4: Extract implement.py

**Move:**
```python
# implement.py
from zen_mode.utils import run_claude, log, read_file, write_file, extract_sections
from zen_mode.config import MODEL_HANDS, MODEL_BRAIN, TIMEOUT_EXEC, MAX_RETRIES
from zen_mode import linter

def run_linter() -> Tuple[bool, str]: ...
def backup_scout_files() -> None: ...
def phase_implement() -> None: ...
```

**Test:** `pytest tests/test_*.py -v`

### Step 0.5: Extract judge.py

**Move:**
```python
# judge.py
from zen_mode.utils import run_claude, log, read_file, write_file
from zen_mode.config import MODEL_BRAIN, MAX_JUDGE_LOOPS

def should_skip_judge() -> bool: ...
def phase_judge() -> None: ...
```

**Test:** `pytest tests/test_*.py -v`

### Step 0.6: Grep Impact (Golden Rule enforcement)

**File:** `src/zen_mode/scout.py`

**Rationale:** "Grep Before Change" is a GOLDEN RULE. System must run grep, not just advise agent to do it.

**Strategy:** Grep for **filename stem** (e.g., `user_model` for `user_model.py`). This catches:
- `from user_model import`
- `import user_model`
- `from .user_model import` (relative)
- `from package.user_model import`

False positives (comments mentioning the name) are acceptable - they add context. False negatives (missing a real dependency) are dangerous.

Risk: If you have a file named utils.py, grepping for the stem utils will match every file that imports django.utils, docutils, etc.
Mitigation:
When calculating the stem, if the stem is a very common word (e.g., utils, config, json, core), you might get noise.
Optimization for Implementation: Consider restricting the grep to import {stem} or from {stem} or from .{stem} regexes if the stem is generic. For V1, the noise is acceptable (better to over-check than under-check), but keep an eye on utils.py specifically.

**Add after scout completes:**

```python
def grep_impact(targeted_files: List[str]) -> Dict[str, List[str]]:
    """Find all files that reference the targeted files."""
    impact = {}

    for target in targeted_files:
        # Use filename stem for broad matching
        stem = Path(target).stem  # "user_model.py" -> "user_model"

        # Grep for any reference to the stem
        result = subprocess.run(
            ["grep", "-rl", "--include=*.py", stem, "."],
            capture_output=True, text=True
        )
        matches = [f for f in result.stdout.strip().split("\n") if f and f != target]
        impact[target] = list(set(matches))

    return impact

def expand_dependencies(targeted_files: List[str]) -> List[str]:
    """Return files that reference any of the targeted files."""
    impact = grep_impact(targeted_files)
    all_deps = set()
    for deps in impact.values():
        all_deps.update(deps)
    return list(all_deps - set(targeted_files))
```

**Append to scout.md:**

```python
deps = expand_dependencies(targeted_files)
if deps:
    with SCOUT_FILE.open("a") as f:
        f.write("\n## Grep Impact (callers/importers)\n")
        for dep in deps:
            f.write(f"- `{dep}`: references targeted file\n")
```

---

### Step 0.7: Interface-First Enforcement

**File:** `src/zen_mode/plan.py`

**Rationale:** ARCHITECTURE says "Interface First. Define types/shapes before implementation." Enforce in output format.

**Add to plan prompt:**

```
<output_format>
Format (strict markdown):

## Interfaces (REQUIRED)
Define signatures that will change:
- `function_name(args) -> ReturnType`: purpose
- `ClassName.method(args) -> ReturnType`: purpose

## Steps
## Step 1: <action verb> <specific target>
...
</output_format>
```

**Add robust validator (handles `# Step`, `## Steps`, etc.):**

```python
def validate_plan_has_interfaces(plan: str) -> Tuple[bool, str]:
    """Reject plans without ## Interfaces section before steps."""
    # Normalize headers (# -> ##)
    normalized = re.sub(r'^#\s+', '## ', plan, flags=re.MULTILINE)

    # Extract all section headers
    sections = [line.strip().lower() for line in normalized.splitlines()
                if line.strip().startswith("## ")]

    # Check for interfaces section
    if not any("interface" in s for s in sections):
        return False, "Plan must include '## Interfaces' section"

    # Find positions
    interface_idx = next((i for i, s in enumerate(sections) if "interface" in s), 999)
    step_idx = next((i for i, s in enumerate(sections) if "step" in s), 999)

    if step_idx < interface_idx:
        return False, "## Interfaces must come BEFORE ## Steps"

    return True, ""
```

---

### Post-Refactor core.py

```python
# core.py - orchestration only
from zen_mode.scout import phase_scout
from zen_mode.plan import phase_plan
from zen_mode.implement import phase_implement
from zen_mode.judge import phase_judge
from zen_mode.verify import verify_and_fix
from zen_mode.triage import parse_triage, should_fast_track

def run(task_file: str, flags: Optional[set] = None, ...) -> None:
    """Main orchestration - delegates to phase modules."""
    # ... flag handling, setup ...

    phase_scout(task_file)

    # triage check
    if should_fast_track(triage):
        phase_implement()
        verify_and_fix()
    else:
        phase_plan(task_file)
        phase_implement()
        verify_and_fix()
        phase_judge()

    # ... summary, cleanup ...
```

---

## Phase 1: Prompt Enhancements

After refactor, apply prompt changes to extracted modules.

## Summary

### Phase 0: Refactor + Foundation

| Step | Action | Location |
|------|--------|----------|
| 0.1 | Extract shared helpers | utils.py |
| 0.2 | Extract scout | scout.py |
| 0.3 | Extract plan | plan.py |
| 0.4 | Extract implement | implement.py |
| 0.5 | Extract judge | judge.py |
| 0.6 | **Grep impact** (Golden Rule) | scout.py |
| 0.7 | **Interface-first** enforcement | plan.py |

### Phase 1: Prompt Enhancements

| Step | Change | Location |
|------|--------|----------|
| 1.1 | Inject ARCHITECTURE+PROCESS | plan.py |
| 1.2 | Richer GOOD/BAD examples | plan.py |
| 1.3 | Inject GOLDEN RULES+CODE STYLE+TESTING | implement.py |
| 1.4 | Few-shot scope examples | implement.py |
| 1.5 | Escalation-specific example | implement.py |

**Source of truth:** `src/zen_mode/defaults/CLAUDE.md`

### Phase 2: Lint Ratchet

| Step | Change | Location |
|------|--------|----------|
| 2.1 | Lint baseline (capture pre-existing) | scout.py |
| 2.2 | `parse_targeted_files()` helper | utils.py |
| 2.3 | Lint diff / ratchet enforcement | implement.py |

---

## Phase 1 Steps

### Step 1.1: Inject zen constitution into PLAN

**File:** `src/zen_mode/plan.py`

**Rationale:** Planner makes architectural decisions but doesn't see the rules. Inject ARCHITECTURE and PROCESS sections.

**Add helper to utils.py:**

```python
def extract_sections(content: str, headers: List[str]) -> str:
    """Extract specific ## sections from markdown content."""
    lines = content.splitlines()
    result = []
    capturing = False

    for line in lines:
        if line.startswith("## "):
            section_name = line[3:].strip()
            capturing = any(h.lower() in section_name.lower() for h in headers)
        if capturing:
            result.append(line)

    return "\n".join(result)
```

**In plan.py, after imports:**

```python
from pathlib import Path
DEFAULTS_DIR = Path(__file__).parent / "defaults"
ZEN_CONSTITUTION = (DEFAULTS_DIR / "CLAUDE.md").read_text()
```

**In phase_plan prompt, after `<role>` block:**

```python
plan_rules = extract_sections(ZEN_CONSTITUTION, ["ARCHITECTURE", "PROCESS"])

# Add to prompt:
<constitution>
{plan_rules}
</constitution>
```

---

### Step 1.2: Replace PLAN GOOD/BAD examples

**File:** `src/zen_mode/plan.py`

**Rationale:** Current examples only teach step consolidation. Need to teach:
- Interface-first structure (required by Step 0.7)
- What info each step should contain
- How to write for fresh-session implementer
- Atomic vs. vague steps

**Replace existing `<EXAMPLES>` with:**

```
<EXAMPLES>
BAD PLAN (missing interfaces, vague steps):
## Step 1: Update the user model
## Step 2: Add validation
## Step 3: Write tests
## Step 4: Update callers

GOOD PLAN (interfaces first, symbol references):

## Interfaces
- `User.validate_email() -> None`: Raises `InvalidEmailError` if email format invalid
- `InvalidEmailError(Exception)`: Custom error for email validation failures

## Steps

## Step 1: Add email validation to User model
Files: `src/models/user.py`
Target: `User` class, add method after `save()`
Action: Add `validate_email()` method that raises `InvalidEmailError`

## Step 2: Update registration endpoint to use validation
Files: `src/api/auth.py` (modify `register_user()`), `src/models/user.py` (read)
Target: `register_user()` function
Action: Call `user.validate_email()` before `user.save()`

## Step 3: Add tests for email validation
Files: `tests/test_user.py` (create)
Action: Test valid email, invalid email, edge case (empty string)

## Step 4: Verify all tests pass
Action: Run `pytest tests/test_user.py -v`
</EXAMPLES>
```

**Key structure enforced:**
1. `## Interfaces` section MUST come first
2. Each interface lists signature and purpose
3. `## Steps` follow with file paths, symbol targets, and actions
4. Use symbol references (`User` class, `save()` method) not line numbers (stable across edits)

---

### Step 1.3: Inject zen constitution into IMPLEMENT

**File:** `src/zen_mode/implement.py`

**Rationale:** Implementer needs hands-on coding rules. Extract dynamically to stay in sync with defaults/CLAUDE.md.

**In implement.py, after imports:**

```python
from pathlib import Path
DEFAULTS_DIR = Path(__file__).parent / "defaults"
ZEN_CONSTITUTION = (DEFAULTS_DIR / "CLAUDE.md").read_text()
```

**In phase_implement prompt:**

```python
impl_rules = extract_sections(ZEN_CONSTITUTION, ["GOLDEN RULES", "CODE STYLE", "TESTING"])

# Add to prompt:
if impl_rules:
    base_prompt += f"\n<constitution>\n{impl_rules}\n</constitution>"
```

**Benefits:**
- No hardcoded rules to maintain
- Automatically picks up defaults/CLAUDE.md changes
- Single source of truth

---

### Step 1.4: Add few-shot scope examples to IMPLEMENT

**File:** `src/zen_mode/implement.py`

**Rationale:** No examples currently. Opus needs few-shot. Teaches scope discipline.

**Add:**

```
<EXAMPLES>
Task: "Add retry logic to API client"

BAD (scope creep):
- Added retry logic ✓
- Also added timeout configuration
- Also added exponential backoff
- Also added circuit breaker pattern
- Also refactored error handling
Result: LINT_FAIL (3 errors), broke 2 existing tests

GOOD (minimal, complete):
- Added retry with 3 attempts and 1s delay
- Updated the one caller that needed it
Result: STEP_COMPLETE
</EXAMPLES>
```

---

### Step 1.5: Add escalation-specific example

**File:** `src/zen_mode/implement.py`

**Rationale:** "Fix it definitively" → Opus over-engineers. Need example showing "definitive = works, not comprehensive"

**Change escalation text to:**

```
ESCALATION: Previous {attempt - 1} attempts failed.
Last error: {last_error_summary}

You are the senior specialist. Fix the SPECIFIC error above.
- Do NOT refactor or add features
- Do NOT apologize or explain
- Output ONLY the fix implementation, no conversational filler

<EXAMPLE>
Previous error: "NameError: 'retry_count' not defined"

BAD (over-engineered):
- Added retry_count
- Also added RetryConfig class
- Also added logging
- Also added backoff strategy
Result: 4 new errors

GOOD (targeted):
- Added `retry_count = 0` at line 42
Result: STEP_COMPLETE
</EXAMPLE>

End with: STEP_COMPLETE or STEP_BLOCKED: <reason>
```

---

## Phase 2: Lint Ratchet

Lint baseline and ratchet enforcement. Run after Scout, enforce during Implement.

### Step 2.1: Lint Baseline (capture pre-existing violations)

**File:** `src/zen_mode/scout.py`

**Problem:** Linter fails on ALL violations including pre-existing ones. Agent wastes cycles fixing unrelated issues.

**Goal:** Only fail on NEW violations. Ratchet model.

```python
# In scout.py, after scout completes:
def capture_lint_baseline(targeted_files: List[str]) -> None:
    """Run linter on targeted files and store baseline."""
    if not targeted_files:
        return

    _, baseline_output = linter.run_lint(paths=targeted_files, min_severity="MEDIUM")

    with SCOUT_FILE.open("a") as f:
        f.write("\n## Lint Baseline\n")
        f.write(baseline_output or "Clean\n")
```

---

### Step 2.2: Parse targeted files helper

**File:** `src/zen_mode/utils.py`

```python
def parse_targeted_files(scout_content: str) -> List[str]:
    """Extract file paths from ## Targeted Files section."""
    files = []
    in_section = False

    for line in scout_content.splitlines():
        if line.startswith("## Targeted Files"):
            in_section = True
            continue
        if line.startswith("## ") and in_section:
            break
        if in_section and line.strip().startswith("- `"):
            match = re.match(r"- `([^`]+)`", line.strip())
            if match:
                files.append(match.group(1))

    return files
```

---

### Step 2.3: Lint Diff in Implement (Categorized Delta)

**File:** `src/zen_mode/implement.py`

**Problem with line-based matching:** If agent inserts 5 lines at top of file, all pre-existing lint errors shift down by 5 lines. Line-based diff will flag old errors as "new".
Observation: The Ratchet relies heavily on parse_violations(lint_out).

Action: Ensure your existing linter.py regex is robust. If the linter outputs multiline errors or slightly different formats for syntax errors vs style errors, the parser must handle them. If parsing fails, the Ratchet will see "0 errors" and might falsely pass a catastrophic failure.
Safety Check: Add a unit test for parse_violations with a sample of a SyntaxError (which sometimes looks different in linter output than a PEP8 violation).

**Solution: Categorized Delta** - Count violations by `(file, error_code)`, ignore line numbers.

```python
def count_violations(violations: List[Violation]) -> Dict[Tuple[str, str], int]:
    """Aggregate violation counts by (filename, error_code)."""
    counts = {}
    for v in violations:
        key = (v.filename, v.code)  # e.g. ('core.py', 'F821')
        counts[key] = counts.get(key, 0) + 1
    return counts

def check_lint_ratchet() -> Tuple[bool, str]:
    """Fail only if violation count INCREASES for any (file, code) pair."""
    passed, lint_out = run_linter()

    if passed:
        return True, ""

    baseline = parse_lint_baseline(SCOUT_FILE)
    baseline_counts = count_violations(baseline)
    current_counts = count_violations(parse_violations(lint_out))

    # Check for regressions
    new_issues = []
    for key, curr_count in current_counts.items():
        base_count = baseline_counts.get(key, 0)

        if curr_count > base_count:
            filename, code = key
            diff = curr_count - base_count
            new_issues.append(f"{filename}: +{diff} new '{code}' errors")

    if new_issues:
        return False, "\n".join(new_issues)

    log("[LINT] No new violations (categorized delta passed)")
    return True, ""
```

### Why Categorized Delta Works

| Problem | How it's solved |
|---------|-----------------|
| Line shifts | Counts ignore line numbers |
| Bug trading | Each `(file, code)` tracked separately |
| Refactoring | Reducing count from 5→1 is a PASS |
| New files | `base_count=0`, so any violation fails |

### Ratchet Behavior

| Scenario | Result |
|----------|--------|
| New violations introduced | FAIL |
| Pre-existing violations only | PASS |
| Agent fixes pre-existing issues | PASS (bonus cleanup) |
| Violations decrease | PASS (ratchet tightens) |
| New file with violations | FAIL (zero tolerance) |

---

## Verification

After each phase:
1. Run existing zen tests: `pytest tests/ -v`
2. Manual test on a simple task
3. Manual test on a task that previously caused scope creep

---

## Out of Scope (Future)

- VERIFY/JUDGE prompt updates
- Rationalization tables (deferred until we see specific failure patterns)
- Evidence-before-assertion (VERIFY phase handles this)

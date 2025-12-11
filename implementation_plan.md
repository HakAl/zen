# Zen.py Refinements - Implementation Plan

Changes to `scripts/zen.py` organized by priority.

---

## P0: Critical (Do First)

### 1. Fix "Suicide Pact" Bug - `phase_verify` returns bool ✅ COMPLETED

**Problem:** `phase_verify()` calls `sys.exit(1)` on failure. When called from `phase_judge()` fix loop (line 793), a test failure kills the entire agent instead of letting the judge retry.

**Change:** Refactor `phase_verify()` to return `bool`.

```python
# BEFORE (line 537)
def phase_verify() -> None:
    ...
    log(f"[VERIFY] Failed after {MAX_RETRIES} attempts.")
    sys.exit(1)

# AFTER
def phase_verify() -> bool:
    """Returns True if verification passed, False otherwise."""
    ...
    # Replace all sys.exit(1) with return False
    # Replace success path with return True

    log(f"[VERIFY] Failed after {MAX_RETRIES} attempts.")
    return False
```

**Callers to update:**

```python
# main() line 863:
# BEFORE:
phase_verify()

# AFTER:
if not phase_verify():
    sys.exit(1)

# phase_judge() line 793:
# BEFORE:
phase_verify()

# AFTER:
if not phase_verify():
    log("[JUDGE_FIX] Tests failed after fixes.")
    sys.exit(1)
```

---

### 2. Judge Short-Circuit - `should_skip_judge()` ✅ COMPLETED

**Location:** Add helper at module level (~line 130), add main function after `get_changed_filenames()` (~line 264), call from `main()`.

```python
# Module-level helper (near other utility functions, ~line 130)
def _is_test_or_doc(path: str) -> bool:
    """Check if path is a test or documentation file."""
    return (path.endswith(('.md', '.txt', '.rst')) or
            '/test' in path or path.startswith('test') or
            '_test.' in path or 'test_' in path)


# Main function (~line 264)
def should_skip_judge() -> bool:
    """Skip expensive Opus review for trivial/safe changes."""
    # Get modified files (tracked)
    try:
        result = subprocess.run(
            ["git", "diff", "--numstat", "HEAD"],
            capture_output=True, text=True, cwd=PROJECT_ROOT
        )
        if result.returncode != 0:
            return False
        numstat = result.stdout.strip()
    except Exception:
        return False

    # Get untracked files (new files not yet in git)
    try:
        untracked_result = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, cwd=PROJECT_ROOT
        )
        untracked = untracked_result.stdout.strip() if untracked_result.returncode == 0 else ""
    except Exception:
        untracked = ""

    # Handle edge cases for new files
    if not numstat and not untracked:
        log("[JUDGE] Skipping: No changes detected")
        return True

    if not numstat and untracked:
        # Only new files, no modifications to existing
        untracked_files = untracked.splitlines()
        if not all(_is_test_or_doc(f) for f in untracked_files):
            log("[JUDGE] Required: New code files created")
            return False
        log("[JUDGE] Skipping: Only new test/doc files")
        return True

    # Parse numstat for modified files
    total_add, total_del = 0, 0
    changed_files = []

    for line in numstat.splitlines():
        parts = line.split('\t')
        if len(parts) >= 3:
            add = int(parts[0]) if parts[0] != '-' else 0
            delete = int(parts[1]) if parts[1] != '-' else 0
            total_add += add
            total_del += delete
            changed_files.append(parts[2])

    # Include untracked files in the file list for risk assessment
    if untracked:
        changed_files.extend(untracked.splitlines())

    total_changes = total_add + total_del

    # Rule A: Typo fix threshold (but not if new code files exist)
    has_new_code_files = untracked and not all(_is_test_or_doc(f) for f in untracked.splitlines())
    if total_changes < 5 and not has_new_code_files:
        log(f"[JUDGE] Skipping: Trivial ({total_changes} lines)")
        return True

    # Rule B: Risky files always reviewed
    risky_patterns = ['auth', 'login', 'secur', 'payment', 'crypt', 'secret', 'token']
    for f in changed_files:
        if any(r in f.lower() for r in risky_patterns):
            log(f"[JUDGE] Required: Sensitive file ({f})")
            return False

    # Rule C: Pure docs/tests exempt
    if all(_is_test_or_doc(f) for f in changed_files):
        log("[JUDGE] Skipping: Only docs/tests changed")
        return True

    # Rule D: Small refactor + simple plan
    plan = read_file(PLAN_FILE)
    steps = parse_steps(plan)
    if len(steps) <= 2 and total_changes < 30 and not has_new_code_files:
        log(f"[JUDGE] Skipping: Simple ({len(steps)} steps, {total_changes} lines)")
        return True

    if total_changes < 20 and not has_new_code_files:
        log(f"[JUDGE] Skipping: Small refactor ({total_changes} lines)")
        return True

    return False
```

**Update `main()`:**
```python
# BEFORE (line 865-868)
if not skip_judge:
    phase_judge()

# AFTER
if not skip_judge and not should_skip_judge():
    phase_judge()
```

---

## P1: High Priority

### 3. Model Escalation (Sonnet → Opus on 2x fail)

**Location:** `phase_implement()` inner retry loop (~line 488).

**Key insight:** When escalating to Opus, reset to a clean prompt. Don't feed Opus the accumulated garbage from failed attempts—just summarize why previous attempts failed.

```python
# BEFORE
for attempt in range(1, MAX_RETRIES + 1):
    ...
    output = run_claude(prompt, model=MODEL_HANDS, timeout=TIMEOUT_EXEC) or ""

# AFTER
base_prompt = f"""Execute Step {step_num}: {step_desc}

IMPORTANT: This is a fresh session with no memory of previous steps.
READ target files first to understand current state before editing.

Full plan:
{plan}

Rules:
- DELETE old code, no shims
- UPDATE callers immediately
- No broken imports

End with: STEP_COMPLETE or STEP_BLOCKED: <reason>"""

prompt = base_prompt
last_error_summary = ""

for attempt in range(1, MAX_RETRIES + 1):
    # Escalate to Opus on final retry with CLEAN prompt
    if attempt == MAX_RETRIES:
        log(f"  Escalating to {MODEL_BRAIN}...")
        prompt = base_prompt + f"""

ESCALATION: Previous {attempt - 1} attempts by a junior model failed.
Last error: {last_error_summary}
You are the senior specialist. Analyze the problem fresh and fix it definitively."""
        model = MODEL_BRAIN
    else:
        model = MODEL_HANDS

    output = run_claude(prompt, model=model, timeout=TIMEOUT_EXEC) or ""

    # ... rest of loop ...

    # On lint failure, capture summary for potential escalation
    if not passed:
        last_error_summary = truncated[:300]  # Keep concise for Opus
        # ... existing lint failure handling ...
```

---

### 4. "I'm Stuck" Detection + Coaching Prompt

**Location:** `phase_implement()` after getting output (~line 493).

**Key fix:** Don't use `continue` after detecting stuck—immediately re-call the model with the coaching prompt in the same attempt.

```python
# AFTER getting output, BEFORE checking STEP_BLOCKED
STUCK_PHRASES = ["I cannot", "I am unable", "I'm unable", "not possible", "cannot complete"]

if any(phrase in output for phrase in STUCK_PHRASES) and "STEP_COMPLETE" not in output:
    log(f"  [STUCK] Detected hesitation, injecting coaching prompt...")
    coaching_prompt = prompt + """

COACHING: You are in Zen Mode with full file access. You CAN do this.
- Re-read the scout report for correct file paths
- Break the problem into smaller pieces
- If a file doesn't exist, create it
- Try again."""

    # Immediately retry with coaching (same attempt, no continue)
    output = run_claude(coaching_prompt, model=model, timeout=TIMEOUT_EXEC) or ""

    # If still stuck after coaching, let normal flow handle it
    if any(phrase in output for phrase in STUCK_PHRASES) and "STEP_COMPLETE" not in output:
        log(f"  [STUCK] Still stuck after coaching, proceeding to next attempt")
```

---

### 5. Implement Snapshots (create_snapshot / restore_snapshot)

**Location:** Add after `backup_file()` (~line 128).

**Key safeguards:**
- Check if git repo exists (non-git repos should not crash)
- Handle stash conflicts gracefully with fallback
- Drop successful snapshots to prevent stack growth

```python
def create_snapshot(label: str) -> str:
    """Create a git stash snapshot before risky operation. Returns stash ref."""
    # Safety: skip if not a git repo
    if not (PROJECT_ROOT / ".git").exists():
        return ""

    try:
        # Check if there are changes to stash
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=PROJECT_ROOT
        )
        if not status.stdout.strip():
            return ""  # Nothing to snapshot

        stash_msg = f"zen-snapshot-{label}-{int(time.time())}"
        result = subprocess.run(
            ["git", "stash", "push", "-m", stash_msg, "--include-untracked"],
            capture_output=True, text=True, cwd=PROJECT_ROOT
        )
        if result.returncode == 0:
            log(f"[SNAPSHOT] Created: {label}")
            return stash_msg
    except Exception as e:
        log(f"[SNAPSHOT] Failed: {e}")
    return ""


def restore_snapshot(stash_msg: str) -> bool:
    """Restore a snapshot by stash message. Returns True on success."""
    if not stash_msg:
        return False

    # Safety: skip if not a git repo
    if not (PROJECT_ROOT / ".git").exists():
        return False

    try:
        # Find the stash index by message
        result = subprocess.run(
            ["git", "stash", "list"],
            capture_output=True, text=True, cwd=PROJECT_ROOT
        )
        for line in result.stdout.splitlines():
            if stash_msg in line:
                # Extract stash ref (e.g., "stash@{0}")
                stash_ref = line.split(":")[0]

                # Try stash pop first
                pop_result = subprocess.run(
                    ["git", "stash", "pop", stash_ref],
                    capture_output=True, text=True, cwd=PROJECT_ROOT
                )
                if pop_result.returncode == 0:
                    log(f"[SNAPSHOT] Restored: {stash_msg}")
                    return True

                # Fallback: stash pop failed (likely conflict)
                # Hard reset to clean state, then apply
                log(f"[SNAPSHOT] Conflict detected, forcing restore...")
                subprocess.run(
                    ["git", "checkout", "."],
                    capture_output=True, text=True, cwd=PROJECT_ROOT
                )
                subprocess.run(
                    ["git", "clean", "-fd"],
                    capture_output=True, text=True, cwd=PROJECT_ROOT
                )
                apply_result = subprocess.run(
                    ["git", "stash", "pop", stash_ref],
                    capture_output=True, text=True, cwd=PROJECT_ROOT
                )
                if apply_result.returncode == 0:
                    log(f"[SNAPSHOT] Restored (forced): {stash_msg}")
                    return True
                else:
                    log(f"[SNAPSHOT] Restore failed: {apply_result.stderr[:200]}")
                    return False

    except Exception as e:
        log(f"[SNAPSHOT] Restore failed: {e}")
    return False


def drop_snapshot(stash_msg: str) -> None:
    """Drop a snapshot after successful step (prevents stash stack growth)."""
    if not stash_msg or not (PROJECT_ROOT / ".git").exists():
        return

    try:
        result = subprocess.run(
            ["git", "stash", "list"],
            capture_output=True, text=True, cwd=PROJECT_ROOT
        )
        for line in result.stdout.splitlines():
            if stash_msg in line:
                stash_ref = line.split(":")[0]
                subprocess.run(
                    ["git", "stash", "drop", stash_ref],
                    capture_output=True, text=True, cwd=PROJECT_ROOT
                )
                return
    except Exception:
        pass  # Non-critical, ignore failures
```

**Update `phase_implement()`:** Add snapshot before each step, drop on success, restore on failure.

```python
for step_num, step_desc in steps:
    if step_num in completed:
        continue

    log(f"\n[STEP {step_num}] {step_desc[:60]}...")

    # NEW: Create snapshot before mutation
    snapshot_ref = create_snapshot(f"step_{step_num}")

    # ... existing retry loop ...

    # On success (inside the loop, after STEP_COMPLETE + lint pass):
    if passed:
        log(f"[COMPLETE] Step {step_num}")
        # NEW: Drop snapshot after successful step (prevent stash growth)
        if snapshot_ref:
            drop_snapshot(snapshot_ref)
        seen_lint_hashes.clear()
        break

    # On failure (the else clause of the for loop):
    else:
        log(f"[FAILED] Step {step_num} after {MAX_RETRIES} attempts")
        # NEW: Restore on failure
        if snapshot_ref:
            restore_snapshot(snapshot_ref)
        if BACKUP_DIR.exists():
            log(f"[RECOVERY] Backups available in: {BACKUP_DIR}")
        sys.exit(1)
```

---

### 6. Include CLAUDE.md in Fix Prompt

**Location:** `phase_judge()` fix prompt (~line 754).

```python
# BEFORE
fix_prompt = f"""JUDGE FEEDBACK - Fixes Required:

{feedback}

## Changed Files
...

# AFTER
constitution = read_file(PROJECT_ROOT / "CLAUDE.md") if (PROJECT_ROOT / "CLAUDE.md").exists() else ""

fix_prompt = f"""JUDGE FEEDBACK - Fixes Required:

{feedback}

## Constitution (CLAUDE.md)
{constitution if constitution else "[No CLAUDE.md]"}

## Changed Files
...
```

---

## P2: Medium Priority

### 7. PLAN Structured Prompts

**Location:** Replace prompt in `phase_plan()` (~line 325).

```python
prompt = f"""ROLE: Lead Architect.
TASK: Create a step-by-step execution plan for the task described in: {task_file}

CONTEXT (Scout Report):
{scout}

STRATEGY:
1. Break into SMALL, ATOMIC steps
2. One file change per step (unless trivial)
3. Delete old code early to reduce noise
4. Final step MUST be verification

OUTPUT FORMAT (strict markdown, no preamble):
## Step 1: <Action Verb> <Target File>
## Step 2: <Action Verb> <Target File>
...
## Step N: Verify changes and run tests

Write to: {PLAN_FILE}"""
```

---

### 8. Escalating Lint Tone

**Location:** `phase_implement()` lint failure handling (~line 513).

```python
# BEFORE
if lint_hash in seen_lint_hashes:
    prompt += f"\n\nLINT FAILED (same as a previous attempt—try a different fix):\n{truncated}"
else:
    prompt += f"\n\nLINT FAILED:\n{truncated}\n\nFix the issues above."

# AFTER
if lint_hash in seen_lint_hashes:
    prompt += f"""

CRITICAL: You made the exact same error again.
Review the file content carefully. The previous approach did not work.
Try a DIFFERENT fix strategy.

Errors:
{truncated}"""
else:
    prompt += f"""

LINT CHECK: Your changes look good but failed strict validation.
You're close - fix these specific issues:

{truncated}"""
```

---

### 9. File Size Annotations in Scout

**Location:** Add helper function, update `phase_scout()` prompt.

```python
def get_file_tree_with_sizes(ignore: list[str] | None = None) -> str:
    """Generate file tree with size annotations."""
    ignore = ignore or ['node_modules', 'venv', '__pycache__', '.git', '.zen*']
    lines = []

    for path in PROJECT_ROOT.rglob('*'):
        if path.is_dir():
            continue
        if any(pattern.replace('*', '') in str(path) for pattern in ignore):
            continue

        try:
            rel = path.relative_to(PROJECT_ROOT)
            # Use binary mode and count newlines to handle encoding issues
            content = path.read_bytes()
            line_count = content.count(b'\n')
            if line_count > 1000:
                tag = "[MASSIVE]"
            elif line_count > 200:
                tag = "[LARGE]"
            else:
                tag = ""
            lines.append(f"{rel} {tag}".strip())
        except Exception:
            continue

    return "\n".join(sorted(lines)[:100])  # Cap at 100 files
```

**Update scout prompt** to include file tree in CONTEXT section.

---

## P3: Low Priority

### 10. Positive Reinforcement on Lint Success

**Location:** `phase_implement()` after lint passes (~line 527).

```python
if passed:
    log(f"[COMPLETE] Step {step_num}")
    # NEW: Track good patterns for next prompt
    if "type hint" in output.lower() or "typing" in output.lower():
        prompt += "\n\n[Note: Great job on the type hints. Maintain that standard.]"
    seen_lint_hashes.clear()
    break
```

**Note:** This is lowest priority. The ROI is speculative. Consider skipping unless you have evidence it helps.

---

## Verification Strategy

### Unit Tests for New Functions

```python
# tests/test_zen_helpers.py
import pytest
from unittest.mock import patch, MagicMock

def test_is_test_or_doc():
    assert _is_test_or_doc("README.md") == True
    assert _is_test_or_doc("tests/test_foo.py") == True
    assert _is_test_or_doc("src/auth.py") == False

def test_should_skip_judge_trivial_change():
    with patch('subprocess.run') as mock_run:
        # Mock: 2 lines added, 1 deleted in README.md
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="2\t1\tREADME.md"
        )
        assert should_skip_judge() == True

def test_should_skip_judge_security_file():
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="10\t5\tsrc/auth.py"
        )
        assert should_skip_judge() == False

def test_phase_verify_returns_bool_on_success():
    # Mock successful test run
    with patch('run_claude') as mock_claude:
        mock_claude.return_value = "TESTS_PASS"
        # ... setup mocks ...
        result = phase_verify()
        assert result == True  # Not sys.exit!

def test_phase_verify_returns_bool_on_failure():
    # Mock failed test run that exhausts retries
    with patch('run_claude') as mock_claude:
        mock_claude.return_value = "TESTS_FAIL"
        # ... setup mocks ...
        result = phase_verify()
        assert result == False  # Not sys.exit!
```

### Integration Test Scenarios

Create test tasks that exercise each path:

```
tests/tasks/
  ├── trivial_readme_change.md    → should skip judge
  ├── security_file_change.md     → should NOT skip judge
  ├── force_lint_failure.md       → should escalate to Opus
  └── force_step_failure.md       → should restore snapshot
```

### Manual Verification Checklist

```
□ P0-1: Force verify failure in judge loop → confirm no sys.exit, returns False
□ P0-2: Change only README.md → confirm "[JUDGE] Skipping: Only docs/tests"
□ P1-3: Create task that fails 2x → confirm "Escalating to opus" in log
□ P1-4: Mock "I cannot" response → confirm coaching prompt sent, retry occurs
□ P1-5: Force step failure → confirm stash created, then restored
□ P1-6: Create CLAUDE.md → trigger judge rejection → confirm constitution in fix prompt
```

### Regression Gate

Before each change, run the existing workflow. After each change, verify:

```bash
# Happy path still works
python zen.py test_task.md --dry-run

# Existing failure modes still exit correctly
python zen.py nonexistent.md  # Should error

# Full integration (use a trivial task)
echo "# Task: Add a comment to README.md" > /tmp/trivial.md
python zen.py /tmp/trivial.md
```

---

## Implementation Order (with Gates)

| Step | Change | Gate (must pass before next) |
|------|--------|------------------------------|
| 1 | P0-1: `phase_verify()` returns bool | Run `phase_judge` with forced verify failure → no sys.exit |
| 2 | P0-2: `should_skip_judge()` | `git diff` only README.md → "[JUDGE] Skipping" in log |
| 3 | P1-5: Snapshots | Force step failure → stash created/restored in log |
| 4 | P1-3: Model escalation | Force 2 lint failures → "Escalating to opus" in log |
| 5 | P1-4: Stuck detection | Mock "I cannot" → coaching prompt + retry in same attempt |
| 6 | P1-6: CLAUDE.md in fix | Add CLAUDE.md, trigger rejection → constitution in prompt |
| 7 | P2-* (batch) | Prompt improvements — low risk, batch together |
| 8 | P3-10 | Skip or defer — speculative ROI |

Total estimated diff: ~200-250 lines added/modified.

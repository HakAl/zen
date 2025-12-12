# Zen.py Refinements - Implementation Plan

Changes to `scripts/zen.py` organized by priority.

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
```



---

## Implementation Order (with Gates)

| Step | Change | Gate (must pass before next) |
|------|--------|------------------------------|
| 7 | P2-* (batch) | Prompt improvements — low risk, batch together |
| 8 | P3-10 | Skip or defer — speculative ROI |

Total estimated diff: ~200-250 lines added/modified.

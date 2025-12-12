# Zen.py Refinements - Implementation Plan

Changes to `scripts/zen.py` organized by priority.

---

## P0: Critical (Production Bug)

### 0. Move Summary Generation Out of phase_verify()

**Problem:** Summary generation happens inside `phase_verify()` on every call, including during judge re-verification. This causes:
1. **3-minute timeout** blocking workflow (Haiku API congestion)
2. **Misleading errors** — looks like verify failed, not just optional summary
3. **Wasted work** — summary regenerated even when judge will reject and re-verify
4. **Stale data risk** — summary may not reflect post-fix state

**Location:** Remove from `phase_verify()` (lines 833-840), add to `main()` (after line 1086).

**Fix:**

```python
# DELETE from phase_verify() (lines 833-840):
#     # Generate summary
#     summary = run_claude(
#         f"Summarize changes made. Be concise.\n\nPlan:\n{plan}",
#         model=MODEL_EYES,
#         timeout=TIMEOUT_SUMMARY,
#     )
#     if summary:
#         write_file(NOTES_FILE, summary)

# ADD to main() after judge phase, before SUCCESS print:
        # Generate summary (once, after all phases complete)
        plan = read_file(PLAN_FILE)
        summary = run_claude(
            f"Summarize the completed changes in 3-5 bullets.\n\nPlan:\n{plan}",
            model=MODEL_EYES,
            timeout=60,  # Reduced from 180 - fail fast
        )
        if summary:
            write_file(NOTES_FILE, summary)
        else:
            log("[SUMMARY] Skipped (timeout)")

        print("\n[SUCCESS]")
```

**Benefits:**
- Summary runs exactly once, after all fixes complete
- Reduced timeout (60s) — if Haiku can't respond fast, skip it
- Clear log message distinguishes summary timeout from verify failure
- Workflow SUCCESS not blocked by optional summary

**Gate:** Run full workflow, verify summary appears after judge approval.

---

## P1: High Priority (Low Risk, Immediate Value)

### 1. Cost Tracking

**Rationale:** Zero risk, ~20 lines, provides data for optimization decisions.

**Location:** Config section (~line 45), `run_claude()` (~line 144), `main()` (~line 1025).

```python
# Add to config section (after TIMEOUT_SUMMARY)
TRACK_COSTS = os.getenv("ZEN_TRACK_COSTS", "false").lower() == "true"
_phase_times: Dict[str, float] = {}
_current_phase: str = "unknown"

# Add helper (after config section)
def set_phase(name: str) -> None:
    global _current_phase
    _current_phase = name

# Modify run_claude - wrap existing logic with timing
def run_claude(prompt: str, model: str, timeout: Optional[int] = None) -> Optional[str]:
    start = time.time()
    # ... existing implementation unchanged ...
    # Before final return, add:
    if TRACK_COSTS and output is not None:
        elapsed = time.time() - start
        _phase_times[_current_phase] = _phase_times.get(_current_phase, 0) + elapsed
        log(f"[TIME] {model}: {elapsed:.1f}s")
    return output

# Add set_phase() calls at start of each phase function:
# - phase_scout(): set_phase("scout")
# - phase_plan(): set_phase("plan")
# - phase_implement(): set_phase("implement")
# - phase_verify(): set_phase("verify")
# - phase_judge(): set_phase("judge")

# Add to main() before "[SUCCESS]" print
if TRACK_COSTS:
    total = sum(_phase_times.values())
    breakdown = ", ".join(f"{k}={v:.0f}s" for k, v in _phase_times.items())
    log(f"[COST] Total: {total:.0f}s ({breakdown})")
```

**Gate:** Run with `ZEN_TRACK_COSTS=true` on a simple task, verify timing output.

---

## P2: Medium Priority (High Value, Medium Effort)

### 2. XML Prompt Structuring

**Rationale:** Anthropic models are trained on XML boundaries. Reduces hallucination, improves instruction following. Output remains markdown (human-readable).

**Prompts to refactor (6 total):**

| Location | Phase | Current Style |
|----------|-------|---------------|
| `phase_scout` :464 | Scout | Markdown headers |
| `phase_plan` :514 | Plan | Markdown headers |
| `phase_implement` :662 | Execute | Inline text |
| `phase_verify` :753 | Verify | Numbered list |
| `phase_judge` :865 | Judge | Markdown headers |
| `phase_judge` :964 | Fix | Inline text |

**Tag taxonomy:**
```xml
<task>...</task>           # The file/objective being worked on
<context>...</context>     # Scout report, plan, prior state
<rules>...</rules>         # Constraints, requirements
<output>...</output>       # What/where to write (format stays markdown)
```

**Implementation order (one at a time, verify between each):**

#### 2a. phase_scout

```python
prompt = f"""<task>
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
- Skip: test*, docs/, node_modules/, venv/, migrations/, __pycache__/
- If unsure whether a file matters, include in Context (not Targeted)
</constraints>

<output>
Write to: {SCOUT_FILE}

Format (markdown, all 4 sections required, use "None" if empty):
## Targeted Files (Must Change)
- `path/to/file.py`: one-line reason

## Context Files (Read-Only)
- `path/to/file.py`: one-line reason

## Deletion Candidates
- `path/to/file.py`: one-line reason

## Open Questions
- Question about ambiguity
</output>"""
```

#### 2b. phase_plan

```python
prompt = f"""<task>
Create execution plan for: {task_file}
</task>

<context>
{scout}
</context>

<rules>
- Clean Code over Backward Compatibility
- DELETE old code, no shims
- UPDATE callers directly
- Final step MUST be verification (test/verify/validate)
</rules>

<output>
Write to: {PLAN_FILE}

Format (strict markdown, no preamble):
## Step 1: <action verb> <specific target>
## Step 2: <action verb> <specific target>
...
## Step N: Verify changes and run tests

Each step: one atomic change. No sub-steps, no bullet lists within steps.
</output>"""
```

#### 2c. phase_judge

```python
prompt = f"""<role>Senior Architect. Be direct and concise.</role>

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
</output>"""
```

#### 2d-f. Remaining prompts

Convert `phase_implement`, `phase_verify`, and judge fix prompt following same pattern.

**Gate:** Run full workflow on test task after each conversion, compare output quality.

---

### 3. Escalating Lint Tone

**Rationale:** Current retry messages are flat. Escalating tone helps model understand severity.

**Location:** `phase_implement()` lint failure handling (~line 720).

```python
# Current
if lint_hash in seen_lint_hashes:
    prompt += f"\n\nLINT FAILED (same as a previous attempt—try a different fix):\n{truncated}"
else:
    prompt += f"\n\nLINT FAILED:\n{truncated}\n\nFix the issues above."

# Proposed
if lint_hash in seen_lint_hashes:
    prompt += f"""

<lint_failure severity="critical">
You made the exact same error again. The previous approach did not work.
Review the file content carefully. Try a DIFFERENT fix strategy.

{truncated}
</lint_failure>"""
else:
    prompt += f"""

<lint_failure>
Your changes look good but failed strict validation. Fix these specific issues:

{truncated}
</lint_failure>"""
```

**Gate:** Verify lint retries still work on a file with intentional lint errors.

---

## P3: Low Priority (Nice to Have)

### 4. File Size Annotations in Scout

**Rationale:** Helps model avoid reading massive files. More code, marginal benefit.

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

    return "\n".join(sorted(lines)[:100])
```

**Gate:** Defer until P1-P2 complete.

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
        mock_run.return_value = MagicMock(returncode=0, stdout="2\t1\tREADME.md")
        assert should_skip_judge() == True

def test_should_skip_judge_security_file():
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="10\t5\tsrc/auth.py")
        assert should_skip_judge() == False
```

---

## Implementation Order

| Step | Item | Risk | Effort | Gate |
|------|------|------|--------|------|
| 1 | Cost Tracking | None | ~20 LOC | Verify timing output |
| 2a | XML: scout prompt | Low | 1 prompt | Compare scout.md quality |
| 2b | XML: plan prompt | Low | 1 prompt | Compare plan.md quality |
| 2c | XML: judge prompt | Low | 1 prompt | Verify judge approvals |
| 2d | XML: remaining prompts | Low | 3 prompts | Full workflow test |
| 3 | Escalating Lint Tone | Low | ~10 LOC | Lint retry test |
| 4 | File Size Annotations | Low | ~25 LOC | Defer |

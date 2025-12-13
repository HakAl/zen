# Zen.py Refinements - Implementation Plan

Changes to `scripts/zen.py` organized by priority.

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
| 1 | Cost Tracking (JSON) | Low | ~50 LOC | Verify costs match console; check file outputs |
| 2a | XML: scout prompt | Low | 1 prompt | Compare scout.md quality |
| 2b | XML: plan prompt | Low | 1 prompt | Compare plan.md quality |
| 2c | XML: judge prompt | Low | 1 prompt | Verify judge approvals |
| 2d | XML: remaining prompts | Low | 3 prompts | Full workflow test |
| 3 | Escalating Lint Tone | Low | ~10 LOC | Lint retry test |
| 4 | File Size Annotations | Low | ~25 LOC | Defer |


---

# BUGS

## Linter

---
 ### ✅ 2. **Improve False Positives: Refine Regex Patterns**
 Some rules may trigger on false positives.

 #### 🔍 Example: `HARDCODED_IP` Rule
 ```python
 r"\b(?!127\.0\.0\.1|...)\d+\.\d+\.\d+\.\d+\b"
 ```
 - The negative lookahead `(?!...)` only applies to the first octet — **this is incorrect**.
 - E.g., `192.168.1.1` might still match if the negative lookahead doesn't consume the full IP.

 #### ✅ Fix:
 Use a **negative lookahead that matches the entire IP**, or better yet, **match all IPs first, then filter
 programmatically**.

 ```python
 # Instead of complex regex, do:
 ip_match = re.match(r"\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b", line)
 if ip_match and not is_private_ip(ip_match.groups()):
     yield Issue(...)
 ```

 > 📄 **Relevant Code**: Line ~100+ for `HARDCODED_IP`. Replace with logic-based check.
---

---
 ### ✅ 3. **Add Per-File or Per-Line Disable Comments**
 Like `# noqa` in flake8 or `// eslint-disable-line`.

 #### ✅ Suggested Syntax:
 ```python
 x = secret_key  # zenlint: ignore POSSIBLE_SECRET
 ```

 #### 💡 Implementation:
 Before checking each line, scan for:
 ```python
 r"#\s*zenlint:\s*ignore\s+([A-Z_]+)"
 ```
 Then skip matching rules accordingly.

 > 📄 **Relevant Code**: In the main loop (likely not shown), before calling `rule.search(text)`.
---

---

 ### ✅ 4. **Improve Performance: Skip Binary Files & Large Files**
 Currently, no indication of file type checking — could crash or hang on large/binary files.

 #### ✅ Add:
 ```python
 def is_text_file(filepath: Path) -> bool:
     try:
         with open(filepath, 'r') as f:
             f.read(1024)
         return True
     except UnicodeDecodeError:
         return False
 ```

 Also, set a max file size limit:
 ```python
 if filepath.stat().st_size > 1_000_000:  # 1MB
     return []
 ```

 > 📄 **Relevant Code**: Likely in a `scan_directory()` function (not shown), but should wrap file processing.

---


 ### ✅ 5. **Add Language-Specific Scoping**
 Rules like `INLINE_IMPORT` assume Python/JS syntax, but the linter claims to be universal.

 #### ✅ Improve:
 - Detect file extension.
 - Apply rules only to relevant languages.

 ```python
 RULE_LANGUAGES = {
     "INLINE_IMPORT": {"py", "js", "ts", "java"},
     "API_KEY": {"all"},
     ...
 }
 ```

 Then:
 ```python
 ext = file.suffix.lstrip(".").lower()
 if rule_langs != {"all"} and ext not in rule_langs:
     continue
 ```

 > 📄 **Relevant Code**: Add metadata to `Rule` class or keep mapping separately.

---

## Zen

1. Break up god class

```
   ├── zen/
   │   ├── __main__.py          # CLI entrypoint
   │   ├── core/state.py        # WorkDir, TaskState
   │   ├── planning/planner.py
   │   ├── execution/runner.py
   │   ├── judge/judge.py
   │   └── utils/files.py
```


7. **Dry Run Mode Enhancement**
 > `--dry-run` shows what would happen, but output is minimal.

 #### 🛠️ Suggested Improvements:                                                                                        
- In dry-run:
   - Print full command that would be executed.
   - Show prompt that would be sent to Claude.
   - Do not create real files (use temp paths).
 - Add `--verbose` flag to show more detail.

 #### 💡 Benefit:
 Safer exploration and debugging.



 ### 9. **Security & Input Sanitization**
 > Task file path is used directly; potential for injection via filenames/content.

 #### 🛠️ Suggested Improvements:                                                                                        
- Sanitize input paths:
   ```python
   task_path = Path(task_file).resolve().relative_to(PROJECT_ROOT)
   ```
 - Avoid shell=True in subprocess.
 - Hash prompts/responses for caching and safety.

 #### 💡 Benefit:
 Prevents path traversal or command injection in edge cases.
 

 ### 10. **Documentation & User Guidance**
 > Good docstring, but no in-file examples or help menu.

 #### 🛠️ Suggested Improvements:                                                                                        
- Add `--help` flag with usage examples.
 - Include sample task file in docs.
 - Link to `implementation_plan.md` and `CLAUDE.md`.


--



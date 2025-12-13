# Zen.py Refinements - Implementation Plan

Changes organized by priority.


## P2: Medium Priority (Cost & Quality)

### 2.1 Haiku-First Test Execution

**Problem:** Test runs use Sonnet ($0.30+) even when tests pass first try.

**Location:** `phase_verify()` in both files

**Implementation:**
```python
def phase_verify() -> bool:
    # First attempt: Haiku just runs tests (no fixing)
    haiku_prompt = f"""<task>
Run the test suite and report results.
</task>

<actions>
1. Run: pytest -q --tb=short (or project's test command)
2. Write output to: {TEST_OUTPUT_PATH}
</actions>

<output>
End with: TESTS_PASS or TESTS_FAIL
</output>"""

    output = run_claude(haiku_prompt, model=MODEL_EYES, phase="verify_check")

    if "TESTS_PASS" in output and verify_test_output(read_file(TEST_OUTPUT_FILE)):
        log("[VERIFY] Passed (Haiku).")
        return True

    # Tests failed or unclear - escalate to Sonnet for fixing
    log("[VERIFY] Escalating to Sonnet for fixes...")
    # ... existing Sonnet retry logic ...
```

**Savings:** ~$0.27 per run when tests pass first try

**Effort:** ~30 LOC | **Risk:** Medium (adds complexity)

---

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

## Implementation Order

| Step | Item | Effort | Gate |
|------|------|--------|------|
| 2 | 1.2 Path sanitization | ~10 LOC | Rejects `../../../etc/passwd` |
| 3 | 1.3 HARDCODED_IP fix | ~15 LOC | `192.168.x.x` no longer flagged |
| 4 | 2.1 Haiku-first tests | ~30 LOC | Cost drops when tests pass |
| 5 | 2.2 `# zenlint: ignore` | ~20 LOC | Inline suppression works |
| 6 | 2.3 Language scoping | ~40 LOC | JS rules don't fire on .md |

---

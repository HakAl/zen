# Zen.py Refinements - Implementation Plan

Changes organized by priority.

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

## Implementation Order

| Step | Item | Effort | Gate |
|------|------|--------|------|
| 1    | 2.2 `# zenlint: ignore` | ~20 LOC | Inline suppression works |
| 2    | 2.3 Language scoping | ~40 LOC | JS rules don't fire on .md |

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

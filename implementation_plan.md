# Zen.py Refinements - Implementation Plan

Changes organized by priority.


## P1: High Priority -- TESTING 1-3 NOW

## Recommended Strategy Enhancements

### 1. Step Complexity Routing (From implementation_plan.md)

The existing Haiku-First plan addresses this. Triage before Sonnet:

```python
# Rate step complexity before execution
complexity = run_claude(
    f"Rate 1-3 (1=trivial, 3=complex):\n{step_desc}",
    model=MODEL_EYES, timeout=20
)
model = MODEL_EYES if "1" in complexity else MODEL_HANDS
```



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
| 2 | 1.2 Path sanitization | ~10 LOC | Rejects `../../../etc/passwd` |
| 3 | 1.3 HARDCODED_IP fix | ~15 LOC | `192.168.x.x` no longer flagged |
| 4 | 2.1 Haiku-first tests | ~30 LOC | Cost drops when tests pass |
| 5 | 2.2 `# zenlint: ignore` | ~20 LOC | Inline suppression works |
| 6 | 2.3 Language scoping | ~40 LOC | JS rules don't fire on .md |

---
  Haiku-First Implementation Plan

  Core Changes

  1. Triage before Sonnet fix (phase_verify)
  # After test failure detected, before Sonnet retry:
  triage_prompt = f"""Classify test failure:
  {test_output[:1500]}

  Reply: TRIVIAL (typo/import/simple) or COMPLEX (logic/architecture)"""

  triage = run_claude(triage_prompt, model=MODEL_EYES, phase="triage", timeout=30)

  if "TRIVIAL" in triage:
      # Haiku attempts fix (cheap shot)
      haiku_fix = run_claude(fix_prompt, model=MODEL_EYES, phase="haiku_fix", timeout=90)
      # If fails, fall through to Sonnet (doesn't count against retries)

  2. Lint fix suggestions (phase_implement)
  # After lint failure, before Sonnet retry:
  if not passed:
      suggestion = run_claude(
          f"Suggest 1-line fix for:\n{lint_out[:500]}",
          model=MODEL_EYES, phase="lint_triage", timeout=30
      )
      # Append suggestion to Sonnet's retry prompt

  3. Step complexity routing (optional)
  # Before executing step:
  complexity = run_claude(
      f"Rate step complexity 1-3:\n{step_desc}",
      model=MODEL_EYES, phase="complexity", timeout=20
  )
  model = MODEL_EYES if "1" in complexity else MODEL_HANDS

  Estimated Savings

  | Scenario         | Current Cost    | With Haiku-First |
  |------------------|-----------------|------------------|
  | Trivial test fix | ~$0.10 (Sonnet) | ~$0.02 (Haiku)   |
  | Lint retry       | ~$0.08 (Sonnet) | ~$0.01 + context |
  | Simple step      | ~$0.06 (Sonnet) | ~$0.01 (Haiku)   |

  ---


  For cost savings, the only levers are:
  1. Tier down: Sonnet → Haiku (12x cheaper)
  2. Fewer tokens: Shorter prompts, truncate context
  3. Fewer calls: Consolidate steps, skip phases
  4. Cache hits: Prompt prefix caching (when it works)


IDEA: Track context and start new sessions when we reach threshold(s) instead of new context for each step.
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

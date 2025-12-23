# Prompt Improvements

Proposed changes to zen prompts based on swarm code review findings.

---

## Problem

Haiku-generated code had preventable issues:
- No exception handling in executor
- No cleanup of temp directories
- Unused config fields (dead code)
- Hardcoded values instead of config
- Tests using `Path.cwd()` instead of temp dirs

Root cause: Planning and implementation prompts don't emphasize robustness.

---

## Changes Already Applied

### 1. Test isolation guidance (core.py:864)

```diff
- 1. TESTS: If writing tests, maximum 3 functions. Cover: happy path, one error, one edge.
+ 1. TESTS: If writing tests, maximum 3 functions. Cover: happy path, one error, one edge. Use temp directories for file I/O.
```

**Status:** Done

---

## Proposed Changes

### 2. Compress EXAMPLES in planning prompt (core.py:642-663)

**Before:** 20 lines
```xml
<EXAMPLES>
BAD PLAN (10 steps, bloated):
## Step 1: Add retry dependency
## Step 2: Create config class
...10 lines...

GOOD PLAN (6 steps, efficient):
## Step 1: Add dependencies and configuration
...6 lines...
</EXAMPLES>
```

**After:** 4 lines
```xml
<EXAMPLES>
BAD: ## Add retry ## Add timeout ## Add rate limit ## Test retry ## Test timeout (10 micro-steps)
GOOD: ## Implement retry with timeout and rate limiting ## Add tests ## Verify (4 steps)
</EXAMPLES>
```

**Rationale:** Same signal, fewer tokens.

---

### 3. Inject constitution into planning prompt

**Before:** Planning has inline `<rules>` that duplicate CLAUDE.md

**After:** Inject project's CLAUDE.md as `<constitution>`, keep only plan-specific rules

```python
constitution = read_file(PROJECT_ROOT / "CLAUDE.md") if (PROJECT_ROOT / "CLAUDE.md").exists() else ""
```

```xml
<constitution>
{constitution}
</constitution>

<planning_rules>
- Final step MUST be verification
- Consolidate: 4-6 steps, not 10 micro-steps
</planning_rules>
```

**Rationale:**
- Same principles at plan and judge = fewer reworks
- Removes duplication
- Project-specific CLAUDE.md customizations apply to planning

---

### 4. Add robustness checklist to planning

```xml
<checklist>
Before outputting plan, verify each step addresses:
- Error paths: What if external calls fail?
- Cleanup: Temp resources created → disposed?
- Config: Hardcoded values → configurable?
</checklist>
```

**Rationale:** Catches the 4 preventable bugs from swarm review.

---

## Implementation Order

1. Commit current changes (test fixes, RESTRICTIONS tweak, roadmap update)
2. Compress EXAMPLES (low risk, saves tokens)
3. Add robustness checklist (medium risk, may increase step count)
4. Inject constitution (higher risk, changes prompt structure)

---

## Metrics to Watch

- Plan step count (should stay 4-6, not balloon)
- Implementation cost (should stay ~$0.50-1.50 per task)
- Judge rejection rate (should decrease)
- Bug types in generated code (robustness issues should decrease)

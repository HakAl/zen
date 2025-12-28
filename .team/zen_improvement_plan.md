# Zen Mode Improvement Plan
**Generated:** 2025-12-27
**Team:** Peter (Lead), Neo (Architecture), Reba (Quality), Matt (Security/Audit)

---

## Executive Summary

Team analysis of Zen Mode identified **47 findings** across architecture, code quality, security, and performance. This plan prioritizes fixes by impact and risk.

**Key Themes:**
1. **Safety**: The `--dangerously-skip-permissions` flag undermines all safeguards
2. **Token Waste**: Full plan sent with every step (~40% waste)
3. **Thread Safety**: Global state breaks swarm parallelism
4. **Code Debt**: Duplicate APIs, missing types, 15+ `sys.exit()` calls

---

## P0: Critical (Fix This Week)

### 1. `cmd_eject` NameError
**File:** `cli.py:164`
**Issue:** Function called but never defined - runtime crash waiting to happen
**Fix:** Remove dead code branch or implement the function

### 2. Remove `--dangerously-skip-permissions`
**File:** `claude.py:90-91`
**Issue:** Bypasses all permission checks, LLM can execute arbitrary operations
**Fix:** Make opt-in via explicit `ZEN_SKIP_PERMISSIONS=true` env var with warning

### 3. Eliminate Global State
**File:** `core.py:108`
**Issue:** 9 globals mutated at runtime - breaks thread safety
**Fix:** Use Context object exclusively, remove all `global` declarations

### 4. Fix Judge Stdin Blocking
**File:** `judge.py:227-234`
**Issue:** Blocks forever on stdin in automated/swarm mode
**Fix:** Add `--non-interactive` flag, default to fail-closed in swarm

---

## P1: High Priority (This Sprint)

### 5. Reduce Step Prompt Context
**File:** `implement.py:117-176`
**Issue:** Full plan (2000+ tokens) sent with every step
**Fix:** Extract only current step + dependencies
**Impact:** ~40% token reduction

### 6. Pre-flight Swarm Conflict Detection
**File:** `swarm.py:456-475`
**Issue:** Conflicts detected AFTER execution, not before
**Fix:** Parse all TARGETS headers before worker spawn, block on overlap

### 7. Fix Linter Thread Leak
**File:** `implement.py:31-58`
**Issue:** Timed-out threads continue running
**Fix:** Use subprocess with explicit kill, not threading

### 8. Delete Duplicate Verify Code
**File:** `verify.py`
**Issue:** `phase_verify` and `phase_verify_ctx` are nearly identical
**Fix:** Keep only `_ctx` variants

### 9. Strengthen Path Traversal
**File:** `swarm.py:210-234`
**Issue:** Windows paths like `..\..\file` may bypass checks
**Fix:** Normalize paths, explicit `..` component check

### 10. Warn on Local zen.py
**File:** `cli.py:73-92`
**Issue:** Executes without warning - supply chain risk
**Fix:** Require `--use-local` flag or print warning

---

## P2: Medium Priority (Next Sprint)

### 11. Remove Plan from Verify Prompts
**File:** `verify.py:332-365`
**Impact:** ~20% token savings

### 12. Batch grep_impact Calls
**File:** `scout.py:155-215`
**Fix:** Single `git grep -E "pattern1|pattern2"` instead of N calls

### 13. Add Type Hints
**Files:** `cli.py`, `linter.py`, `swarm.py`
**Focus:** Public API functions first

### 14. Replace sys.exit() with Exceptions
**Files:** All modules (15+ occurrences)
**Fix:** Create `ZenError` hierarchy, catch at top level

### 15. Add Cost Budgets
**File:** `context.py`
**Fix:** `MAX_COST_PER_TASK` config, abort when exceeded

### 16. Validate Environment Variables
**File:** `config.py`
**Fix:** try/except for int conversion, model name allowlist

### 17. Improve Claude Error Handling
**File:** `claude.py:145-150`
**Fix:** Distinguish error types, don't catch broad Exception

---

## Quick Wins (< 1 hour each)

| Task | File | Lines |
|------|------|-------|
| Remove cmd_eject branch | cli.py | 164-166 |
| Cache constitution | files.py | 179-210 |
| Pre-compile regex | plan.py | 122, 134-137 |
| Add log() to Context | context.py | new method |
| Type hint dataclasses | context.py, swarm.py | various |

---

## Test Coverage Gaps

| Module | Status | Priority |
|--------|--------|----------|
| cli.py | NO tests | HIGH |
| implement.py | NO tests | HIGH |
| files.py | Partial | MEDIUM |
| core.py | Partial | MEDIUM |
| context.py | Indirect only | LOW |

---

## Architecture Recommendations

### Short Term
1. Complete migration to Context-based APIs
2. Add per-task timeout in swarm (not swarm-level)
3. Implement LLM circuit breaker with exponential backoff

### Long Term
1. Incremental scout cache (project-wide symbol index)
2. Streaming output for long steps
3. Semantic diff for test verification
4. Tool call interception/audit log

---

## Security Hardening

1. **Critical:** Gate `--dangerously-skip-permissions`
2. **High:** Sanitize task file content in prompts
3. **Medium:** Filter subprocess environment variables
4. **Low:** Add secrets detection warning

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Token cost per run | $0.10-0.50 | $0.06-0.30 |
| Scout phase time | 30-60s | 15-30s |
| Swarm overhead | 5-10s | 2-5s |
| Test coverage | ~60% | 85% |
| Type hint coverage | ~40% | 90% |

---

## Next Steps

1. **User Decision:** Which priority tier to tackle first?
2. **Quick Wins:** Can be done immediately (team recommends starting here)
3. **Sprint Planning:** P0 items should be addressed before next feature work

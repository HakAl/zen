# Zen Performance Research Findings

Analysis of test runs from `zen_tests/` directories (V1, V2, V3 variants).

---

## Executive Summary

Three iterations showed **44% total cost reduction** ($3.51 → $1.97) through:
1. Scout model switch (sonnet → haiku): 65% scout phase savings
2. Plan step consolidation (16 → 9 → 12 steps): 40% implement phase savings
3. Test step grouping: 5.8x cost reduction on test-related steps

---

## Cost Breakdown by Phase

| Phase | V1 | V2 | V3 | Insight |
|-------|-----|-----|-----|---------|
| **Scout** | $0.180 (sonnet) | $0.142 (haiku) | $0.063 (haiku) | 65% savings from model switch |
| **Plan** | $0.152 | $0.179 | $0.003 | V3 got prompt cache hit |
| **Implement** | $2.615 (16 steps) | $1.553 (9 steps) | $1.540 (12 steps) | Consolidated steps save ~40% |
| **Verify** | $0.265 | $0.126 | $0.099 | Better test parsing |
| **Judge** | $0.261 | $0.215 | $0.222 | Relatively stable |
| **Total** | **$3.510** | **$2.247** | **$1.966** | 44% total reduction |

---

## Key Finding: Test Step Granularity

### V1's Test Steps (Steps 12-15)
```
Step 12: $0.30 - retry logic tests
Step 13: $0.20 - rate limiting tests
Step 14: $0.24 - user-agent tests
Step 15: $0.42 - edge case tests
────────────────────────────────
Total: ~$1.16 for 4 separate test categories
```

### V2's Test Step (Step 7)
```
Step 7: $0.20 - ALL tests consolidated
────────────────────────────────
Total: $0.20
```

**Result: 5.8x cost reduction** by consolidating test steps into a single step.

---

## Token Accumulation Problem

V1 late steps show context bloat:

| Step | Input Tokens | Cost |
|------|--------------|------|
| Steps 1-11 | 15-50 avg | $0.05-0.13 |
| Step 14 | 2054 | $0.24 |
| Step 15 | 2071 | $0.42 |

Context accumulates through the implement phase, inflating costs for later steps.

---

## Plan Structure Comparison

### V1: 16 Steps (Over-granular)
```
Steps 1-8:   Implementation (8 steps)
Steps 9-11:  Test setup (3 steps)
Steps 12-15: Test categories (4 separate steps)  <- Problem
Step 16:     Verify
```

### V2: 9 Steps (Most Efficient)
```
Steps 1-4:  Implementation + modular setup
Steps 5-7:  Test setup + ALL tests combined  <- Fixed
Steps 8-9:  Dependencies + verify
```

### V3: 12 Steps (Balanced)
```
Steps 1-8:   Implementation (more features)
Steps 9-11:  Test setup + tests (consolidated)
Step 12:     Verify
```

**V2's approach was most cost-efficient** at $0.17/step average vs V1's $0.16/step, but with 44% fewer steps.

---

## Recommended Strategy Enhancements

### 1. Plan Step Consolidation Guidance (High Impact)

Add to PLAN phase prompt:

```
CONSOLIDATION RULES:
- Combine related test categories into 1-2 test steps maximum
- Do NOT create separate steps for: retry tests, validation tests, edge case tests
- Group: "Create all unit tests for [component]" not "Create tests for X, then Y, then Z"
- Target: 8-12 steps for typical features, never exceed 15
```

**Estimated savings: ~$0.90/task**

### 2. Plan Efficiency Validator

Reject inefficient plans before execution:

```python
def validate_plan_efficiency(steps: list[str]) -> tuple[bool, str]:
    """Check plan for common inefficiency patterns."""
    test_steps = [s for s in steps if "test" in s.lower()]

    if len(test_steps) > 2:
        return False, "CONSOLIDATE: Too many test steps. Combine into 1-2 steps."

    if len(steps) > 15:
        return False, "SIMPLIFY: Plan exceeds 15 steps. Look for consolidation."

    # Check for overly granular patterns
    granular_patterns = ["add test for", "create test for", "write test for"]
    granular_count = sum(1 for s in steps if any(p in s.lower() for p in granular_patterns))
    if granular_count > 2:
        return False, "CONSOLIDATE: Multiple 'add test for X' steps. Group into single test step."

    return True, None
```

**Benefit: Prevents bloated plans before expensive execution**

### 3. Prompt Structure for Cache Optimization

V3's plan phase cost $0.003 vs $0.15-0.18 in V1/V2 (likely cache hit).

Structure prompts for maximum cache reuse:
```
[STABLE - cacheable]
1. System prompt
2. CLAUDE.md constitution
3. Role instructions

[VARIABLE - at end]
4. Scout output
5. Task description
```

**Estimated savings: ~$0.15/task on cache hits**

### 4. Step Complexity Routing (From implementation_plan.md)

The existing Haiku-First plan addresses this. Triage before Sonnet:

```python
# Rate step complexity before execution
complexity = run_claude(
    f"Rate 1-3 (1=trivial, 3=complex):\n{step_desc}",
    model=MODEL_EYES, timeout=20
)
model = MODEL_EYES if "1" in complexity else MODEL_HANDS
```

---

## Quick Wins Priority Matrix

| Enhancement | Savings/Task | Effort | Priority |
|-------------|--------------|--------|----------|
| Test step consolidation in PLAN prompt | ~$0.90 | ~10 LOC | **P1** |
| Plan efficiency validator | Prevents bloat | ~20 LOC | **P1** |
| Prompt structure for caching | ~$0.15 | ~5 LOC | **P2** |
| Haiku-first triage (already planned) | ~$0.10 | ~30 LOC | **P2** |

---

## Experimental: Context Pruning (P3 - Test in Isolation)

**Status:** Lowest priority. Test separately after P1/P2 improvements are validated.

**Why isolated:** Context pruning is risky - too aggressive loses important details, too conservative saves nothing. The V1→V3 improvements came mostly from better planning (fewer steps), not context tricks.

**If tested, use structured extraction instead of word limits:**

```python
# BAD: Arbitrary word limit
summary = run_claude(f"Summarize in <100 words:\n{context}", ...)

# BETTER: Structured extraction of what matters
PRUNE_PROMPT = """Extract from this step output:
1. Files modified (paths only)
2. Functions/classes added (names only, not code)
3. Key decisions affecting later steps
4. Dependencies for remaining steps

Step output:
{step_output}
"""

summary = run_claude(PRUNE_PROMPT.format(step_output=output), model=MODEL_EYES, ...)
```

**File-grounded alternative:**

Since files ARE the source of truth, context can reference them rather than carry code:
```
"scraper.py now has WebScraper with fetch_page(), parse_html()"
```
The model can re-read the file if it needs full code.

**Adaptive threshold:**

```python
TOKEN_THRESHOLD = 4000  # Only prune when bloated

if estimate_tokens(context) > TOKEN_THRESHOLD:
    # Structured prune
    ...
else:
    # Keep full context
    pass
```

**Test plan:**
1. Run 3-5 tasks with P1/P2 improvements only (baseline)
2. Run same tasks with context pruning enabled
3. Compare: cost savings vs quality/success rate
4. Only adopt if quality remains equal

---

## Architecture Observations

### What Worked in Each Variant

| Aspect | V1 | V2 | V3 | Winner |
|--------|----|----|----|----|
| HTTP Library | requests | requests | httpx | V3 (faster) |
| Parser | html.parser | html.parser | lxml | V3 (faster) |
| Architecture | Monolithic | Modular (3 files) | Monolithic + rich | V3 |
| Config location | Embedded | Separate file | Embedded | V1/V3 |
| Test count | 86 | 49 | 38 | V3 (focused) |
| Test time | 57.18s | 36.43s | 21.97s | V3 |

### Insight: Modular vs Monolithic

V2's modular approach (separate config.py, exceptions.py) added steps without proportional benefit for this scope. V3's "smart monolithic" (everything in scraper.py with clear sections) was more efficient.

**Recommendation:** Scout/Plan should consider scope when recommending architecture:
- Small components (<500 LOC): Keep monolithic
- Medium components (500-1500 LOC): Consider 2-3 files
- Large systems (>1500 LOC): Full modular

---

## Test Data Locations

```
C:\Users\anyth\MINE\dev\zen_tests\
├── .1____zen___1\    # V1: 16 steps, $3.51, sonnet scout
├── .2___zen___2\     # V2: 9 steps, $2.25, haiku scout, modular
└── .3___zen__3\      # V3: 12 steps, $1.97, haiku scout, httpx/lxml
```

Each contains: `log.md`, `plan.md`, `scout.md`, `final_notes.md`, `test_output.txt`

---

## Runs 4-9: Plan Validation & Haiku-First Tests

Extended testing to validate optimization strategies.

### Run Summary (Runs 4-9)

| Run | Steps | Total Cost | Key Test | Outcome |
|-----|-------|------------|----------|---------|
| 4 | 9 | $2.80 | Baseline with warning | Success |
| 5 | 9 | N/A | Rate limit hit | Failed (external) |
| 6 | 8 | $1.83 | Warning-only validation | **Best baseline** |
| 7 | 8 | $2.57 | Plan retry loop | Retry made plan worse (3→4 test steps) |
| 8 | 10 | $4.85 | New feedback prompt | Prompt never triggered, micro-steps bloat |
| 9 | 8 | $1.94 | **Haiku-first tests** | **4/4 test steps succeeded with Haiku** |

---

### Finding: Plan Retry Doesn't Work

**Run 7 tested** in-loop plan validation with retry:
```
[07:38:40] [PLAN] Inefficient (3 test steps), retrying...
[07:39:28] [PLAN] Warning: 4 test steps found (proceeding anyway)
```

**Result:** Opus produced a *worse* plan after feedback. Retry cost an extra ~$0.12 for negative value.

**Run 8 tested** explicit feedback prompt showing actual steps to merge:
```python
prompt = base_prompt + f"""
<feedback>
REJECTED: Your plan has {len(test_steps)} test steps. Maximum allowed: 2.
MERGE these into a single step:
{actual_test_steps_list}
</feedback>"""
```

**Result:** Plan only had 1 test step (validation never triggered), but 10 total steps with micro-implementation granularity. Cost $4.85 - highest yet.

**Conclusion:** Opus plan quality is highly variable regardless of feedback. Reverted to warning-only. Detection kept for observability, retry removed.

---

### Finding: Haiku Writes Tests Successfully

**Hypothesis:** Tests are formulaic (setup → action → assert), constrained scope, repetitive patterns. Haiku should handle them.

**Run 9 Implementation:**
```python
is_test_step = "test" in step_desc.lower()

if is_test_step:
    log(f"  Trying {MODEL_EYES} for test step...")
    haiku_output = run_claude(prompt, model=MODEL_EYES, ...)

    if "STEP_COMPLETE" in haiku_output:
        passed, lint_out = run_linter()
        if passed:
            log(f"[COMPLETE] Step {step_num} ({MODEL_EYES})")
            continue  # Success - next step
    # Fall back to Sonnet if Haiku fails
```

**Run 9 Results:**
| Step | Description | Model | Cost |
|------|-------------|-------|------|
| 1 | requirements.txt ("testing" deps) | haiku | $0.015 |
| 6 | conftest.py | haiku | $0.100 |
| 7 | test_scraper.py | haiku | $0.170 |
| 8 | Verify/run tests | haiku | $0.149 |
| **Total test steps** | | **haiku** | **$0.434** |

**Comparison - Implementation Phase Cost:**
| Run | Haiku | Sonnet | Total Impl |
|-----|-------|--------|------------|
| 6 (baseline) | $0 | $1.18 | $1.18 |
| 8 (worst) | $0 | $3.15 | $3.15 |
| **9 (haiku-first)** | **$0.43** | **$0.48** | **$0.91** |

**Success rate:** 4/4 test steps completed by Haiku with zero fallbacks.

**Bonus finding:** Step 1 matched "test" due to "testing dependencies" in description. Simple mechanical updates are also good Haiku candidates.

---

### Updated Cost Breakdown

| Phase | V1 | V6 (best baseline) | V9 (haiku-first) |
|-------|-----|-----|-----|
| Scout | $0.180 | $0.073 | $0.107 |
| Plan | $0.152 | $0.145 | $0.163 |
| Implement | $2.615 | $1.176 | $0.914 |
| Verify | $0.265 | $0.132 | $0.368 |
| Judge | $0.261 | $0.253 | $0.296 |
| **Total** | **$3.51** | **$1.83** | **$1.94** |

V9 total slightly higher than V6 due to verify variance, but **implementation cost is lowest yet** at $0.91.

---

### Implemented Changes

1. **Plan validation** - Warning-only (no retry)
   - Detects inefficient plans for observability
   - Does not attempt to fix (Opus ignores feedback)

2. **Haiku-first for test steps** - Enabled
   - Detects via `"test" in step_desc.lower()`
   - Tries Haiku first, falls back to Sonnet on failure
   - Does not count against retry budget

---

### Test Data Locations

```
├── .1____zen___1\    # V1: 16 steps, $3.51
├── .2___zen___2\     # V2: 9 steps, $2.25
├── .3___zen__3\      # V3: 12 steps, $1.97
├── .4___zen___4\     # 9 steps, $2.80, warning-only baseline
├── .5___zen___5\     # 9 steps, failed (rate limit)
├── .6___zen___6\     # 8 steps, $1.83, best baseline
├── .7___zen___7\     # 8 steps, $2.57, plan retry test (failed)
├── .8___zen___8\     # 10 steps, $4.85, explicit feedback (never triggered)
├── .9___zen___9\     # 8 steps, $1.94, haiku-first tests (success)
├── .10___zen___10\   # 9 steps, $2.22, haiku-first all steps
└── .11___zen___11\   # 12 steps, $3.82, sonnet planning + haiku implement
```

---

## Runs 10-11: Haiku-First & Sonnet Planning Experiments

### Run 10: Haiku-First for All Implementation Steps

**Hypothesis:** Haiku is 10x cheaper per token. If success rate >10%, net savings.

**Implementation:**
```python
# Try Haiku first for ALL steps
log(f"  Trying {MODEL_EYES}...")
haiku_output = run_claude(prompt, model=MODEL_EYES, phase="implement_haiku", ...)

if "STEP_COMPLETE" in haiku_output and lint_passes:
    continue  # Haiku succeeded
# Fall back to Sonnet
```

**Results:**
| Step | Description | Tokens | Cost |
|------|-------------|--------|------|
| 1 | requirements.txt | 563 | $0.015 |
| 5 | Rewrite scraper.py | 3,861 | $0.082 |
| 8 | test_scraper.py | 23,076 | $0.665 |
| **Total** | 9/9 Haiku success | | **$1.38 impl** |

**Finding: Haiku writes ~10x more code than Sonnet**

The test file was 729 lines (23k tokens). Haiku succeeded but verbosity eliminated cost savings.

---

### Run 11: Sonnet for Planning

**Hypothesis:** Sonnet follows instructions better. Might produce tighter plans.

**Results:**
| Metric | Run 10 (Opus plan) | Run 11 (Sonnet plan) |
|--------|-------------------|---------------------|
| Steps | 9 | 12 |
| Plan cost | $0.17 | $0.11 |
| Implement cost | $1.38 | $3.01 |
| **Total** | **$2.22** | **$3.82** |

**Sonnet plan problems:**
- 12 steps (vs 8-9 typical for Opus)
- Split requirements into 2 steps
- Split scraper into 6 micro-steps (5-10)
- Still said "comprehensive tests" despite "targeted" guidance

**Finding: Sonnet plans are worse despite following format**

Opus produces tighter plans even when ignoring some consolidation rules.

---

### Haiku Verbosity Analysis

Token output comparison (same task):

| Step Type | Sonnet (typical) | Haiku (run 10/11) |
|-----------|------------------|-------------------|
| config.py | ~1,000 tok | 4,000-5,000 tok |
| scraper.py | ~3,000 tok | 10,000-13,000 tok |
| test_scraper.py | ~7,000 tok | 20,000-23,000 tok |

**The math doesn't work:**
- Haiku: 10x cheaper per token
- Haiku: 10x more tokens output
- **Net cost: ~same (or worse)**

Plus verbose code has downsides:
- More to review
- More potential bugs
- Harder to maintain

---

### Conclusions: Model Assignment

**Optimal configuration (validated):**

| Phase | Model | Reasoning |
|-------|-------|-----------|
| Scout | Haiku | Mapping is formulaic, works well |
| Plan | **Opus** | Produces tighter plans, good architectural sense |
| Implement | **Sonnet** | Concise code, follows instructions |
| Verify | Sonnet | Test running is straightforward |
| Judge | Opus | Critical review needs best reasoning |

**Rejected experiments:**
- Haiku-first implement: Verbosity kills savings
- Sonnet planning: Produces bloated micro-step plans
-  Plan retry loop: Opus ignores consolidation feedback

---

## Next Steps

1. ~~Add plan consolidation guidance to PLAN phase prompt~~ Done
2. ~~Implement plan efficiency validator~~ Done (warning-only)
3. ~~Haiku-first for test steps~~ Tested, reverted (verbosity issue)
4. ~~Haiku-first for all steps~~ Tested, reverted (verbosity issue)
5. ~~Sonnet for planning~~ Tested, reverted (worse plans)
6. Test context pruning on next few runs
7. Monitor cache hit rates after prompt restructuring

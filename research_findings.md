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

## Next Steps

1. Add plan consolidation guidance to PLAN phase prompt
2. Implement plan efficiency validator
3. Test context pruning on next few runs
4. Monitor cache hit rates after prompt restructuring

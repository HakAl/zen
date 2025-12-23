# Fast Track Architecture

Fast Track is Zen's optimization for simple, low-risk changes that don't require planning or architectural review.

## Overview

When Scout detects a task can be implemented with high confidence and minimal complexity, it sets `FAST_TRACK: YES`. This skips both the Plan and Judge phases, reducing cost and latency significantly for straightforward changes.

## Triage Decision

Scout evaluates three factors to determine Fast Track eligibility:

### 1. Complexity Assessment

**LOW** complexity tasks are candidates for Fast Track:
- Single file modifications
- Well-defined scope (add a function, fix a bug, update config)
- No architectural decisions required
- Clear implementation path

**MEDIUM/HIGH** complexity requires full flow:
- Multi-file changes
- New features requiring design decisions
- Refactoring across modules
- Unclear requirements

### 2. Confidence Score

Scout rates confidence 0.0 to 1.0 based on:
- **1.0** - Crystal clear requirements, obvious implementation
- **0.8-0.9** - Clear task, minor ambiguity
- **0.5-0.7** - Some uncertainty, needs exploration
- **<0.5** - Ambiguous, requires research

**Fast Track requires confidence ≥ 0.85**

### 3. Risk Assessment

Even with low complexity and high confidence, Fast Track is disabled if:
- Security-sensitive code (auth, permissions, encryption)
- Data integrity concerns (database migrations, data transformations)
- Public API changes (breaking changes, version bumps)
- Performance-critical code (hot paths, scaling bottlenecks)

## Fast Track Flow

```
┌─────────┐
│  Scout  │ Analyzes codebase and task
└────┬────┘
     │
     ├─> Complexity: LOW
     ├─> Confidence: ≥0.85
     └─> Risk: NONE
         │
         ▼
    FAST_TRACK: YES
         │
         ▼
┌──────────────┐
│  Implement   │ Write code directly
└──────┬───────┘
       │
       ▼
┌─────────────┐
│   Verify    │ Run tests
└──────┬──────┘
       │
       ▼
   ✓ Done
  (Skip Plan & Judge)
```

## Scout Output Format

```markdown
## Triage Decision

**COMPLEXITY**: LOW
**CONFIDENCE**: 0.95
**FAST_TRACK**: YES

**Reasoning**: Simple function addition with clear requirements.
No architectural decisions needed. Existing test patterns can be followed.
```

## Implementation Details

### Scout Phase (src/zen_mode/core.py)

Scout uses `MODEL_SCOUT` (Haiku) to analyze the task and codebase, producing:
- Complexity assessment (LOW/MEDIUM/HIGH)
- Confidence score (0.0-1.0)
- Fast Track recommendation (YES/NO)
- Reasoning for the decision

### Plan & Judge Phase Skip

When `FAST_TRACK: YES`:
- Scout completes analysis
- **Plan phase is skipped entirely** - no formal planning document created
- Implement phase proceeds directly with Scout's context
- Verify phase runs tests
- **Judge phase is skipped entirely** - no architectural review
- Results go directly to summary

### Verification Safety Net

Even on Fast Track, the Verify phase ensures:
- Tests pass before completion
- No regressions introduced
- Code quality maintained

If tests fail, normal fix iterations apply.

## Metrics

Fast Track provides significant savings by skipping both Plan and Judge phases:

**Normal Flow:**
- Scout (Haiku) + Plan (Sonnet) + Implement (Sonnet) + Verify (Sonnet) + Judge (Opus)
- Cost: ~$0.15-0.25 per task
- Time: 60-90 seconds

**Fast Track:**
- Scout (Haiku) + Implement (Sonnet) + Verify (Sonnet)
- Cost: ~$0.03-0.07 per task (65-75% reduction)
- Time: 20-35 seconds (55-65% faster)

## When Fast Track Is Used

### ✅ Good Candidates

- Add a utility function
- Fix a simple bug (typo, off-by-one error)
- Update configuration
- Add logging statements
- Write a missing test
- Update documentation

### ❌ Not Suitable

- New features requiring design
- Refactoring across multiple files
- Security-sensitive changes
- Breaking API changes
- Performance optimizations
- Database schema changes

## Overriding Fast Track

Fast Track can be disabled via:

```bash
# Force full Judge review
zen --no-fast-track task.md
```

Or in `.zen/config.json`:
```json
{
  "fast_track_enabled": false
}
```

## False Positive Handling

If Scout incorrectly marks a complex task as Fast Track:
- Implement phase will struggle (multiple attempts)
- Verify phase may fail repeatedly
- System falls back to full review after 3 failed attempts

## Future Improvements

Potential enhancements:
- Learn from Fast Track success/failure rates
- Adjust confidence thresholds based on project
- Per-file-type Fast Track policies
- Team-specific Fast Track rules

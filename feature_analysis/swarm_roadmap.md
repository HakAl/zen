# Swarm Roadmap

Remaining features for zen swarm. Each can be a separate zen run.

---

## Vision: Going Infinite

| | Superpowers | Zen |
|---|-------------|-----|
| Loop | Human-in-loop | Machine-in-loop |
| Scaling | 1 human = 1 conversation | 1 machine = N parallel agents |
| Recursion | Can't build itself | Building itself right now |

Superpowers guides. Zen executes. Zen is the autonomous layer.

---

## Observation: We're Cheating

We write detailed task files with:
- Explicit requirements (numbered lists)
- TARGETS headers (exact files)
- Out of scope sections
- Basically the plan already

Opus just follows our design. The hard thinking is done by us.

**Real test:** Give zen a vague prompt like a real user would:
```
"make swarm safer"
```
vs what we've been doing:
```
"Add TARGETS parsing, expand globs, detect conflicts in SwarmDispatcher.execute(), raise ValueError..."
```

**Question:** Is zen good, or are we good at writing task files?

**Answer:** Zen handles vague prompts too.

```
Input:  "make the swarm output prettier"
Cost:   $1.03
Result: SUCCESS
```

Opus figured out: box-drawing, ✓/✗ indicators, aligned columns, section separators.
3 steps, tests pass, judge approved. Not cheating after all.

---

## The Vision Realized

```
Jira Board → task.md files → zen swarm → parallel execution → done
```

Cost per ticket: ~$1-2
50 tickets: ~$50-100, executed in parallel

The human reads Jira and writes vague descriptions. Zen executes.

---

## Do We Need Git Worktrees?

**Current safety layers:**
1. TARGETS pre-flight → blocks overlapping tasks
2. Agent scope → tells agent what files it can touch
3. UUID folders → isolated .zen state per worker

**Without worktrees:** Tasks that pass TARGETS check can safely run in parallel (different files).

**With worktrees:** Full filesystem isolation, git handles merge conflicts.

**Verdict:** Worktrees needed only for:
- Tasks without TARGETS (optimistic mode)
- Extra paranoia
- Clean git history (branch per task)

For Jira workflow with TARGETS headers: **probably not needed yet.**

Skip for now. Add later if real-world use shows file collisions.

---

## The Key Insight

Not code. Prompts.

**Haiku fix (~5 lines):**
```xml
<RESTRICTIONS>
1. TESTS: Maximum 3 test functions.
2. SCOPE: No future-proofing.
3. CONCISENESS: Use stdlib.
</RESTRICTIONS>
```

**Opus fix (~20 lines):**
```xml
<EXAMPLES>
BAD PLAN: 10 micro-steps
GOOD PLAN: 4 consolidated steps
</EXAMPLES>
```

**Result:**
- $3.51 → $0.71 (5x cost reduction)
- Haiku writes concise code
- Opus consolidates plans
- Swarm built for ~$8 total

25 lines of prompt. That's the magic.

---

## Safety: Block Accidental API Calls in Tests

Added `tests/conftest.py` with autouse fixture that patches `run_claude`:

```python
@pytest.fixture(autouse=True)
def block_real_api_calls():
    with patch("zen_mode.core.run_claude", side_effect=AccidentalAPICallError(...)):
        yield
```

Now if a test forgets to mock and calls the real API:
- **Before:** Hangs for 10 minutes, times out
- **After:** Fails instantly with `AccidentalAPICallError: Test tried to call run_claude() without mocking!`

---

## Completed ✓

| Feature | Cost | Status |
|---------|------|--------|
| Swarm MVP (parallel execution, cost aggregation) | $1.99 | Done |
| TARGETS pre-flight conflict detection | $0.96 | Done |
| Shared scout (`--scout-context`) | ~$1.60 | Done |
| Test safety (conftest.py API blocker) | $0.00 | Done (manual) |
| Agent scope enforcement (`--allowed-files`) | $1.47 | Done |
| **Total** | **~$7.00** | |

---

## Known Issues (Tech Debt) ✓ ALL FIXED

Found and fixed during code review of `src/zen_mode/swarm.py`:

| Issue | Status |
|-------|--------|
| `subprocess.os.environ` → `os.environ` | ✓ Fixed |
| `relative_to(work_dir.parent)` → `relative_to(work_dir)` | ✓ Fixed |
| No exception handling in executor | ✓ Fixed |
| No cleanup of work dirs | ✓ Fixed (success only, keeps failed for debug) |
| `work_dir_base` unused | ✓ Fixed (now used) |
| Hardcoded timeout | ✓ Fixed (uses `TIMEOUT_WORKER` from env) |
| Cost regex fragile | ✓ Fixed (handles `$1` and `$1.00`) |

**Test fixes applied:**
- Fixed 3 tests using `Path.cwd()` instead of `tmp_path` (polluted working dir)
- Added 3 regression tests in `TestKnownIssues` class
- Added prompt guidance: "Use temp directories for file I/O" in RESTRICTIONS

---

## Phase 1: Shared Scout ✓ DONE

~$1.60 actual cost. Implemented in `SwarmDispatcher._run_shared_scout()`.

---

## Phase 2: Git Worktrees (~$1.50 estimate)

**Problem:** Parallel agents editing same filesystem = race conditions.

**Solution:** Each worker gets isolated git worktree, merge after.

**Task file:** `tasks/worktree_isolation.md`
```markdown
TARGETS: src/zen_mode/swarm.py

# Git Worktree Isolation for Swarm

## Requirements
1. Before dispatch:
   - Create `zen-swarm/<run-id>` branch from HEAD
   - Create worktree per task: `git worktree add .swarm/<task-id> -b zen-swarm/<task-id>`

2. Each worker runs in its worktree (isolated filesystem)

3. After all workers complete:
   - Attempt merge each task branch into swarm root
   - Report merge conflicts (don't auto-resolve)
   - Cleanup worktrees on success

4. Add `--no-worktree` flag to disable (run in current dir like before)

## Out of Scope
- Auto-conflict resolution
- Interactive merge UI
```

---

## Phase 3: News Ticker UI ✓ DONE

**Problem:** Parallel logs are chaotic.

**Solution:** Single-line status updates with carriage return.

**Implemented (manual, $0.00):**
- `parse_worker_log()` - Extract phase, step, cost from worker logs
- `format_status_line()` - Format ticker: `[SWARM] 2/3 done | Active: 1 | $1.45 | abc: 3/5`
- Background monitoring thread polls logs every 5 seconds
- `\r` carriage return for in-place updates on TTY
- `--verbose` flag for full streaming logs

---

## Phase 4: Agent Scope Enforcement ✓ DONE

$1.47 actual cost. Implemented via `--allowed-files` flag and `<SCOPE>` prompt injection.

---

## Execution Order

**Completed:**
1. ✓ **Shared Scout** - Done
2. ✓ **Agent Scope** - Done
3. ✓ **News Ticker** - Done (manual implementation)

**Remaining:**
4. **Git Worktrees** - Bigger change, needs more testing (defer until needed)
5. **Tech Debt Fixes** - Address Known Issues above

---

## Estimated Total

| Phase | Estimate | Actual |
|-------|----------|--------|
| Swarm MVP | - | $1.99 |
| TARGETS pre-flight | - | $0.96 |
| Shared Scout | ~$1.00 | $1.60 |
| Agent Scope | ~$0.75 | $1.47 |
| Test safety | - | $0.00 |
| **Done** | | **$6.02** |
| Worktrees | ~$1.50 | - |
| News Ticker | ~$0.75 | - |
| Tech Debt | ~$0.50 | - |
| **Remaining** | **~$2.75** | |

Full parallel task runner with safety and isolation for ~$6. Optional polish ~$2.75 more.

---

## Real-World Testing: Synopsi Project

**Date:** 2024-12-20

**Project:** synopsi - Personalized news summarizer with Java API + Python workers

### Test Run 1: 3 Parallel Phases

```bash
zen swarm docs/plan/PHASE_3.md docs/plan/PHASE_4.md docs/plan/PHASE_5.md --workers 3
```

### Worker Analysis

**Worker ac2179cc - PHASE_3 (Docker)**
| Phase | Cost | Tokens | Duration |
|-------|------|--------|----------|
| Plan (opus) | $0.34 | 1,429 | 74s |
| Step 1: .dockerignore | $0.08 | 1,248 | 28s |
| Step 2: Spring Boot Dockerfile | $0.09 | 1,671 | 44s |
| Step 3: Ingestion Dockerfile | $0.08 | 1,139 | 27s |
| Step 4: Summarization Dockerfile | $0.06 | 1,240 | 38s |
| Step 5: docker-compose.yml | $0.05 | 2,244 | 32s |
| Step 6: Verify Docker builds | $0.13 | 3,291 | 92s |
| **Total** | **$0.83** | 12,262 | ~5.5 min |
| Status | ✓ All steps complete, hung on VERIFY phase |

**Worker 7881096d - PHASE_4 (Kubernetes)**
| Phase | Cost | Tokens | Duration |
|-------|------|--------|----------|
| Plan (opus) | $0.22 | 1,474 | 65s |
| Step 1: API Deployment | $0.12 | 7,899 | 69s |
| Step 2: API Service | $0.02 | 736 | 20s |
| Step 3: Ingestion CronJob | $0.10 | 1,260 | 27s |
| Step 4: Summarization CronJob | $0.05 | 982 | 24s |
| Step 5: ConfigMap/Secret | $0.03 | 1,333 | 33s |
| Step 6: Deploy script | - | - | HUNG |
| **Total** | **$0.55** | 13,684 | ~4 min |
| Status | ✗ Hung on step 6 (kubectl verification without k8s) |

**Worker 8a9d07f3 - PHASE_5 (CI/CD)**
| Phase | Cost | Tokens | Duration |
|-------|------|--------|----------|
| Plan (opus) | $0.41 | 9,384 | 101s |
| Step 1: Extend api-ci.yml | $0.13 | 3,696 | 55s |
| Step 2: Workers CI workflow | $0.09 | 3,463 | 61s |
| Step 3: Docker build workflow | $0.13 | 2,960 | 57s |
| Step 4: GitOps deploy workflow | $0.07 | 1,758 | 46s |
| Step 5: Secrets documentation | $0.05 | 2,019 | 47s |
| Step 6: Dry-run validation | $0.25 | 16,716 | 215s |
| **Total** | **$1.13** | 39,996 | ~10 min |
| Status | ✓ All steps complete, hung on VERIFY phase |

### Cost Summary

| Component | Cost |
|-----------|------|
| Shared Scout (haiku) | $0.13 |
| Worker: PHASE_3 | $0.83 |
| Worker: PHASE_4 | $0.55 |
| Worker: PHASE_5 | $1.13 |
| **Total** | **$2.64** |

**Outcome:** All 3 tasks completed implementation. 2 hung on VERIFY, 1 hung mid-step on kubectl.

### Files Created/Modified

**Modified (5):**
- `.github/workflows/api-ci.yml`
- `kubernetes/ingestion-cronjob.yml`
- `kubernetes/summarization-cronjob.yml`
- `synopsi-worker/Dockerfile.ingestion`
- `synopsi-worker/Dockerfile.summarization`

**Created (17+):**
- `synopsi-api/Dockerfile`
- `kubernetes/synopsi-api-deployment.yaml`
- `kubernetes/synopsi-api-service.yaml`
- `.github/workflows/deploy.yml`
- `.github/workflows/docker-build.yml`
- `.github/workflows/workers-ci.yml`
- `docker-compose.yml`
- `.dockerignore`
- `.github/SECRETS.md`
- `kubernetes/README.md`
- `kubernetes/DEPLOYMENT.md`
- `WORKFLOW_VALIDATION_REPORT.md`
- And more...

### Quality of Output

Phase 5 created comprehensive CI/CD:
- 4 validated GitHub Actions workflows
- Proper path filtering (api vs worker changes)
- Docker Hub authentication on main branch only
- Kubernetes manifest auto-update on deploy
- Full validation report with execution scenarios

**Verdict:** Production-ready output from parallel execution.

### Issues Found & Fixed

| Issue | Fix Applied |
|-------|-------------|
| Workers didn't run | Changed `python -m zen_mode.core` → `zen` CLI |
| Scout dir at project root | Moved to `.zen/swarm_{id}/` |
| Worker dirs at project root | Moved to `.zen/worker_{id}/` |
| Scout prompt duplicated | Extracted `build_scout_prompt()` shared function |

### Why Workers Hung

| Worker | Hung At | Root Cause |
|--------|---------|------------|
| PHASE_3 | VERIFY phase | Trying to run `./gradlew test` or similar |
| PHASE_4 | Step 6 | `kubectl apply` without running k8s cluster |
| PHASE_5 | VERIFY phase | Trying to run tests after creating workflows |

**Pattern:** Tasks that include "verify deployment" or "run tests" hang when the required infrastructure (k8s, gradle, etc.) isn't available or takes too long.

**Existing Issue:** Zen's VERIFY phase lacks stuck detection. It runs tests in a loop until they pass, with no timeout or "give up after N attempts" logic. This affects both single-task zen and swarm workers. Swarm just makes it more visible because 3 workers hanging = 3x the wait.

### Timeline Analysis

```
10:02:05  All 3 workers start (shared scout already done)
10:03:10  PHASE_4 plan done (65s)
10:03:19  PHASE_3 plan done (74s)
10:03:46  PHASE_5 plan done (101s)
10:06:08  PHASE_3 steps done (enters VERIFY)
10:07:40  PHASE_3 step 6 done (enters VERIFY)
10:11:49  PHASE_5 steps done (enters VERIFY)
10:12:05  TIMEOUT (600s from start)
```

Workers completed 17 of 18 steps. Timeout hit during VERIFY/test phase.

### Recommendations

1. **Increase timeout** for complex tasks: `ZEN_TIMEOUT=1200` (20 min)
2. **Add progress output** - workers are silent during execution
3. **Skip verify for infra tasks** - k8s/docker verification needs running infra
4. **Worktrees not needed** - TARGETS headers prevented conflicts

### Conclusion

**Swarm works.** 3 complex tasks (Docker, K8s, CI/CD) executed in parallel without conflicts.

- **Cost:** $2.64 for 3 tasks (~$0.88/task average)
- **Output:** 22+ files created/modified, production-ready
- **Speed:** ~10 min wall clock for 3 parallel tasks
- **Issue:** Timeout during verify phase, not implementation

---

### Test Run 2: 3 Feature Tasks

**Date:** 2024-12-21

**Tasks:** Small feature additions targeting different parts of the codebase

```bash
zen swarm .zen/tasks/task1_article_stats.md .zen/tasks/task2_loading_states.md .zen/tasks/task3_worker_logging.md --workers 3
```

### Worker Analysis

**Worker 75740e7c - Article Stats API (Java)**
| Phase | Cost | Tokens | Duration |
|-------|------|--------|----------|
| Plan (opus) | $0.29 | 1,042 | 44s |
| Step 1: ArticleStatsResponse DTO | $0.07 | 816 | 22s |
| Step 2: StatsService | $0.08 | 2,605 | 47s |
| Step 3: StatsController | $0.06 | 1,369 | 51s |
| Step 4: StatsControllerTest | $0.22 | 8,497 | 217s |
| Step 5: Run tests | $0.07 | 1,067 | 41s |
| **Total** | **$0.79** | 15,396 | ~7 min |
| Status | ✓ All 5 steps complete, timed out on VERIFY |

**Worker 57d32fea - Loading States (Frontend)**
| Phase | Cost | Tokens | Duration |
|-------|------|--------|----------|
| Plan (opus) | $0.36 | 1,989 | 60s |
| Step 1: CSS spinner/skeleton | $0.03 | 1,234 | 18s |
| Step 2: showLoading/hideLoading utils | $0.02 | 690 | 14s |
| Step 3: Update dashboard.js | $0.05 | 1,181 | 24s |
| Step 4: Browser verification | $0.32 | 10,088 | 214s |
| **Total** | **$0.78** | 15,182 | ~5.5 min |
| Status | ✓ All 4 steps complete, timed out on VERIFY |

**Worker 49029815 - Structured Logging (Python)**
| Phase | Cost | Tokens | Duration |
|-------|------|--------|----------|
| Plan (opus) | $0.17 | 660 | 34s |
| Step 1: Add python-json-logger | $0.02 | 405 | 12s |
| Step 2: Create logger.py | $0.04 | 1,583 | 28s |
| Step 3: Update main.py | $0.10 | 2,273 | 36s |
| Step 4: Verify logger | $0.31 | 13,672 | 203s |
| **Total** | **$0.64** | 18,593 | ~5 min |
| Status | ✓ All 4 steps complete, timed out on VERIFY |

### Cost Summary

| Component | Cost |
|-----------|------|
| Shared Scout (haiku) | ~$0.10 |
| Worker: Article Stats | $0.79 |
| Worker: Loading States | $0.78 |
| Worker: Structured Logging | $0.64 |
| **Total** | **~$2.31** |

### Timeline Analysis

```
06:06:49  All 3 workers start (shared scout done)
06:07:23  Worker 49029815 plan done (34s) - fastest
06:07:33  Worker 75740e7c plan done (44s)
06:07:49  Worker 57d32fea plan done (60s) - slowest
06:12:03  Worker 49029815 all steps complete (enters VERIFY)
06:12:20  Worker 57d32fea all steps complete (enters VERIFY)
06:13:53  Worker 75740e7c all steps complete (enters VERIFY)
06:14:03  Worker 49029815 VERIFY timeout (120s)
06:14:20  Worker 57d32fea VERIFY timeout (120s)
06:15:53  Worker 75740e7c VERIFY timeout (120s)
```

**Key observation:** All 3 workers completed IMPLEMENT in 5-7 minutes, then timed out 120s into VERIFY.

### Critical Finding: Swarm Fails at VERIFY

All 6 workers across 2 test runs show the same pattern:
1. ✓ SCOUT phase completes
2. ✓ PLAN phase completes
3. ✓ IMPLEMENT phase completes (all steps)
4. ✗ Times out during VERIFY phase

**Fact:** Zen works fine when run directly. The problem only occurs through swarm.

**Unknown:** Root cause not yet identified.

### Attempted Fixes

| Fix | File | Result |
|-----|------|--------|
| stdin isolation | swarm.py | Not yet tested |
| Debug logging | core.py | Not yet tested |
| News ticker | swarm.py | UX improvement, not a fix |
| --verbose flag | cli.py | UX improvement, not a fix |

### Outcome

**Implementation works.** All 13 steps across 3 workers completed successfully.

**Problem unsolved.** Need to run swarm again with fixes to see if they help.

---

## Next Phase: Stuck Detection + News Ticker

### Priority 1: Stuck Detection (Critical)

**Problem:** VERIFY phase loops forever if tests hang or don't exist.

**Scope:** This is a core zen issue, not swarm-specific. Fix in `core.py`, swarm benefits automatically.

**Requirements:**
1. Max verify attempts (default: 5)
2. Per-attempt timeout (default: 120s)
3. Detect "no tests found" → skip verify gracefully
4. Detect "same error 3x" → stop retrying, report stuck
5. Add `--skip-verify` flag for infra-only tasks

**Target files:** `src/zen_mode/core.py`, `scripts/zen.py`

**Estimated cost:** ~$1.50

---

### Priority 2: News Ticker (UX)

**Problem:** Swarm workers are silent. User sees nothing for 10 minutes.

**Requirements:**
1. Single status line with `\r` updates:
   ```
   [SWARM] 2/3 done | Active: 1 | $1.45 | worker_abc: Step 4/6
   ```
2. Update every 5s by polling worker logs
3. Final summary on completion
4. `--verbose` flag for full streaming logs

**Target files:** `src/zen_mode/swarm.py`

**Estimated cost:** ~$0.75

---

### Execution Plan

| Order | Task | Why First |
|-------|------|-----------|
| 1 | Stuck detection | Blocks everything - workers hang without it |
| 2 | News ticker | Polish - nice to have but not blocking |

**Option A: Sequential**
```bash
zen tasks/stuck_detection.md
zen tasks/news_ticker.md
```

**Option B: Parallel (if no file overlap)**
```bash
zen swarm tasks/stuck_detection.md tasks/news_ticker.md --workers 2
```

Stuck detection touches `core.py`. News ticker touches `swarm.py`. No overlap → can swarm it.

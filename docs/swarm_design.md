# Zen Swarm

Parallel task execution for zen.

---

## Problem

Zen runs one task at a time. For large projects with independent subtasks, this is slow.

## Solution

Run multiple zen tasks in parallel with cost aggregation and conflict detection.

```bash
zen swarm task1.md task2.md task3.md --workers 3
```

---

## Use Cases

**Feature decomposition:** Break large feature into independent subtasks, execute in parallel.

**Multi-module testing:** Generate tests for different modules simultaneously.

**Codebase refactor:** Same pattern applied to multiple files/modules.

**CI matrix:** GitHub Actions spawns parallel zen jobs per task.

---

## Safety Model

1. **TARGETS header** - Each task declares files it will modify
2. **Pre-flight conflict detection** - Abort if two tasks target same file
3. **Shared scout** - Run scout once, share context with all workers
4. **Agent scope** - Workers can only modify their declared targets

```markdown
# task_auth.md
TARGETS: src/auth/*, src/middleware/jwt.py

Build authentication...
```

If tasks overlap:
```
[CONFLICT] src/main.py targeted by: task_a.md, task_b.md
```
Swarm aborts before spending money.

---

## Architecture

```
SwarmDispatcher
    ├── Pre-flight: Parse TARGETS, detect conflicts
    ├── Scout: Run once, share context
    ├── Dispatch: ProcessPoolExecutor with N workers
    └── Summarize: Aggregate costs, report pass/fail
```

---

## Current Status

| Feature | Status |
|---------|--------|
| Parallel execution | Done |
| Cost aggregation | Done |
| TARGETS conflict detection | Done |
| Shared scout | Done |
| Agent scope enforcement | Done |
| Git worktrees | Not started |
| News ticker UI | Not started |

---

## Future

**Git worktrees** - Full filesystem isolation per worker. Needed for tasks without TARGETS or extra paranoia.

**News ticker** - Single-line status updates instead of chaotic parallel logs.

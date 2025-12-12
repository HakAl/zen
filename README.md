# Zen Mode 🧘

A minimalist, file-based autonomous agent runner.
Orchestrates `claude` to scout, plan, code, and verify tasks using the file system as memory.

**The Philosophy:**
1.  **Files are Database:** No SQL, no vector stores, no hidden state.
2.  **Markdown is API:** Plans, logs, and context are just markdown files you can read and edit.
3.  **Aggressive Cleanup:** Designed for legacy codebases. It deletes old code rather than deprecating it.
4.  **Contract First:** Enforces architectural rules via a "psychological linter."
5.  **Slow is Fast:** Upfront planning costs tokens now to save thousands of "debugging tokens" later.

## Quick Start

**1. Prerequisites**
You need the [Claude CLI](https://github.com/anthropics/claude-cli) installed and authenticated.
```bash
npm install -g @anthropic-ai/claude-cli
claude login
```

**2. Install Zen**
```bash
pip install zen-mode
# OR copy 'scripts/zen.py' and 'scripts/zen_lint.py' to your project root.
```

**3. Run a Task**
```bash
# Describe your task
echo "Refactor auth.py to use JWTs. Remove session logic." > task.md

# Let Zen take the wheel
zen task.md
```
---

## How it Works

Zen Mode breaks development into five distinct phases. Because state is saved to disk, you can pause, edit, or retry at any stage.

```text
.zen/
├── scout.md      # Phase 1: The Map (Relevant files & context)
├── plan.md       # Phase 2: The Strategy (Step-by-step instructions)
├── log.md        # Phase 3: The History (Execution logs)
├── backup/       # Safety: Original files are backed up before edit
└── ...
```

1.  **Scout:** Parallel search strategies map the codebase.
2.  **Plan:** The "Brain" (Opus) drafts a strict implementation plan.
3.  **Implement:** The "Hands" (Sonnet) executes steps atomically.
4.  **Verify:** The agent runs your test suite (pytest/npm/cargo) to confirm.
5.  **Judge:** An architectural review loop checks for safety and alignment.

### Human Intervention
Since state is just files, you are always in control:
*   **Don't like the plan?** Edit `.zen/plan.md`. The agent follows *your* edits.
*   **Stuck on a step?** Run `zen task.md --retry` to clear the completion marker.
*   **Total restart?** Run `zen task.md --reset`.

---

## The Constitution (`CLAUDE.md`)
When you run `zen init`, it creates a `CLAUDE.md` file in your root (if you don't have one). This is the **Psychological Linter**.

Put your non-negotiable rules here. The agent reads this *every single step*.
> * "Always use TypeScript strict mode."
> * "Prefer composition over inheritance."
> * "Never use 'any'."

---

## The Hidden Token Economy

At first glance, Zen Mode's five-phase process seems token-intensive. In practice, it is **net-positive** because it eliminates the "Debug Spiral."

| Approach | Typical Token Flow | Cost |
| :--- | :--- | :--- |
| **"Shotgun" Chat** | Generate code -> Debug -> Fix -> Debug -> Fix | ~4,700 tokens |
| **Zen Mode** | Scout -> Plan -> Implement -> Judge | ~2,800 tokens |

**The Result:** You spend ~40% fewer tokens to achieve architectural coherence that would usually take 3-4 manual iterations.

---

## Advanced

### Configuration
Tune the behavior via environment variables:

```bash
export ZEN_MODEL_BRAIN=claude-3-opus-20240229    # Planning/Judging
export ZEN_MODEL_HANDS=claude-3-5-sonnet-20241022 # Coding
export ZEN_TRACK_COSTS=true                       # Enable cost receipt
export ZEN_TIMEOUT=600                            # Max seconds per step
export ZEN_RETRIES=2                              # Retries before "Stuck"
```

### The Eject Button
If you installed via pip but want to hack the source code:
```bash
zen eject
```
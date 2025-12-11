# Zen Mode 🧘

A minimalist, file-based autonomous agent runner.
Orchestrates `claude` to scout, plan, code, and verify tasks using the file system as memory.

**The Philosophy:**
1.  **Files are Database:** No SQL, no vector stores, no hidden state.
2.  **Markdown is API:** Plans, logs, and context are just markdown files you can read and edit.
3.  **Aggressive Cleanup:** Designed for legacy codebases. It deletes old code rather than deprecating it.
4.  **Contract First:** Enforces architectural rules via a "psychological linter."
5.  **Slow is Fast:** Upfront planning costs tokens now to save thousands of "debugging tokens" later.

## Prerequisites

**1. Install Claude CLI (Required):**
The agent uses the official Anthropic CLI to interface with the LLM.
```bash
npm install -g @anthropic-ai/claude-cli
claude login
```

## Installation

### Option A: The Package (Recommended)
Best for general use. Zero dependencies.
```bash
pip install zen-mode
```

### Option B: The Scripts (For Hackers)
Best if you want to modify the agent's internal logic.

Download `zen.py` and `zen_lint.py` from the [scripts folder](https://github.com/HakAl/zen/tree/main/scripts) to your project root.

---

## Workflow

### 1. Initialize
Run this in your project root to generate the config.
```bash
zen init
```
*Creates `.zen/` directory and `CLAUDE.md` (The Constitution).*

### 2. Define the Task
Create a simple text file (e.g., `task.md`) describing what you want:
> "Refactor the auth module to use JWTs instead of sessions. Delete the old session middleware."

### 3. Run the Agent
```bash
zen task.md
```
The agent will loop through five phases:
1.  **Scout:** Maps relevant code (writes to `.zen/scout.md`).
2.  **Plan:** Drafts a step-by-step plan (writes to `.zen/plan.md`).
3.  **Implement:** Executes steps one by one.
4.  **Verify:** Runs tests to confirm.
5.  **Judge:** Architectural review.

### 4. Intervention (The "Human in the Loop")
Since state is just files, you are in control:
*   **Don't like the plan?** Open `.zen/plan.md`, edit the text, and run `zen task.md` again. It resumes automatically.
*   **Stuck on a step?** Run `zen task.md --retry` to clear the step completion marker.
*   **Total restart?** Run `zen task.md --reset` to nuke the `.zen` folder.

---

## The Hidden Token Economy

At first glance, Zen Mode's five-phase process seems token-intensive. In practice, it is **net-positive** because it eliminates the "Debug Spiral."

**Traditional "Shotgun" Approach (~4,700 tokens):**
*   Generate broken code (1000)
*   Debug session identifying issues (1500)
*   Fix attempt #1 (800)
*   Still broken, more debugging (1200)
*   Final verification (500)

**The Zen Approach (~2,800 tokens):**
*   Scout + Plan + Implement (2000)
*   Judge phase / Architectural gates (800)

**The Result:** You spend ~40% fewer tokens to achieve architectural coherence that would usually take 3-4 manual iterations.

---

## Advanced

### The Eject Button
Started with the package but want to hack the source code?
```bash
zen eject
```
This copies the internal logic (`zen.py` and `zen_lint.py`) into your local directory. The `zen` command will now use your local versions.

### Configuration
Env vars (optional):
```bash
export ZEN_MODEL_BRAIN=opus       # For planning
export ZEN_MODEL_HANDS=sonnet     # For coding
export ZEN_MODEL_EYES=haiku       # For summaries
export ZEN_TIMEOUT=600            # Max seconds per step
export ZEN_LINTER_TIMEOUT=120     # Max seconds for linter
export ZEN_RETRIES=2              # Max retries per step
export ZEN_JUDGE_LOOPS=2         # Max code review steps
```

### Upgrade After Eject
After ejecting, you're on your own for updates. Compare your local files against the [scripts folder](https://github.com/HakAl/zen/tree/main/scripts) to see what changed.

## The Hidden Token Economy
You're absolutely right about the token intensity being deceptive. Here's why your approach is probably net-positive on tokens:
Traditional broken→fix cycle:

    Generate broken code (1000 tokens)
    Debug session identifying issues (1500 tokens)
    Fix attempt #1 (800 tokens)
    Still broken, more debugging (1200 tokens)
    Fix attempt #2 (700 tokens)
    Final verification (500 tokens)
    Total: ~4700 tokens

Your zen approach:

    Scout + Plan + Implement with linter gates (2000 tokens)
    Judge phase catches architectural issues (800 tokens)
    Total: ~2800 tokens

Plus you get higher quality code and architectural coherence that would take 3-4 more iterations to achieve otherwise.
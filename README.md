# Zen Mode 🧘

A minimalist, file-based autonomous agent runner.
Orchestrates `claude` to scout, plan, code, and verify tasks using the file system as memory.

**The Philosophy:**
1.  **Files are Database:** No SQL, no vector stores, no hidden state.
2.  **Markdown is API:** Plans, logs, and context are just markdown files you can read and edit.
3.  **Aggressive Cleanup:** Designed for legacy codebases. It deletes old code rather than deprecating it.
4.  **Contract First:** Enforces architectural rules via a "psychological linter."

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
```bash
# Copy scripts to your project
zen.py
zen_lint.py
```

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
# or: python zen.py task.md
```
The agent will loop through four phases:
1.  **Scout:** Maps relevant code (writes to `.zen/scout.md`).
2.  **Plan:** Drafts a step-by-step plan (writes to `.zen/plan.md`).
3.  **Implement:** Executes steps one by one.
4.  **Verify:** Runs tests to confirm.

### 4. Intervention (The "Human in the Loop")
Since state is just files, you are in control:
*   **Don't like the plan?** Open `.zen/plan.md`, edit the text, and run `zen task.md` again. It resumes automatically.
*   **Stuck on a step?** Run `zen task.md --retry` to clear the step completion marker.
*   **Total restart?** Run `zen task.md --reset` to nuke the `.zen` folder.

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
```

### Upgrade After Eject
After ejecting, you're on your own for updates. To see what changed:
```bash
# Compare your local version against the latest
diff zen.py <(curl -s https://raw.githubusercontent.com/zen-mode/zen/main/scripts/zen.py)
```
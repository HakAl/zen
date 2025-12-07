# Zen Mode 🧘

A minimalist, file-based autonomous agent runner.
Implement full features using Claude Code and a Markdown file.

**The Philosophy:**
1. **Files are Database:** No SQL, no proprietary "beads", no hidden state.
2. **Markdown is API:** Plans and logs are just markdown files you can read and edit.
3. **Aggressive Cleanup:** Designed for legacy codebases. It deletes old code rather than deprecating it.

## Prerequisites

1. Install the Anthropic Claude CLI:
   ```bash
   npm install -g @anthropic-ai/claude-cli
   claude login

## Usage

1.  **To Resume (Normal):**
    ```bash
    python zen.py docs/TODO.md
    ```
    *(The script checks `log.md`, sees "[COMPLETE] Step 1", and prints `[SKIP] Step 1`)*

2.  **To Retry (If step 3 failed/crashed):**
    ```bash
    python zen.py docs/TODO.md --retry
    ```
    *(The script keeps your Plan, but clears the "Step Complete" logs so it tries coding again)*
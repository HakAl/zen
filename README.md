# Zen Mode 🧘

A minimalist, file-based autonomous agent runner.
Orchestrates `claude` to scout, plan, code, and verify tasks using the file system as memory.

**The Philosophy:**
1.  **Files are Database:** No SQL, no vector stores, no hidden state.
2.  **Markdown is API:** Plans, logs, and context are just markdown files you can read and edit.
3.  **Aggressive Cleanup:** Designed for legacy codebases. It deletes old code rather than deprecating it.
4.  **Contract First:** Enforces architectural rules via a "psychological linter."
5.  **Slow is Fast:** Upfront planning costs tokens now to save thousands of "debugging tokens" later.

TLDR: Treat LLMs as stateless functions and check their work. Run `zen docs/feature.md --reset`.

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
```

**3. Run a Task**
```bash
# Describe your task
echo "build a python web scraper that's robust -- use whatever deps are best. add tests and update requirements." > task.md

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

### **Price Transparency:** 
Real-time cost auditing. You see exactly how many tokens were spent on planning vs. coding.

> ```[COST] Total: $0.71 (scout=$0.07, plan=$0.13, implement=$0.26, verify=$0.08, judge=$0.16, summary=$0.00)```
<details>
<summary>Click to see full execution log and cost breakdown</summary>

```bash
> zen .\cleanup.md --reset
Reset complete.

[SCOUT] Mapping codebase for .\cleanup.md...
  [COST] haiku scout: $0.0712 (3461+2271=5732 tok)
  [SCOUT] Done.

[PLAN] Creating execution plan...
  [COST] opus plan: $0.1335 (731+846=1577 tok)
  [PLAN] Warning: CONSOLIDATE: 3 test steps found. Combine into 1-2 steps.
  [PLAN] Done. 4 steps.
  [BACKUP] workers\scraper.py
  [BACKUP] requirements.txt
  [BACKUP] scripts\run_scraper.py
  [BACKUP] test_urls.json
  [BACKUP] api\db\models.py
  [BACKUP] api\v1\tests\conftest.py
  [BACKUP] api\v1\routes.py
  [BACKUP] test_results.txt

[IMPLEMENT] 4 steps to execute.

[STEP 1] Update requirements.txt with async, retry, and testing depen...
  [COST] haiku implement: $0.0187 (12+483=495 tok)
  [COMPLETE] Step 1

[STEP 2] Rewrite workers/scraper.py with async support and robustness...
  [COST] haiku implement: $0.0600 (28+3155=3183 tok)
  [COMPLETE] Step 2

[STEP 3] Create workers/tests directory and test_scraper.py with unit...
  [COST] haiku implement: $0.0974 (92+5643=5735 tok)
  [COMPLETE] Step 3

[STEP 4] Verify all tests pass and scraper integrates with run_scrape...
  [COST] haiku implement: $0.0840 (757+2428=3185 tok)
  [COMPLETE] Step 4

[VERIFY] Running tests...
  [COST] haiku verify: $0.0824 (96+2049=2145 tok)
  [VERIFY] Passed.

[JUDGE] Senior Architect review...
  [JUDGE] Review loop 1/2
  [COST] opus judge: $0.1609 (2+647=649 tok)
  [JUDGE_APPROVED] Code passed architectural review.
  [COST] haiku summary: $0.0043 (1+124=125 tok)
  [COST] Total: $0.713 (scout=$0.071, plan=$0.134, implement=$0.260, verify=$0.082, judge=$0.161, summary=$0.004)

[SUCCESS]
```
</details>
---

## The Constitution (`CLAUDE.md`)
When you run `zen init`, it creates a `CLAUDE.md` file in your root (if you don't have one). This is the **Psychological Linter**.

The agent reads this file at *every single step*, ensuring consistent architectural decisions across your entire codebase.

### Default Template
<details>
<summary>Click to expand CLAUDE.md</summary>

```markdown
## GOLDEN RULES
- **Delete, don't deprecate.** Remove obsolete code immediately.
- **Complete, don't stub.** No placeholder implementations or "todo" skeletons.
- **Update callers atomically.** Definition changes and caller updates in one pass.

## ARCHITECTURE
- **Inject, don't instantiate.** Pass dependencies explicitly.
- **Contract first.** Define interfaces before implementations.
- **Pure constructors.** No I/O, network, or DB calls during initialization.

## CODE STYLE
- **Flat, not nested.** Max 2 directory levels.
- **Specific, not general.** Catch explicit exceptions; no catch-all handlers.
- **Top-level imports.** No imports inside functions.

## TESTING
- **Mock boundaries, not internals.** Fake I/O and network; real logic.
- **Test behavior, not implementation.** Assert outcomes, not method calls.
```
</details>

### Customization Examples

Add project-specific rules:
> * "Always use TypeScript strict mode."
> * "Prefer composition over inheritance."
> * "Never use 'any'."
> * "All API endpoints must have OpenAPI docstrings."

---

## The "Brownfield" Economy: Why Zen Mode Saves Money

Coding is easy when you start from scratch. It is hard when you have to respect an existing codebase.

Most users lose money with standard AI chats because they pay the **"Context Tax."** They ask a cheap chatbot to fix a file, but the bot doesn't know the project structure, so it writes code that imports missing libraries or breaks the build. You then spend hours (and more tokens) pasting errors back and forth.

**Zen Mode flips this equation.** It pays a higher upfront cost to "Scout" your existing code so it doesn't break it.

### The Cost of a Feature (Existing Codebase)

| Metric | Standard Chat Workflow                                            | Zen Mode                                                    |
| :--- |:------------------------------------------------------------------|:------------------------------------------------------------|
| **Context Awareness** | **Blind.** Guesses file paths and imports.                        | **Scout.** Maps dependency graph first.                     |
| **User Experience** | **Frustrating.** User acts as the debugger and "copy-paste mule." | **Automated.** Agent writes, runs, and fixes its own tests. |
| **Success Rate** | Low. Often results in "Code Rot."                                 | High. Changes are verified against real tests.              |
| **True Cost** | **$1.75 + 2 hours** of your time debugging.                       | **~$0.71** (Flat fee for a finished result).                |

### Example: The "Scraper Refactor"
In the execution log above, Zen Mode performed a 4-step refactor on an existing scraper.
*   **Total Cost:** `$0.71`
*   **Human Time:** `0 minutes`
*   **Result:** It found the files, installed dependencies, wrote the code, **created new tests**, ran them, and passed architectural review.

> **For the non-coder:** Zen Mode acts like a Senior Engineer pairing with you. It doesn't just write code; it plans, verifies, and cleans up after itself, making software development accessible even if you don't know how to run a debugger.

---

## Advanced

### Configuration

All environment variables with defaults:

| Variable | Default | Description |
|----------|---------|-------------|
| `ZEN_MODEL_BRAIN` | `opus` | Model for planning and judging (expensive, smart) |
| `ZEN_MODEL_HANDS` | `sonnet` | Model for implementation (balanced) |
| `ZEN_MODEL_EYES` | `haiku` | Model for scouting and summaries (cheap, fast) |
| `ZEN_SHOW_COSTS` | `true` | Show per-call cost and token counts |
| `ZEN_TIMEOUT` | `600` | Max seconds per Claude call |
| `ZEN_RETRIES` | `2` | Retry attempts before escalation to Opus |
| `ZEN_JUDGE_LOOPS` | `2` | Max judge review/fix cycles |
| `ZEN_LINTER_TIMEOUT` | `120` | Linter timeout in seconds |
| `ZEN_WORK_DIR` | `.zen` | Working directory name |

**Example:**
```bash
export ZEN_MODEL_BRAIN=claude-3-opus-20240229
export ZEN_MODEL_HANDS=claude-3-5-sonnet-20241022
export ZEN_SHOW_COSTS=false
```

### Security Considerations

**⚠️ Zen has full file system access within your project directory.**

| Risk | Mitigation |
|------|------------|
| **Untrusted task files** | Task files are executed by an LLM with write access. Review `.md` files from external sources before running. |
| **Local `zen.py` override** | If a `zen.py` exists in your project root, Zen executes it instead of the package. Requires `--trust-local` flag or interactive confirmation. |
| **`ZEN_SKIP_PERMISSIONS`** | Bypasses Claude CLI's permission prompts. **Use only in trusted CI/CD environments** where tasks are pre-reviewed. Never set in interactive sessions. |

```bash
# CI/CD example - only if tasks are trusted
export ZEN_SKIP_PERMISSIONS=true
zen task.md
```

### Judge Auto-Skip

The Judge phase (Opus architectural review) is automatically skipped to save costs when:

| Condition | Threshold |
|-----------|-----------|
| Trivial changes | < 5 lines changed |
| Docs/tests only | No production code touched |
| Small refactors | < 20 lines AND ≤ 2 plan steps |

**Always reviewed:** Files containing `auth`, `login`, `payment`, `crypt`, `secret`, or `token` in the path.

Override thresholds with: `ZEN_JUDGE_TRIVIAL`, `ZEN_JUDGE_SMALL`, `ZEN_JUDGE_SIMPLE_LINES`, `ZEN_JUDGE_SIMPLE_STEPS`

---

## CLI Reference

| Command | Description |
|---------|-------------|
| `zen init` | Create `.zen/` directory and default `CLAUDE.md` |
| `zen <task.md>` | Run the 5-phase workflow |
| `zen <task.md> --reset` | Wipe state and start fresh |
| `zen <task.md> --retry` | Clear completion markers to retry failed steps |
| `zen <task.md> --skip-judge` | Skip architectural review (saves ~$0.25) |

---

## The Linter (`zen_lint`)

Zen Mode includes a built-in "lazy coder detector" that runs after every implementation step. It enforces the Constitution by catching sloppy patterns before they ship.

### Rule Categories

| Severity | What It Catches |
|----------|-----------------|
| **HIGH** | Hardcoded secrets, merge conflict markers, truncation markers (`...rest of implementation`), bare `except:` |
| **MEDIUM** | TODO/FIXME comments, stub implementations (`pass`, `...`), inline imports, hardcoded public IPs |
| **LOW** | Debug prints, magic numbers (86400, 3600), catch-all exceptions, empty docstrings |

See [docs/linter-rules.md](docs/linter-rules.md) for the complete rule reference.

### Inline Suppression

Suppress specific rules when needed:
```python
debug_value = 86400  # lint:ignore MAGIC_NUMBER
print(x)             # lint:ignore  (suppresses all rules for this line)
```

### Config File

Create `.lintrc.json` to disable rules project-wide:
```json
{
  "disabled_rules": ["DEBUG_PRINT", "MAGIC_NUMBER"]
}
```

### Standalone Usage

```bash
# Lint git changes (default)
python -m zen_mode.linter

# Lint specific paths
python -m zen_mode.linter src/ tests/

# Output formats for CI
python -m zen_mode.linter --format json
python -m zen_mode.linter --format sarif  # GitHub Code Scanning compatible

# Show all rules
python -m zen_mode.linter --list-rules
```

---

## Troubleshooting

See [docs/troubleshooting.md](docs/troubleshooting.md) for common issues:

- Agent stuck on step → `zen task.md --retry` or edit `.zen/plan.md`
- Lint keeps failing → inline suppression or `.lintrc.json`
- Judge rejected → check `.zen/judge_feedback.md`
- Costs too high → `--skip-judge` or break into smaller tasks

---

## Documentation

| Document | Description |
|----------|-------------|
| [docs/linter-rules.md](docs/linter-rules.md) | Complete reference for all 25 lint rules |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common issues and solutions |
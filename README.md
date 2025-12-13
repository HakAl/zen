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
# OR copy 'scripts/zen.py' and 'scripts/zen_lint.py' to your project root.
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

> ```[COST] Total: $3.510 (scout=$0.180, plan=$0.152, implement=$2.615, verify=$0.265, judge=$0.261, summary=$0.038)```
<details>
<summary>Click to see full execution log and cost breakdown</summary>

```bash
test_repo> zen cleanup.md --reset
Reset complete.

[SCOUT] Mapping codebase for cleanup.md...
  [COST] sonnet scout: $0.1798 (228+1839=2067 tok)
  [SCOUT] Done.

[PLAN] Creating execution plan...
  [COST] opus plan: $0.1516 (6+948=954 tok)
  [PLAN] Done.
  [BACKUP] workers\scraper.py
  [BACKUP] requirements.txt
  [BACKUP] api\v1\tests\conftest.py
  [BACKUP] api\v1\tests\test_routes.py
  [BACKUP] api\db\models.py
  [BACKUP] api\db\repository.py

[IMPLEMENT] 16 steps to execute.

[STEP 1] Add scraping dependencies to requirements.txt (tenacity, fak...
  [COST] sonnet implement: $0.0681 (15+465=480 tok)
  [COMPLETE] Step 1

[STEP 2] Create ScraperConfig dataclass for timeout, retries, rate li...
  [COST] sonnet implement: $0.1010 (35+1040=1075 tok)
  [COMPLETE] Step 2

[STEP 3] Add retry decorator with exponential backoff using tenacity ...
  [COST] sonnet implement: $0.1017 (28+1197=1225 tok)
  [COMPLETE] Step 3

[STEP 4] Add rotating user-agent headers using fake-useragent library...
  [COST] sonnet implement: $0.1010 (27+1110=1137 tok)
  [COMPLETE] Step 4

[STEP 5] Add rate limiting with configurable delay between requests...
  [COST] sonnet implement: $0.1009 (27+1715=1742 tok)
  [COMPLETE] Step 5

[STEP 6] Add request timeout configuration to fetch_page method...
  [COST] sonnet implement: $0.0520 (15+524=539 tok)
  [COMPLETE] Step 6

[STEP 7] Add session management with connection pooling using request...
  [COST] sonnet implement: $0.1314 (36+1864=1900 tok)
  [COMPLETE] Step 7

[STEP 8] Add structured logging with Python logging module to WebScra...
  [COST] sonnet implement: $0.1961 (31+3517=3548 tok)
  [COMPLETE] Step 8

[STEP 9] Create workers/tests directory with __init__.py file...
  [COST] sonnet implement: $0.0592 (27+426=453 tok)
  [COMPLETE] Step 9

[STEP 10] Create workers/tests/conftest.py with pytest fixtures for mo...
  [COST] sonnet implement: $0.0903 (16+1744=1760 tok)
  [COMPLETE] Step 10

[STEP 11] Create workers/tests/test_scraper.py with tests for successf...
  [COST] sonnet implement: $0.1338 (26+3330=3356 tok)
  [COMPLETE] Step 11

[STEP 12] Add tests for retry logic on transient failures (5xx errors,...
  [COST] sonnet implement: $0.2961 (50+5202=5252 tok)
  [COMPLETE] Step 12

[STEP 13] Add tests for rate limiting behavior...
  [COST] sonnet implement: $0.2042 (34+3886=3920 tok)
  [COMPLETE] Step 13

[STEP 14] Add tests for user-agent rotation...
  [COST] sonnet implement: $0.2357 (2054+3894=5948 tok)
  [COMPLETE] Step 14

[STEP 15] Add tests for HTML parsing edge cases (empty content, malfor...
  [COST] sonnet implement: $0.4185 (2071+6290=8361 tok)
  [COMPLETE] Step 15

[STEP 16] Verify changes and run tests...
  [COST] sonnet implement: $0.3247 (53+2540=2593 tok)
  [COMPLETE] Step 16

[VERIFY] Running tests...
  [COST] sonnet verify: $0.2646 (67+2759=2826 tok)
  [VERIFY] Passed.
  [JUDGE] Required: Sensitive file (.scrappy/lancedb/code_chunks.lance/_indices/7e9eadae-cd58-457c-9031-7eeb51f022c4/part_6_tokens.lance)

[JUDGE] Senior Architect review...
  [JUDGE] Review loop 1/2
  [COST] opus judge: $0.2614 (5+750=755 tok)
  [JUDGE_APPROVED] Code passed architectural review.
  [COST] haiku summary: $0.0382 (14+641=655 tok)
  [COST] Total: $3.510 (scout=$0.180, plan=$0.152, implement=$2.615, verify=$0.265, judge=$0.261, summary=$0.038)

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
| **Context Awareness** | **Blind.** Guesses file paths and imports.                        |  **Scout.** Maps dependency graph first.                    |
| **User Experience** | **Frustrating.** User acts as the debugger and "copy-paste mule." | **Automated.** Agent writes, runs, and fixes its own tests. |
| **Success Rate** | Low. Often results in "Code Rot."                                 | High. Changes are verified against real tests.              |
| **True Cost** | **$1.75 + 2 hours** of your time debugging.                       | **~$3.50** (Flat fee for a finished result).                |

### Example: The "Scraper Refactor"
In the execution log above, Zen Mode performed a complex 16-step refactor on an existing scraper.
*   **Total Cost:** `$3.51`
*   **Human Time:** `0 minutes`
*   **Result:** It found the files, installed dependencies, wrote the code, **created new tests**, ran them, and self-corrected.

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

### Judge Auto-Skip

The Judge phase (Opus architectural review) is automatically skipped to save costs when:

| Condition | Threshold |
|-----------|-----------|
| Trivial changes | < 5 lines changed |
| Docs/tests only | No production code touched |
| Small refactors | < 20 lines AND ≤ 2 plan steps |

**Always reviewed:** Files containing `auth`, `login`, `payment`, `crypt`, `secret`, or `token` in the path.

Override thresholds with: `ZEN_JUDGE_TRIVIAL`, `ZEN_JUDGE_SMALL`, `ZEN_JUDGE_SIMPLE_LINES`, `ZEN_JUDGE_SIMPLE_STEPS`

### The Eject Button
If you installed via pip but want to hack the source code:
```bash
zen eject
```
This copies `zen.py` and `zen_lint.py` to your project root for local modifications. The `zen` command will automatically use your local versions.

---

## CLI Reference

| Command | Description |
|---------|-------------|
| `zen init` | Create `.zen/` directory and default `CLAUDE.md` |
| `zen <task.md>` | Run the 5-phase workflow |
| `zen <task.md> --reset` | Wipe state and start fresh |
| `zen <task.md> --retry` | Clear completion markers to retry failed steps |
| `zen <task.md> --skip-judge` | Skip architectural review (saves ~$0.25) |
| `zen <task.md> --dry-run` | Preview without executing |
| `zen eject` | Copy scripts to project root for customization |

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
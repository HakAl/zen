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

> ```[COST] Total: $1.966 (scout=$0.063, plan=$0.003, implement=$1.540, verify=$0.099, judge=$0.222, summary=$0.039)```
<details>
<summary>Click to see full execution log and cost breakdown</summary>

```bash
> zen .\cleanup.md --reset
Reset complete.

[SCOUT] Mapping codebase for .\cleanup.md...
  [COST] haiku scout: $0.0626 (52+1670=1722 tok)
  [SCOUT] Done.

[PLAN] Creating execution plan...
  [COST] opus plan: $0.0029 (0+0=0 tok)
  [PLAN] Done.
  [BACKUP] workers\scraper.py
  [BACKUP] requirements.txt
  [BACKUP] api\db\models.py
  [BACKUP] api\db\repository.py
  [BACKUP] api\v1\routes.py

[IMPLEMENT] 12 steps to execute.

[STEP 1] Create workers/__init__.py to establish workers as a Python ...
  [COST] sonnet implement: $0.0957 (40+1004=1044 tok)
  [COMPLETE] Step 1

[STEP 2] Add httpx, tenacity, lxml, and pytest-httpx to requirements....
  [COST] sonnet implement: $0.0473 (15+430=445 tok)
  [COMPLETE] Step 2

[STEP 3] Rewrite workers/scraper.py with ScraperConfig dataclass for ...
  [COST] sonnet implement: $0.1141 (30+2296=2326 tok)
  [COMPLETE] Step 3

[STEP 4] Add exponential backoff retry logic using tenacity decorator...
  [COST] sonnet implement: $0.1030 (27+1615=1642 tok)
  [COMPLETE] Step 4

[STEP 5] Implement session-based HTTP client with httpx supporting co...
  [COST] sonnet implement: $0.1045 (31+2256=2287 tok)
  [COMPLETE] Step 5

[STEP 6] Add custom exception classes for ScraperError, FetchError, a...
  [COST] sonnet implement: $0.0556 (19+687=706 tok)
  [COMPLETE] Step 6

[STEP 7] Enhance parse_html method with lxml parser and extraction me...
  [COST] sonnet implement: $0.2189 (50+4265=4315 tok)
  [COMPLETE] Step 7

[STEP 8] Add rate limiting with configurable delay between requests i...
  [COST] sonnet implement: $0.1546 (45+2860=2905 tok)
  [COMPLETE] Step 8

[STEP 9] Create workers/tests/__init__.py for test package structure...
  [COST] sonnet implement: $0.0570 (32+596=628 tok)
  [COMPLETE] Step 9

[STEP 10] Create workers/tests/conftest.py with pytest fixtures for mo...
  [COST] sonnet implement: $0.1695 (37+3084=3121 tok)
  [COMPLETE] Step 10

[STEP 11] Create workers/tests/test_scraper.py with tests for successf...
  [COST] sonnet implement: $0.1753 (16+6621=6637 tok)
  [COMPLETE] Step 11

[STEP 12] Verify changes by running pytest on workers/tests/test_scrap...
  [COST] sonnet implement: $0.2447 (48+2927=2975 tok)
  [COMPLETE] Step 12

[VERIFY] Running tests...
  [COST] sonnet verify: $0.0987 (40+1279=1319 tok)
  [VERIFY] Passed.
  [JUDGE] Required: Sensitive file (.scrappy/lancedb/code_chunks.lance/_indices/7e9eadae-cd58-457c-9031-7eeb51f022c4/part_6_tokens.lance)

[JUDGE] Senior Architect review...
  [JUDGE] Review loop 1/2
  [COST] opus judge: $0.2224 (6+811=817 tok)
  [JUDGE_APPROVED] Code passed architectural review.
  [COST] haiku summary: $0.0389 (18+652=670 tok)
  [COST] Total: $1.966 (scout=$0.063, plan=$0.003, implement=$1.540, verify=$0.099, judge=$0.222, summary=$0.039)

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
| **True Cost** | **$1.75 + 2 hours** of your time debugging.                       | **~$2** (Flat fee for a finished result).                   |

### Example: The "Scraper Refactor"
In the execution log above, Zen Mode performed a complex 12 step refactor on an existing scraper.
*   **Total Cost:** `$2`
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
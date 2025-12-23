# Troubleshooting Guide

Common issues and how to resolve them.

---

## Agent Issues

### "Agent stuck on step" / Step keeps failing

**Symptoms:**
- Same step fails repeatedly
- `[FAILED] Step N after 2 attempts`
- Agent seems to be making the same mistake

**Solutions:**

1. **Retry with fresh context:**
   ```bash
   zen task.md --retry
   ```
   This clears completion markers and lets the agent retry from where it left off.

2. **Edit the plan manually:**
   Open `.zen/plan.md` and modify the problematic step to be more specific:
   ```markdown
   ## Step 3: Refactor authentication module
   ```
   Change to:
   ```markdown
   ## Step 3: Move validate_token() from auth.py to tokens.py and update imports in routes.py
   ```

3. **Reset completely:**
   ```bash
   zen task.md --reset
   ```
   Wipes all state and starts from scratch.

4. **Check backups:**
   If the agent made breaking changes:
   ```bash
   ls .zen/backup/
   # Restore a file
   cp .zen/backup/src/module.py src/module.py
   ```

---

### "STEP_BLOCKED" error

**Symptoms:**
- Agent reports `STEP_BLOCKED: <reason>`
- Execution halts

**Cause:** The agent determined it cannot complete the step (missing dependencies, ambiguous requirements, etc.)

**Solutions:**

1. Read the block reason carefully
2. Address the blocker manually or update your task description
3. Run `zen task.md --retry` to continue

---

### Agent takes too long / Timeout

**Symptoms:**
- `[ERROR] Claude (sonnet) timed out`
- Steps hang indefinitely

**Solutions:**

1. **Increase timeout:**
   ```bash
   export ZEN_TIMEOUT=900  # 15 minutes instead of 10
   ```

2. **Break down the task:**
   Large tasks should be split into smaller task files.

3. **Check network:**
   Ensure stable connection to Anthropic API.

---

## Linter Issues

### "Lint keeps failing"

**Symptoms:**
- `[LINT FAIL] Step N`
- Same lint errors after multiple retries

**Solutions:**

1. **Check the actual error:**
   Look at the lint output in the terminal. Common issues:
   - `TODO` comments the agent left behind
   - `pass` stubs in new functions
   - Debug `print()` statements

2. **Suppress false positives:**
   If the lint rule is too strict for your case:
   ```python
   debug_flag = True  # lint:ignore
   ```

3. **Disable rules globally:**
   Create `.lintrc.json`:
   ```json
   {
     "disabled_rules": ["DEBUG_PRINT"]
   }
   ```

4. **Fix manually and retry:**
   ```bash
   # Fix the issue in your editor
   zen task.md --retry
   ```

---

### Linter times out

**Symptoms:**
- `Linter timed out after 120s`

**Solutions:**

1. **Increase linter timeout:**
   ```bash
   export ZEN_LINTER_TIMEOUT=300
   ```

2. **Check for large generated files:**
   Linter might be scanning files that should be ignored. Add them to `.gitignore`.

---

## Judge Issues

### "JUDGE_REJECTED"

**Symptoms:**
- `[JUDGE_REJECTED] Issues found`
- Agent attempts fixes but judge still rejects

**Solutions:**

1. **Check feedback file:**
   ```bash
   cat .zen/judge_feedback.md
   ```
   This contains the specific issues the Judge found.

2. **Skip judge for simple changes:**
   ```bash
   zen task.md --skip-judge
   ```
   Use when you trust the implementation is correct.

3. **Check your CLAUDE.md:**
   The Judge enforces rules from your Constitution. Make sure you're not violating your own rules.

---

### "ESCALATE_TO_HUMAN"

**Symptoms:**
- `[ESCALATE_TO_HUMAN] Max judge loops reached`
- Judge and fixer are going in circles

**Cause:** The Judge keeps finding issues that the fixer can't resolve automatically.

**Solutions:**

1. **Review `.zen/judge_feedback.md`** for the specific issues
2. **Fix manually** based on the feedback
3. **Run `zen task.md --retry --skip-judge`** to verify tests pass

---

## Cost Issues

### Costs higher than expected

**Symptoms:**
- Total cost significantly higher than typical tasks
- Many retries or escalations

**Solutions:**

1. **Check the cost breakdown:**
   ```
   [COST] Total: $5.23 (scout=$0.18, plan=$0.15, implement=$3.80, verify=$0.50, judge=$0.60)
   ```
   Identify which phase is expensive.

2. **Reduce judge usage:**
   ```bash
   zen task.md --skip-judge  # Saves ~$0.25-0.50 per run
   ```

3. **Use Haiku for simple tasks:**
   ```bash
   export ZEN_MODEL_BRAIN=haiku
   export ZEN_MODEL_HANDS=haiku
   ```

4. **Break large tasks into smaller ones:**
   Multiple small tasks often cost less than one large task with many retries.

---

### No cost shown

**Symptoms:**
- `[WARN] Failed to parse JSON response, cost not tracked`

**Cause:** Claude CLI returned malformed JSON or warnings before the response.

**Solutions:**

1. Update Claude CLI:
   ```bash
   npm update -g @anthropic-ai/claude-cli
   ```

2. Check for CLI errors:
   ```bash
   claude --version
   ```

---

## File Issues

### "Task file must be within project directory"

**Symptoms:**
- `ERROR: Task file must be within project directory`

**Cause:** Task file path traversal detected (security feature).

**Solutions:**

1. Move your task file into the project:
   ```bash
   cp ~/tasks/feature.md ./feature.md
   zen feature.md
   ```

2. Run from the correct directory:
   ```bash
   cd /path/to/project
   zen docs/task.md
   ```

---

### Files not being backed up

**Symptoms:**
- No backup created for modified files
- `.zen/backup/` is empty

**Cause:** Files not listed in scout report aren't backed up.

**Solutions:**

1. **Reset and re-run:**
   ```bash
   zen task.md --reset
   ```
   The scout phase should identify files correctly.

2. **Check scout report:**
   ```bash
   cat .zen/scout.md
   ```
   Ensure your target files are listed under "Targeted Files".

---

## Recovery

### How to undo all changes

```bash
# If you have backups
cp -r .zen/backup/* .

# If you have git
git checkout .
git clean -fd

# Nuclear option
git reset --hard HEAD
```

### How to see what changed

```bash
# View git diff
git diff

# View changed file list
git status

# View what the agent logged
cat .zen/log.md
```

### How to continue after manual fixes

```bash
# Continue from where you left off
zen task.md --retry

# Or skip to verification
# (edit .zen/log.md to mark steps as [COMPLETE])
```

---

## Getting Help

1. **Check the log:**
   ```bash
   cat .zen/log.md
   ```

2. **Check individual phase outputs:**
   ```bash
   cat .zen/scout.md    # What files were identified
   cat .zen/plan.md     # The execution plan
   cat .zen/test_output.txt  # Test results
   ```

3. **File an issue:**
   https://github.com/anthropics/claude-code/issues

"""
Zen Mode: The "Anti-Jira" Agent Workflow.

PHILOSOPHY:
1. File System is the Database.
2. Markdown is the API.
3. If a file exists, that step is done.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tempfile
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from zen_mode.triage import (
    parse_triage,
    should_fast_track,
    generate_synthetic_plan,
)
from zen_mode import utils
from zen_mode.config import (
    MODEL_BRAIN,
    MODEL_HANDS,
    MODEL_EYES,
    TIMEOUT_EXEC,
    TIMEOUT_LINTER,
    TIMEOUT_SUMMARY,
    MAX_RETRIES,
    MAX_JUDGE_LOOPS,
    JUDGE_TRIVIAL_LINES,
    JUDGE_SMALL_REFACTOR_LINES,
    JUDGE_SIMPLE_PLAN_LINES,
    JUDGE_SIMPLE_PLAN_STEPS,
    WORK_DIR_NAME,
    PROJECT_ROOT,
    WORK_DIR,
    SHOW_COSTS,
    PARSE_TEST_THRESHOLD,
)
from zen_mode.verify import (
    TestState,
    phase_verify,
    verify_and_fix,
    project_has_tests,
    extract_failure_count,
    detect_no_tests,
    verify_test_output,
    parse_test_output,
)

from . import linter

# -----------------------------------------------------------------------------
# Derived Paths (from config)
# -----------------------------------------------------------------------------
SCOUT_FILE = WORK_DIR / "scout.md"
PLAN_FILE = WORK_DIR / "plan.md"
LOG_FILE = WORK_DIR / "log.md"
NOTES_FILE = WORK_DIR / "final_notes.md"
BACKUP_DIR = WORK_DIR / "backup"
TEST_OUTPUT_FILE = WORK_DIR / "test_output.txt"
JUDGE_FEEDBACK_FILE = WORK_DIR / "judge_feedback.md"

# -----------------------------------------------------------------------------
# Cost Tracking (runtime state)
# -----------------------------------------------------------------------------
_phase_costs: Dict[str, float] = {}
_phase_tokens: Dict[str, Dict[str, int]] = {}

DRY_RUN = False

CLAUDE_EXE: Optional[str] = None
ALLOWED_FILES: Optional[str] = None


def _init_claude() -> str:
    """Initialize Claude CLI path. Returns path or exits."""
    global CLAUDE_EXE
    if CLAUDE_EXE:
        return CLAUDE_EXE
    CLAUDE_EXE = shutil.which("claude") or os.getenv("CLAUDE_EXE")
    if not CLAUDE_EXE:
        print("ERROR: 'claude' CLI not found.")
        print("Install: npm i -g @anthropic-ai/claude-cli")
        sys.exit(1)
    return CLAUDE_EXE


# -----------------------------------------------------------------------------
# Core Utils
# -----------------------------------------------------------------------------
def log(msg: str) -> None:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(f"  {msg}")


def read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def write_file(path: Path, content: str) -> None:
    WORK_DIR.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=WORK_DIR, delete=False, encoding="utf-8") as tf:
        tf.write(content)
        tmp = tf.name

    # Atomic replace with Windows retry
    try:
        Path(tmp).replace(path)
    except OSError:
        # Windows: file may be busy (virus scanner, IDE)
        time.sleep(0.3)
        try:
            Path(tmp).replace(path)
        except OSError as e:
            # Clean up temp file on failure
            Path(tmp).unlink(missing_ok=True)
            raise OSError(f"Failed to write {path}: {e}")


def backup_file(path: Path) -> None:
    """Create a backup of a file before modification."""
    if not path.exists():
        return

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    rel_path = path.relative_to(PROJECT_ROOT) if path.is_relative_to(PROJECT_ROOT) else path

    # Preserve directory structure to avoid collisions
    backup_path = BACKUP_DIR / rel_path
    backup_path.parent.mkdir(parents=True, exist_ok=True)

    # Only backup if we haven't already
    if not backup_path.exists():
        shutil.copy2(path, backup_path)
        log(f"[BACKUP] {rel_path}")


def _is_test_or_doc(path: str) -> bool:
    """Check if path is a test or documentation file."""
    return (path.endswith(('.md', '.txt', '.rst')) or
            '/test' in path or path.startswith('test') or
            '_test.' in path or 'test_' in path)


def _extract_cost(raw: dict) -> tuple[float, dict[str, int]]:
    """Extract cost and token counts from CLI JSON response."""
    cost = float(raw.get("total_cost_usd") or 0)
    usage = raw.get("usage") or {}
    return cost, {
        "in": int(usage.get("input_tokens") or 0),
        "out": int(usage.get("output_tokens") or 0),
        "cache_read": int(usage.get("cache_read_input_tokens") or 0),
    }


def _parse_json_response(stdout: str) -> Optional[dict]:
    """Parse JSON from CLI output, stripping any warning prefixes."""
    # CLI may emit warnings before JSON; find first '{'
    start = stdout.find("{")
    if start == -1:
        return None
    try:
        return json.loads(stdout[start:])
    except json.JSONDecodeError:
        return None


def _record_cost(phase: str, cost: float, tokens: dict[str, int]) -> None:
    """Accumulate cost and tokens for a phase."""
    _phase_costs[phase] = _phase_costs.get(phase, 0) + cost
    _phase_tokens.setdefault(phase, {"in": 0, "out": 0, "cache_read": 0})
    for k in tokens:
        _phase_tokens[phase][k] += tokens[k]


def run_claude(prompt: str, model: str, *, phase: str = "unknown", timeout: Optional[int] = None) -> Optional[str]:
    timeout = timeout or TIMEOUT_EXEC
    if DRY_RUN:
        log(f"[DRY-RUN] Would call {model}")
        return "DRY_RUN_OUTPUT"

    claude_exe = _init_claude()
    cmd = [claude_exe, "-p", "--dangerously-skip-permissions", "--model", model,
           "--output-format", "json"]
    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=PROJECT_ROOT,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        # Write prompt and close stdin immediately to send EOF
        # This prevents child processes (gradle) from blocking on stdin reads
        try:
            proc.stdin.write(prompt)
            proc.stdin.close()
        except BrokenPipeError:
            log(f"[WARN] Claude ({model}) stdin closed early")
        stdout, stderr = proc.communicate(timeout=timeout)

        if proc.returncode != 0:
            log(f"[ERROR] Claude ({model}): {stderr[:300]}")
            return None

        data = _parse_json_response(stdout)
        if not isinstance(data, dict):
            log("[WARN] Failed to parse JSON response, cost not tracked")
            return stdout  # Continue without cost data

        try:
            cost, tokens = _extract_cost(data)
            _record_cost(phase, cost, tokens)

            if SHOW_COSTS:
                total_tok = tokens["in"] + tokens["out"]
                log(f"[COST] {model} {phase}: ${cost:.4f} ({tokens['in']}+{tokens['out']}={total_tok} tok)")
        except (KeyError, TypeError, ValueError) as e:
            log(f"[WARN] Cost extraction failed: {e}")

        return data.get("result")

    except subprocess.TimeoutExpired:
        log(f"[ERROR] Claude ({model}) timed out")
        if proc:
            proc.terminate()
            try:
                stdout, stderr = proc.communicate(timeout=5)
                # Debug: capture partial output on timeout
                if phase == "verify":
                    log(f"[DEBUG] Timeout partial: stdout_len={len(stdout) if stdout else 0}, stderr_len={len(stderr) if stderr else 0}")
                    if stderr:
                        log(f"[DEBUG] stderr: {stderr[:300]}")
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
        return None
    except Exception as e:
        log(f"[ERROR] Subprocess: {e}")
        if proc:
            proc.terminate()
            proc.communicate()
        return None


def _write_cost_summary() -> None:
    """Write cost summary to log and final_notes."""
    if not _phase_costs:
        return  # No costs tracked (e.g., dry run)

    total = sum(_phase_costs.values())
    total_in = sum(t["in"] for t in _phase_tokens.values())
    total_out = sum(t["out"] for t in _phase_tokens.values())
    total_cache = sum(t["cache_read"] for t in _phase_tokens.values())
    breakdown = ", ".join(f"{k}=${v:.3f}" for k, v in _phase_costs.items())

    summary = f"[COST] Total: ${total:.3f} ({breakdown})"
    log(summary)

    # Append to log.md
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"\n{summary}\n")

    # Append to final_notes.md
    with NOTES_FILE.open("a", encoding="utf-8") as f:
        f.write("\n## Cost Summary\n")
        f.write(f"Total: ${total:.3f}\n")
        f.write(f"Tokens: {total_in} in, {total_out} out, {total_cache} cache read\n")
        f.write(f"Breakdown: {breakdown}\n")


def _git_has_head() -> bool:
    """Check if git repo has at least one commit (HEAD exists)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=PROJECT_ROOT
        )
        return result.returncode == 0
    except Exception:
        return False


def _git_is_repo() -> bool:
    """Check if we're in a git repository."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True, text=True, cwd=PROJECT_ROOT
        )
        return result.returncode == 0
    except Exception:
        return False


def should_skip_judge() -> bool:
    """Skip expensive Opus review for trivial/safe changes.

    Handles edge cases:
    - No git repo: returns False (require judge, fail-safe)
    - No commits (fresh repo): uses git diff --cached instead of diff HEAD
    """
    # Check if we're in a git repo
    if not _git_is_repo():
        return False  # Fail-safe: require judge if not a git repo

    # Get modified files (tracked)
    numstat = ""
    if _git_has_head():
        try:
            result = subprocess.run(
                ["git", "diff", "--numstat", "HEAD"],
                capture_output=True, text=True, cwd=PROJECT_ROOT
            )
            if result.returncode == 0:
                numstat = result.stdout.strip()
        except Exception:
            pass
    else:
        # No commits yet - use git diff --cached to find staged files
        try:
            result = subprocess.run(
                ["git", "diff", "--cached", "--numstat"],
                capture_output=True, text=True, cwd=PROJECT_ROOT
            )
            if result.returncode == 0:
                numstat = result.stdout.strip()
        except Exception:
            pass

    # Get untracked files (new files not yet in git)
    untracked = ""
    try:
        untracked_result = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, cwd=PROJECT_ROOT
        )
        if untracked_result.returncode == 0:
            untracked = untracked_result.stdout.strip()
    except Exception:
        pass

    # Handle edge cases for new files
    if not numstat and not untracked:
        log("[JUDGE] Skipping: No changes detected")
        return True

    if not numstat and untracked:
        # Only new files, no modifications to existing
        untracked_files = untracked.splitlines()
        if not all(_is_test_or_doc(f) for f in untracked_files):
            log("[JUDGE] Required: New code files created")
            return False
        log("[JUDGE] Skipping: Only new test/doc files")
        return True

    # Parse numstat for modified files
    total_add, total_del = 0, 0
    changed_files = []

    for line in numstat.splitlines():
        parts = line.split('\t')
        if len(parts) >= 3:
            add = int(parts[0]) if parts[0] != '-' else 0
            delete = int(parts[1]) if parts[1] != '-' else 0
            total_add += add
            total_del += delete
            changed_files.append(parts[2])

    # Include untracked files in the file list for risk assessment
    if untracked:
        changed_files.extend(untracked.splitlines())

    total_changes = total_add + total_del
    has_new_code_files = untracked and not all(_is_test_or_doc(f) for f in untracked.splitlines())

    # Rule B: Risky files always reviewed (check FIRST - before any skip rules)
    risky_patterns = ['auth', 'login', 'secur', 'payment', 'crypt', 'secret', 'token']
    for f in changed_files:
        if any(r in f.lower() for r in risky_patterns):
            log(f"[JUDGE] Required: Sensitive file ({f})")
            return False

    # Rule A: Typo fix threshold (but not if new code files exist)
    if total_changes < JUDGE_TRIVIAL_LINES and not has_new_code_files:
        log(f"[JUDGE] Skipping: Trivial ({total_changes} lines)")
        return True

    # Rule C: Pure docs/tests exempt
    if all(_is_test_or_doc(f) for f in changed_files):
        log("[JUDGE] Skipping: Only docs/tests changed")
        return True

    # Rule D: Small refactor + simple plan
    plan = read_file(PLAN_FILE)
    steps = parse_steps(plan)
    if len(steps) <= JUDGE_SIMPLE_PLAN_STEPS and total_changes < JUDGE_SIMPLE_PLAN_LINES and not has_new_code_files:
        log(f"[JUDGE] Skipping: Simple ({len(steps)} steps, {total_changes} lines)")
        return True

    if total_changes < JUDGE_SMALL_REFACTOR_LINES and not has_new_code_files:
        log(f"[JUDGE] Skipping: Small refactor ({total_changes} lines)")
        return True

    return False


# -----------------------------------------------------------------------------
# Shared Prompts
# -----------------------------------------------------------------------------
def build_scout_prompt(task_file: str, output_file: str) -> str:
    """Build scout prompt for mapping codebase. Used by both core and swarm."""
    return f"""<task>
Scout codebase for: {task_file}
</task>

<objective>
Map code relevant to the task. Quality over quantity.
</objective>

<investigation>
1. find . -type f -name "*.py" (or equivalent for the language)
2. grep -r for task-related symbols
3. Read ONLY signatures/exports of key files — never dump full contents
</investigation>

<constraints>
- Max 30 files total
- Skip: tests and build files: test*, docs/, node_modules/, venv/, migrations/, __pycache__/, etc
- If unsure whether a file matters, include in Context (not Targeted)
</constraints>

<output>
Write to: {output_file}

Format (markdown, ALL 5 SECTIONS REQUIRED):
## Targeted Files (Must Change)
- `path/to/file.py`: one-line reason

## Context Files (Read-Only)
- `path/to/file.py`: one-line reason (or "None")

## Deletion Candidates
- `path/to/file.py`: one-line reason (or "None")

## Open Questions
- Question about ambiguity (or "None")

## Triage
COMPLEXITY: LOW or HIGH
CONFIDENCE: 0.0-1.0
FAST_TRACK: YES or NO

If FAST_TRACK=YES, also include:
TARGET_FILE: exact/path (or "N/A" if VERIFY_COMPLETE)
OPERATION: UPDATE|INSERT|DELETE|VERIFY_COMPLETE
INSTRUCTION: one-line change description (or verification summary)

FAST_TRACK=YES if:
- 1-2 files, obvious fix, no new deps, not auth/payments, OR
- Task already complete with HIGH confidence (use OPERATION: VERIFY_COMPLETE)

If unsure, FAST_TRACK=NO.
</output>"""


# -----------------------------------------------------------------------------
# Phases
# -----------------------------------------------------------------------------
def phase_scout(task_file: str) -> None:
    if SCOUT_FILE.exists():
        log("[SCOUT] Cached. Skipping.")
        return

    log(f"\n[SCOUT] Mapping codebase for {task_file}...")
    prompt = build_scout_prompt(task_file, str(SCOUT_FILE))

    output = run_claude(prompt, model=MODEL_EYES, phase="scout")
    if not output:
        log("[SCOUT] Failed.")
        sys.exit(1)

    # Fallback: write output if Claude didn't
    if not SCOUT_FILE.exists():
        write_file(SCOUT_FILE, output)

    log("[SCOUT] Done.")


def phase_plan(task_file: str) -> None:
    if PLAN_FILE.exists():
        log("[PLAN] Cached. Skipping.")
        return

    log("\n[PLAN] Creating execution plan...")
    scout = read_file(SCOUT_FILE)
    # Prompt structured for cache optimization: stable content first, variable content last
    base_prompt = f"""<role>
You are a senior software architect creating an execution plan.
Your plans are precise, atomic, and efficient.
</role>

<rules>
- Clean Code over Backward Compatibility
- DELETE old code, no shims
- UPDATE callers directly
- Final step MUST be verification (test/verify/validate)
</rules>

<consolidation>
- Combine related test categories into 1-2 test steps maximum
- Do NOT create separate steps for: retry tests, validation tests, edge case tests
- Group: "Create all unit tests for [component]" not "Create tests for X, then Y, then Z"
- Use "targeted tests covering key behavior" not "comprehensive tests covering X, Y, Z"
</consolidation>

<EXAMPLES>
BAD PLAN (10 steps, bloated):
## Step 1: Add retry dependency
## Step 2: Create config class
## Step 3: Add retry decorator
## Step 4: Add timeout handling
## Step 5: Add rate limiting
## Step 6: Add logging
## Step 7: Create test file
## Step 8: Add test for success
## Step 9: Add test for timeout
## Step 10: Add test for retry
...

GOOD PLAN (6 steps, efficient):
## Step 1: Add dependencies and configuration
## Step 2: Implement retry logic with timeout and rate limiting
## Step 3: Add structured logging
## Step 4: Add unit tests for core functionality
## Step 5: Update requirements.txt
## Step 6: Verify all tests pass
</EXAMPLES>

<output_format>
Format (strict markdown, no preamble):
## Step 1: <action verb> <specific target>
## Step 2: <action verb> <specific target>
...
## Step N: Verify changes and run tests

Each step: one atomic change. No sub-steps, no bullet lists within steps.
</output_format>

<task>
Create execution plan for: {task_file}
Write output to: {PLAN_FILE}
</task>

<context>
{scout}
</context>"""

    output = run_claude(base_prompt, model=MODEL_BRAIN, phase="plan")

    # Write plan if Claude didn't use Write tool
    if not PLAN_FILE.exists():
        if not output:
            log("[PLAN] Failed.")
            sys.exit(1)
        write_file(PLAN_FILE, output)

    # Validate efficiency (warn only, don't retry - Opus doesn't consolidate well)
    steps = parse_steps(read_file(PLAN_FILE))
    valid, efficiency_msg = validate_plan_efficiency(steps)

    if not valid:
        log(f"[PLAN] Warning: {efficiency_msg}")

    log(f"[PLAN] Done. {len(steps)} steps.")


def parse_steps(plan: str) -> List[Tuple[int, str]]:
    # Strict format: ## Step N: description
    strict = re.findall(r"^## Step (\d+):\s*(.+)$", plan, re.M)
    if strict:
        seen = set()
        result = []
        for n, desc in strict:
            step_num = int(n)
            if step_num not in seen:
                seen.add(step_num)
                result.append((step_num, desc.strip()))
        return result

    # Fallback: flexible parsing
    pattern = re.compile(
        r"(?:^|\n)(?:#{1,6}\s*)?(?:Step\s+(\d+)|(\d+)\.)[:\s]+(.*?)(?=\n(?:#{1,6}\s*)?(?:Step\s+\d+|\d+\.)|$)",
        re.DOTALL | re.IGNORECASE,
    )
    matches = pattern.findall(plan + "\n")
    if matches:
        seen = set()
        result = []
        for m in matches:
            step_num = int(m[0] or m[1])
            if step_num not in seen:
                seen.add(step_num)
                result.append((step_num, m[2].strip()))
        return result

    # Last resort: bullets
    bullets = re.findall(r"(?:^|\n)[-*]\s+(.*?)(?=\n[-*]|$)", plan)
    return [(i, txt.strip()) for i, txt in enumerate(bullets, 1) if txt.strip()]


def validate_plan_efficiency(steps: List[Tuple[int, str]]) -> Tuple[bool, str]:
    """Check plan for common inefficiency patterns. Returns (valid, message)."""
    if not steps:
        return True, ""

    step_descs = [desc.lower() for _, desc in steps]

    # Check for too many test steps
    test_steps = [s for s in step_descs if "test" in s]
    if len(test_steps) > 2:
        return False, f"CONSOLIDATE: {len(test_steps)} test steps found. Combine into 1-2 steps."

    # Check for excessive steps
    if len(steps) > 15:
        return False, f"SIMPLIFY: Plan has {len(steps)} steps (max 15). Look for consolidation."

    # Check for overly granular test patterns
    granular_patterns = ["add test for", "create test for", "write test for"]
    granular_count = sum(1 for s in step_descs if any(p in s for p in granular_patterns))
    if granular_count > 2:
        return False, "CONSOLIDATE: Multiple 'add/create/write test for X' steps. Group into single test step."

    return True, ""


def get_completed_steps() -> set:
    if not LOG_FILE.exists():
        return set()

    log_content = read_file(LOG_FILE)
    completed = set()

    # Explicit markers
    for m in re.findall(r"\[COMPLETE\] Step\s+(\d+)", log_content):
        completed.add(int(m))

    # Heuristic: steps before last started are done
    started = re.findall(r"\[STEP\s+(\d+)\]", log_content)
    if started:
        max_started = max(int(m) for m in started)
        for i in range(1, max_started):
            completed.add(i)

    return completed


def run_linter() -> Tuple[bool, str]:
    """Run the linter with timeout - package imports directly."""

    result: List = [False, f"Linter timed out after {TIMEOUT_LINTER}s"]

    def target():
        result[0], result[1] = linter.run_lint()

    thread = threading.Thread(target=target)
    thread.start()
    thread.join(timeout=TIMEOUT_LINTER)

    if thread.is_alive():
        # Thread still running - timeout occurred
        # Note: Python threads can't be killed, but we return timeout error
        return False, f"Linter timed out after {TIMEOUT_LINTER}s"

    return result[0], result[1]


def backup_scout_files() -> None:
    """Backup files identified in scout phase before modification."""
    scout = read_file(SCOUT_FILE)
    if not scout:
        return

    # Extract file paths from scout report (look for backtick-wrapped paths)
    file_pattern = re.compile(r"`([^`]+\.\w+)`")
    for match in file_pattern.finditer(scout):
        filepath = PROJECT_ROOT / match.group(1)
        if filepath.exists() and filepath.is_file():
            backup_file(filepath)


def phase_implement() -> None:
    plan = read_file(PLAN_FILE)
    steps = parse_steps(plan)

    if not steps:
        log("[IMPLEMENT] No steps found in plan.")
        sys.exit(1)

    # Check that plan includes a verification step
    last_step_desc = steps[-1][1].lower() if steps else ""
    verify_keywords = ['verify', 'test', 'check', 'validate', 'confirm']
    has_verify_step = any(kw in last_step_desc for kw in verify_keywords)
    if not has_verify_step:
        log("[WARN] Plan missing verification step. Adding implicit verify.")

    backup_scout_files()

    log(f"\n[IMPLEMENT] {len(steps)} steps to execute.")
    completed = get_completed_steps()
    seen_lint_hashes: set[str] = set()

    for step_num, step_desc in steps:
        if step_num in completed:
            continue

        log(f"\n[STEP {step_num}] {step_desc[:60]}...")

        # Check if this is a verification-only task (task already complete)
        is_verify_only = "OPERATION: VERIFY_COMPLETE" in plan

        if is_verify_only:
            base_prompt = f"""<task>
Verify that the task described below is already complete.
</task>

<verification>
{step_desc}
</verification>

<context>
Full plan:
{plan}
</context>

<instructions>
1. READ the relevant files to confirm the task is complete
2. If complete, explain what was already in place
3. If NOT complete, explain what's missing

Do NOT make any changes. This is verification only.
</instructions>

<output>
End with: STEP_COMPLETE (if verified) or STEP_BLOCKED: <reason> (if not complete)
</output>"""
        else:
            base_prompt = f"""<task>
Execute Step {step_num}: {step_desc}
</task>

<context>
IMPORTANT: This is a fresh session with no memory of previous steps.
READ target files first to understand current state before editing.

Full plan:
{plan}
</context>

<rules>
- DELETE old code, no shims
- UPDATE callers immediately
- No broken imports
</rules>

<RESTRICTIONS>
1. TESTS: If writing tests, maximum 3 functions. Cover: happy path, one error, one edge. Use temp directories for file I/O.
2. SCOPE: Do not implement "future proofing" or extra helper functions.
3. CONCISENESS: If a standard library function exists, use it. Do not reinvent utils.
</RESTRICTIONS>

<output>
End with: STEP_COMPLETE or STEP_BLOCKED: <reason>
</output>"""

        # Inject SCOPE XML block if allowed_files is provided
        if ALLOWED_FILES:
            base_prompt += f"""

<SCOPE>
You MUST ONLY modify files matching this glob pattern:
{ALLOWED_FILES}

Do not create, modify, or delete any files outside this scope.
</SCOPE>"""

        prompt = base_prompt
        last_error_summary = ""

        for attempt in range(1, MAX_RETRIES + 1):
            if attempt > 1:
                log(f"  Retry {attempt}/{MAX_RETRIES}...")

            # Escalate to Opus on final retry with CLEAN prompt
            if attempt == MAX_RETRIES:
                log(f"  Escalating to {MODEL_BRAIN}...")
                prompt = base_prompt + f"""

ESCALATION: Previous {attempt - 1} attempts by a junior model failed.
Last error: {last_error_summary}
You are the senior specialist. Analyze the problem fresh and fix it definitively."""
                model = MODEL_BRAIN
            else:
                model = MODEL_HANDS

            output = run_claude(prompt, model=model, phase="implement", timeout=TIMEOUT_EXEC) or ""

            # Check last line for STEP_BLOCKED to avoid false positives
            last_line = output.strip().split('\n')[-1] if output.strip() else ""
            if last_line.startswith("STEP_BLOCKED"):
                log(f"[BLOCKED] Step {step_num}")
                print(f"\n{output}")
                sys.exit(1)

            if "STEP_COMPLETE" in output:
                passed, lint_out = run_linter()
                if not passed:
                    log(f"[LINT FAIL] Step {step_num}")
                    for line in lint_out.splitlines()[:20]:
                        print(f"    {line}")

                    # Truncate for prompt to avoid blowing context
                    truncated = "\n".join(lint_out.splitlines()[:30])

                    # Capture summary for potential escalation
                    last_error_summary = truncated[:300]

                    # Hash full output to detect same error, but use truncated for prompt
                    lint_hash = hashlib.md5(lint_out.encode()).hexdigest()
                    if lint_hash in seen_lint_hashes:
                        prompt += f"\n\nLINT FAILED (same as a previous attempt—try a different fix):\n{truncated}"
                    else:
                        prompt += f"\n\nLINT FAILED:\n{truncated}\n\nFix the issues above."
                    seen_lint_hashes.add(lint_hash)

                    # Bail if we've seen too many distinct failures (agent is thrashing)
                    if len(seen_lint_hashes) >= MAX_RETRIES + 1:
                        log(f"[FAILED] Step {step_num}: {len(seen_lint_hashes)} distinct lint failures, agent is thrashing")
                        if BACKUP_DIR.exists():
                            log(f"[RECOVERY] Backups available in: {BACKUP_DIR}")
                        sys.exit(1)
                    continue

                log(f"[COMPLETE] Step {step_num}")
                seen_lint_hashes.clear()  # Reset on success
                break
        else:
            log(f"[FAILED] Step {step_num} after {MAX_RETRIES} attempts")
            if BACKUP_DIR.exists():
                log(f"[RECOVERY] Backups available in: {BACKUP_DIR}")
            sys.exit(1)


def phase_judge() -> None:
    """Judge phase: Review implementation for quality and alignment."""
    log("\n[JUDGE] Senior Architect review...")

    # Gather context
    plan = read_file(PLAN_FILE)
    scout = read_file(SCOUT_FILE)
    test_output = read_file(TEST_OUTPUT_FILE)

    constitution_path = PROJECT_ROOT / "CLAUDE.md"
    constitution = read_file(constitution_path) if constitution_path.exists() else "[No CLAUDE.md found]"

    changed_files = utils.get_changed_filenames(PROJECT_ROOT, BACKUP_DIR)
    if changed_files == "[No files detected]":
        log("[JUDGE] No changes detected. Auto-approving.")
        return

    for loop in range(1, MAX_JUDGE_LOOPS + 1):
        log(f"[JUDGE] Review loop {loop}/{MAX_JUDGE_LOOPS}")

        prompt = f"""<role>Senior Architect. Be direct and concise.</role>

<context>
<plan>{plan}</plan>
<scout>{scout}</scout>
<constitution>{constitution}</constitution>
<test_results>{test_output[:2000]}</test_results>
<changed_files>{changed_files}</changed_files>
</context>

<task>
Review implementation using `git diff HEAD -- <file>` or read files directly.
</task>

<criteria>
1. Plan Alignment — Does the diff satisfy the requirements?
2. Constitution Adherence — Any CLAUDE.md rule violations?
3. Security and Edge Cases — Obvious vulnerabilities or unhandled cases?

IGNORE: Syntax, formatting, linting (already verified by tooling).
</criteria>

<output>
If approved:
JUDGE_APPROVED

If rejected:
JUDGE_REJECTED

## Issues
- Issue 1: [specific problem]

## Fix Plan
Step 1: [specific fix action]
</output>"""

        output = run_claude(prompt, model=MODEL_BRAIN, phase="judge", timeout=TIMEOUT_EXEC)

        # Fail-closed: prompt user on judge failure
        if not output:
            log("[JUDGE] No response from Judge.")
            try:
                choice = input(">> Judge failed. Proceed anyway? [y/N]: ").strip().lower()
                if choice == 'y':
                    log("[JUDGE] User approved proceeding without review.")
                    return
            except EOFError:
                pass  # Non-interactive, fall through to exit
            log("[JUDGE] Aborting (fail-closed).")
            sys.exit(1)

        if "JUDGE_APPROVED" in output:
            log("[JUDGE_APPROVED] Code passed architectural review.")
            return

        if "JUDGE_REJECTED" not in output:
            log("[JUDGE] Unclear verdict from Judge.")
            try:
                choice = input(">> Judge gave unclear verdict. Proceed anyway? [y/N]: ").strip().lower()
                if choice == 'y':
                    log("[JUDGE] User approved proceeding despite unclear verdict.")
                    return
            except EOFError:
                pass
            log("[JUDGE] Aborting (fail-closed).")
            sys.exit(1)

        # Rejected - extract feedback
        log(f"[JUDGE_REJECTED] Issues found (loop {loop})")

        # Parse feedback (everything after JUDGE_REJECTED)
        feedback = output.split("JUDGE_REJECTED", 1)[-1].strip()
        write_file(JUDGE_FEEDBACK_FILE, feedback)

        # Print issues for visibility
        for line in feedback.splitlines()[:10]:
            print(f"    {line}")

        if loop >= MAX_JUDGE_LOOPS:
            log("[ESCALATE_TO_HUMAN] Max judge loops reached. Manual review required.")
            log(f"[INFO] Judge feedback saved to: {JUDGE_FEEDBACK_FILE}")
            sys.exit(1)

        # Apply fixes with Sonnet - include changed files list
        log("[JUDGE_FIX] Applying fixes...")
        changed_files = utils.get_changed_filenames(PROJECT_ROOT, BACKUP_DIR)

        fix_prompt = f"""<task>
JUDGE FEEDBACK - Fixes Required:

{feedback}
</task>

## Constitution (CLAUDE.md)
{constitution}

## Changed Files
{changed_files}

## Original Plan
{plan}

<context>
IMPORTANT: This is a fresh session. The files listed above were modified.
READ those files first to understand current state before making fixes.
</context>

<rules>
Execute the fixes above. After fixing:
1. Ensure linting passes
2. Ensure tests still pass
</rules>

<output>
End with: FIXES_COMPLETE or FIXES_BLOCKED: <reason>
</output>"""

        fix_output = run_claude(fix_prompt, model=MODEL_HANDS, phase="judge_fix", timeout=TIMEOUT_EXEC)

        if not fix_output:
            log("[JUDGE_FIX] No response from fixer.")
            sys.exit(1)

        if "FIXES_BLOCKED" in fix_output:
            log("[JUDGE_FIX] Fixes blocked. Manual intervention required.")
            sys.exit(1)

        # Re-run linter after fixes
        passed, lint_out = run_linter()
        if not passed:
            log("[JUDGE_FIX] Lint failed after fixes.")
            for line in lint_out.splitlines()[:10]:
                print(f"    {line}")
            sys.exit(1)

        # Re-run verify (tests) - just check, don't try to fix
        log("[JUDGE_FIX] Checking tests...")
        state, _ = phase_verify()
        if state == TestState.FAIL:
            log("[JUDGE_FIX] Tests failed after fixes.")
            sys.exit(1)
        elif state == TestState.ERROR:
            log("[JUDGE_FIX] Test runner error.")
            sys.exit(1)
        elif state == TestState.RUNTIME_MISSING:
            log("[JUDGE_FIX] Runtime not installed, skipping tests.")

        # Update changed files for next judge loop
        changed_files = utils.get_changed_filenames(PROJECT_ROOT, BACKUP_DIR)

        # Clean up feedback file on retry
        if JUDGE_FEEDBACK_FILE.exists():
            JUDGE_FEEDBACK_FILE.unlink()

    # Should not reach here
    log("[JUDGE] Unexpected exit from judge loop.")
    sys.exit(1)


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------
def run(task_file: str, flags: Optional[set] = None, scout_context: Optional[str] = None, allowed_files: Optional[str] = None) -> None:
    """
    Run the Zen workflow on a task file.

    Args:
        task_file: Path to task markdown file
        flags: Set of flags (--reset, --retry, --dry-run)
        scout_context: Optional path to pre-computed scout context file
        allowed_files: Optional glob pattern for allowed files to modify
    """
    global DRY_RUN, WORK_DIR, SCOUT_FILE, PLAN_FILE, LOG_FILE, NOTES_FILE, BACKUP_DIR, TEST_OUTPUT_FILE, JUDGE_FEEDBACK_FILE, ALLOWED_FILES

    ALLOWED_FILES = allowed_files
    flags = flags or set()

    task_path = Path(task_file)
    resolved_path = task_path.resolve()
    if not resolved_path.is_relative_to(PROJECT_ROOT.resolve()):
        print(f"ERROR: Task file must be within project directory: {task_file}")
        sys.exit(1)
    if not task_path.exists():
        print(f"ERROR: Task file not found: {task_file}")
        sys.exit(1)

    # Set up paths
    WORK_DIR = PROJECT_ROOT / WORK_DIR_NAME
    SCOUT_FILE = WORK_DIR / "scout.md"
    PLAN_FILE = WORK_DIR / "plan.md"
    LOG_FILE = WORK_DIR / "log.md"
    NOTES_FILE = WORK_DIR / "final_notes.md"
    BACKUP_DIR = WORK_DIR / "backup"
    TEST_OUTPUT_FILE = WORK_DIR / "test_output.txt"
    JUDGE_FEEDBACK_FILE = WORK_DIR / "judge_feedback.md"

    if "--reset" in flags:
        if WORK_DIR.exists():
            shutil.rmtree(WORK_DIR)
        print("Reset complete.")
        WORK_DIR.mkdir(exist_ok=True)

    if "--retry" in flags and LOG_FILE.exists():
        lines = read_file(LOG_FILE).splitlines()
        cleaned = "\n".join(line for line in lines if "[COMPLETE] Step" not in line)
        write_file(LOG_FILE, cleaned)
        print("Cleared completion markers.")

    if "--dry-run" in flags:
        DRY_RUN = True
        print("Dry-run mode enabled.")

    skip_judge = "--skip-judge" in flags
    skip_verify = "--skip-verify" in flags

    try:
        # If scout_context provided, copy it to SCOUT_FILE instead of running phase_scout
        if scout_context:
            scout_path = Path(scout_context)
            if not scout_path.exists():
                print(f"ERROR: Scout context file not found: {scout_context}")
                sys.exit(1)
            WORK_DIR.mkdir(exist_ok=True)
            shutil.copy(str(scout_path), str(SCOUT_FILE))
            log(f"[SCOUT] Using provided context: {scout_context}")
        else:
            phase_scout(task_file)

        # --- TRIAGE CHECK ---
        scout_output = read_file(SCOUT_FILE)
        triage = parse_triage(scout_output)
        fast_track_succeeded = False

        if should_fast_track(triage):
            log(f"[TRIAGE] FAST_TRACK (confidence={triage.confidence:.2f})")

            # Generate synthetic plan from micro-spec
            write_file(PLAN_FILE, generate_synthetic_plan(triage))

            phase_implement()

            if skip_verify:
                log("[VERIFY] Skipped (--skip-verify flag)")
                fast_track_succeeded = True
            elif not project_has_tests():
                log("[VERIFY] Skipped (no test files in project)")
                fast_track_succeeded = True
            elif verify_and_fix():
                log("[TRIAGE] Fast Track verified. Skipping Judge.")
                fast_track_succeeded = True
            else:
                log("[TRIAGE] Fast Track failed verify. Escalating to Planner...")
                # Fall through to standard path
        # --- END TRIAGE ---

        if not fast_track_succeeded:
            # Standard path (fallback or default)
            phase_plan(task_file)
            phase_implement()
            if skip_verify:
                log("[VERIFY] Skipped (--skip-verify flag)")
            elif not project_has_tests():
                log("[VERIFY] Skipped (no test files in project)")
            elif not verify_and_fix():
                sys.exit(1)

            if not skip_judge and not should_skip_judge():
                phase_judge()
            else:
                if skip_judge:
                    log("[JUDGE] Skipped (--skip-judge flag)")
                # else: should_skip_judge() already logged reason

        # Generate summary (once, after all phases complete)
        plan = read_file(PLAN_FILE)
        summary = run_claude(
            f"Summarize the completed changes in 3-5 bullets.\n\nPlan:\n{plan}",
            model=MODEL_EYES,
            phase="summary",
            timeout=60,
        )
        if summary:
            write_file(NOTES_FILE, summary)
        else:
            log("[SUMMARY] Skipped (timeout)")

        _write_cost_summary()

        print("\n[SUCCESS]")
    except KeyboardInterrupt:
        log("[INTERRUPTED] User cancelled execution")
        print("\nInterrupted. Progress saved to log.")
        sys.exit(130)

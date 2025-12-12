#!/usr/bin/env python3
# Standalone version - copy to project and modify as needed
"""
Zen Mode: The "Anti-Jira" Agent Workflow.

PHILOSOPHY:
1. File System is the Database.
2. Markdown is the API.
3. If a file exists, that step is done.

USAGE:
  python zen.py <TASK_FILE> [flags]

FLAGS:
  --reset     Reset work directory and start fresh
  --retry     Clear completion markers to retry failed steps
  --dry-run   Show what would happen without executing
"""
from __future__ import annotations
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
import tempfile
import unicodedata
from pathlib import Path
from typing import List, Optional, Tuple

# -----------------------------------------------------------------------------
# Regex constants
# -----------------------------------------------------------------------------
_FAIL_STEM = re.compile(r"\bfail", re.IGNORECASE)
_CLAUSE_SPLIT = re.compile(r"[,;|()\[\]{}\n]")
_DIGIT = re.compile(r"\d+")

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
WORK_DIR_NAME = os.getenv("ZEN_WORK_DIR", ".zen")
LINTER_NAME = os.getenv("ZEN_LINTER", "zen_lint.py")
MODEL_BRAIN = os.getenv("ZEN_MODEL_BRAIN", "opus")
MODEL_HANDS = os.getenv("ZEN_MODEL_HANDS", "sonnet")
MODEL_EYES = os.getenv("ZEN_MODEL_EYES", "haiku")
TIMEOUT_EXEC = int(os.getenv("ZEN_TIMEOUT", "600"))
TIMEOUT_LINTER = int(os.getenv("ZEN_LINTER_TIMEOUT", "120"))
TIMEOUT_SUMMARY = int(os.getenv("ZEN_SUMMARY_TIMEOUT", "180"))  # 3 min for summary
MAX_RETRIES = int(os.getenv("ZEN_RETRIES", "2"))
MAX_JUDGE_LOOPS = int(os.getenv("ZEN_JUDGE_LOOPS", "2"))

# Judge skip thresholds (lines changed)
JUDGE_TRIVIAL_LINES = int(os.getenv("ZEN_JUDGE_TRIVIAL", "5"))
JUDGE_SMALL_REFACTOR_LINES = int(os.getenv("ZEN_JUDGE_SMALL", "20"))
JUDGE_SIMPLE_PLAN_LINES = int(os.getenv("ZEN_JUDGE_SIMPLE_LINES", "30"))
JUDGE_SIMPLE_PLAN_STEPS = int(os.getenv("ZEN_JUDGE_SIMPLE_STEPS", "2"))

PROJECT_ROOT = Path.cwd()

ZEN_ID = os.getenv("ZEN_ID", str(os.getpid()))
WORK_DIR_STR = f"{WORK_DIR_NAME}-{ZEN_ID}"
WORK_DIR = PROJECT_ROOT / WORK_DIR_STR

SCOUT_FILE = WORK_DIR / "scout.md"
PLAN_FILE = WORK_DIR / "plan.md"
LOG_FILE = WORK_DIR / "log.md"
NOTES_FILE = WORK_DIR / "final_notes.md"
BACKUP_DIR = WORK_DIR / "backup"
TEST_OUTPUT_FILE = WORK_DIR / "test_output.txt"
TEST_OUTPUT_PATH = WORK_DIR_STR + "/test_output.txt"  # For prompts (forward slash)
JUDGE_FEEDBACK_FILE = WORK_DIR / "judge_feedback.md"

DRY_RUN = False

CLAUDE_EXE = shutil.which("claude") or os.getenv("CLAUDE_EXE")
if not CLAUDE_EXE:
    print("ERROR: 'claude' CLI not found.")
    print("Install: npm i -g @anthropic-ai/claude-cli")
    sys.exit(1)


# -----------------------------------------------------------------------------
# Core Utils
# -----------------------------------------------------------------------------
def log(msg: str) -> None:
    WORK_DIR.mkdir(exist_ok=True)
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


def run_claude(prompt: str, model: str, timeout: Optional[int] = None) -> Optional[str]:
    timeout = timeout or TIMEOUT_EXEC
    if DRY_RUN:
        log(f"[DRY-RUN] Would call {model}")
        return "DRY_RUN_OUTPUT"

    cmd = [CLAUDE_EXE, "-p", "--dangerously-skip-permissions", "--model", model]
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
        stdout, stderr = proc.communicate(input=prompt, timeout=timeout)

        if proc.returncode != 0:
            log(f"[ERROR] Claude ({model}): {stderr[:300]}")
            return None
        return stdout

    except subprocess.TimeoutExpired:
        log(f"[ERROR] Claude ({model}) timed out")
        if proc:
            proc.terminate()
            try:
                proc.communicate(timeout=5)
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


def find_linter() -> Optional[Path]:
    candidates = [
        PROJECT_ROOT / LINTER_NAME,
        Path(sys.argv[0]).resolve().parent / LINTER_NAME,
        Path(__file__).resolve().parent / LINTER_NAME,
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def verify_test_output(output: str) -> bool:
    """
    Verify that agent output contains real test results, not just claims.
    Returns True if genuine test output is detected.
    """
    # Patterns that indicate real test framework output
    real_test_patterns = [
        # pytest (verbose and minimal)
        r"=+\s+\d+\s+passed",
        r"=+\s+passed in \d+",
        r"\d+\s+passed",
        r"passed in [\d.]+s",
        r"PASSED|FAILED|ERROR",
        # npm/jest
        r"Tests:\s+\d+\s+passed",
        r"Test Suites:\s+\d+\s+passed",
        # cargo
        r"test result: ok\.",
        r"running \d+ tests?",
        r"\d+ passed; \d+ failed",
        # go
        r"^ok\s+\S+\s+[\d.]+s",
        r"^PASS$",
        # generic
        r"\d+\s+tests?\s+(passed|succeeded|ok)",
        r"All \d+ tests? passed",
    ]

    for pattern in real_test_patterns:
        if re.search(pattern, output, re.MULTILINE | re.IGNORECASE):
            return True

    return False


def extract_failure_count(output: str) -> Optional[int]:
    """Extract failure count from test output. Language-agnostic."""
    if not output:
        return None

    # Normalize unicode (smart quotes, dashes, etc.)
    norm = unicodedata.normalize("NFKC", output)
    norm = norm.translate({0x2013: 0x2D, 0x2014: 0x2D,
                           0x2019: 0x27, 0x2018: 0x27,
                           0x201C: 0x22, 0x201D: 0x22})

    # Split into a list so we can reverse it
    clauses = _CLAUSE_SPLIT.split(norm)

    # Process from bottom of log to top
    for clause in reversed(clauses):
        if not _FAIL_STEM.search(clause):
            continue

        m = _DIGIT.search(clause)
        if m:
            return int(m.group(0))

    return None


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


def get_changed_filenames() -> str:
    """Get list of changed files for Sonnet context.

    Handles edge cases:
    - No git repo: falls back to backup directory
    - No commits (fresh repo): uses git diff --cached instead of diff HEAD
    - Untracked files: always checks git ls-files --others
    """
    changed_files: set[str] = set()

    if _git_is_repo():
        # Try git diff against HEAD (works if commits exist)
        if _git_has_head():
            try:
                result = subprocess.run(
                    ["git", "diff", "--name-only", "HEAD"],
                    capture_output=True, text=True, cwd=PROJECT_ROOT
                )
                if result.returncode == 0 and result.stdout.strip():
                    changed_files.update(result.stdout.strip().splitlines())
            except Exception:
                pass
        else:
            # No commits yet - use git diff --cached to find staged files
            try:
                result = subprocess.run(
                    ["git", "diff", "--cached", "--name-only"],
                    capture_output=True, text=True, cwd=PROJECT_ROOT
                )
                if result.returncode == 0 and result.stdout.strip():
                    changed_files.update(result.stdout.strip().splitlines())
            except Exception:
                pass

        # Always check for untracked files (works even with no commits)
        try:
            result = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard"],
                capture_output=True, text=True, cwd=PROJECT_ROOT
            )
            if result.returncode == 0 and result.stdout.strip():
                changed_files.update(result.stdout.strip().splitlines())
        except Exception:
            pass

    # Return git-detected files if any
    if changed_files:
        return "\n".join(sorted(changed_files))

    # Fallback: list files from backup directory
    if BACKUP_DIR.exists():
        files = [str(f.relative_to(BACKUP_DIR)) for f in BACKUP_DIR.rglob("*") if f.is_file()]
        if files:
            return "\n".join(files)

    return "[No files detected]"


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
# Phases
# -----------------------------------------------------------------------------
def phase_scout(task_file: str) -> None:
    if SCOUT_FILE.exists():
        log("[SCOUT] Cached. Skipping.")
        return

    log(f"\n[SCOUT] Mapping codebase for {task_file}...")
    prompt = f"""Scout codebase for: {task_file}

OBJECTIVE: Map code relevant to the task. Quality > quantity.

INVESTIGATION:
1. `find . -type f -name "*.py"` (or equivalent for the language)
2. `grep -r` for task-related symbols
3. Read ONLY signatures/exports of key files—never dump full contents

CONSTRAINTS:
- Max 30 files total
- Skip: test*, docs/, **/node_modules/, venv/, migrations/, __pycache__/
- If unsure whether a file matters, include it in Context (not Targeted)

OUTPUT FORMAT (all 4 sections required, use "None" if empty):
## Targeted Files (Must Change)
- `path/to/file.py`: one-line reason

## Context Files (Read-Only)
- `path/to/file.py`: one-line reason

## Deletion Candidates
- `path/to/file.py`: one-line reason

## Open Questions
- Question about ambiguity

OUTPUT ONLY the 4 sections above. No preamble, no commentary, no explanations outside the sections.

Write to: {SCOUT_FILE}"""

    output = run_claude(prompt, model=MODEL_HANDS)
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
    prompt = f"""Create plan for: {task_file}

Scout report:
{scout}

RULES:
- Clean Code > Backward Compatibility
- DELETE old code, no shims
- UPDATE callers directly
- Final step MUST be verification (test/verify/validate)

OUTPUT FORMAT (strict):
## Step 1: <action verb> <specific target>
## Step 2: <action verb> <specific target>
...
## Step N: Verify changes and run tests

Each step: one atomic change. No sub-steps, no bullet lists within steps.
OUTPUT ONLY the steps. No preamble, no commentary.

Write to: {PLAN_FILE}"""

    output = run_claude(prompt, model=MODEL_BRAIN)
    if not output:
        log("[PLAN] Failed.")
        sys.exit(1)

    if not PLAN_FILE.exists():
        write_file(PLAN_FILE, output)

    log("[PLAN] Done.")


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
    linter = find_linter()
    if not linter:
        return True, ""  # No linter = pass

    try:
        result = subprocess.run(
            [sys.executable, str(linter)],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            timeout=TIMEOUT_LINTER
        )
        output = (result.stdout + "\n" + result.stderr).strip()
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, f"Linter timed out after {TIMEOUT_LINTER}s"


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

        base_prompt = f"""Execute Step {step_num}: {step_desc}

IMPORTANT: This is a fresh session with no memory of previous steps.
READ target files first to understand current state before editing.

Full plan:
{plan}

Rules:
- DELETE old code, no shims
- UPDATE callers immediately
- No broken imports

End with: STEP_COMPLETE or STEP_BLOCKED: <reason>"""

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

            output = run_claude(prompt, model=model, timeout=TIMEOUT_EXEC) or ""

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


def phase_verify() -> bool:
    """Returns True if verification passed, False otherwise."""
    log("\n[VERIFY] Running tests...")
    plan = read_file(PLAN_FILE)

    # Versioned output files for user visibility
    last_failure_hash: Optional[str] = None
    stuck_count = 0

    base_prompt = f"""Verify implementation is complete.

IMPORTANT: This is a fresh session. Read files to understand current state.

Plan executed:
{plan}

Actions:
1. Run the project's test suite with minimal output (e.g., pytest -q --tb=short)
2. Write test results to: {TEST_OUTPUT_PATH}
   - If tests PASS: write only the summary line (e.g., "10 passed in 1.23s")
   - If tests FAIL: write failure tracebacks + summary line (no passing test names)
3. If tests fail, fix the issues and re-run

End with exactly: TESTS_PASS or TESTS_FAIL"""

    prompt = base_prompt

    for attempt in range(1, MAX_RETRIES + 2):  # +1 for initial + retries
        output = run_claude(prompt, model=MODEL_HANDS, timeout=TIMEOUT_EXEC)

        if not output:
            log("[VERIFY] No output from agent.")
            return False

        # Check file exists
        if not TEST_OUTPUT_FILE.exists():
            log("[VERIFY] Agent did not write test output file.")
            prompt = base_prompt + "\n\nYou MUST write test output to the file."
            continue

        test_output = read_file(TEST_OUTPUT_FILE)

        # Version the file for user
        versioned = WORK_DIR / f"test_output_{attempt}.txt"
        shutil.copy2(TEST_OUTPUT_FILE, versioned)

        # Verify it looks like real test output
        if not verify_test_output(test_output):
            log("[VERIFY] File doesn't contain valid test output.")
            prompt = base_prompt + "\n\nThe file must contain actual test framework output, not a summary."
            continue

        # Check for failures
        failure_count = extract_failure_count(test_output)

        if failure_count is None or failure_count == 0:
            # Success or can't parse (trust TESTS_PASS marker)
            if "TESTS_PASS" in output:
                log("[VERIFY] Passed.")
                break

        # We have failures - check for progress
        failure_hash = hashlib.md5(test_output.encode()).hexdigest()

        if failure_hash == last_failure_hash:
            stuck_count += 1
            if stuck_count >= 2:
                log(f"[VERIFY] Agent stuck - same failures {stuck_count} times.")
                print(test_output[:500])
                return False
            prompt += "\n\nSame failures as before. Try a DIFFERENT approach."
        else:
            stuck_count = 0  # Reset - making progress
            if last_failure_hash is not None:
                log(f"[VERIFY] Progress: failures changed (attempt {attempt})")

        last_failure_hash = failure_hash
        prompt = f"""Tests still failing. Fix them.

Test output (from {TEST_OUTPUT_PATH}):
{test_output[:2000]}

Write updated test output to: {TEST_OUTPUT_PATH}
End with: TESTS_PASS or TESTS_FAIL"""

    else:
        log(f"[VERIFY] Failed after {MAX_RETRIES} attempts.")
        return False

    # Generate summary
    summary = run_claude(
        f"Summarize changes made. Be concise.\n\nPlan:\n{plan}",
        model=MODEL_EYES,
        timeout=TIMEOUT_SUMMARY,
    )
    if summary:
        write_file(NOTES_FILE, summary)

    return True


def phase_judge() -> None:
    """Judge phase: Review implementation for quality and alignment."""
    log("\n[JUDGE] Senior Architect review...")

    # Gather context
    plan = read_file(PLAN_FILE)
    scout = read_file(SCOUT_FILE)
    test_output = read_file(TEST_OUTPUT_FILE)

    constitution_path = PROJECT_ROOT / "CLAUDE.md"
    constitution = read_file(constitution_path) if constitution_path.exists() else "[No CLAUDE.md found]"

    changed_files = get_changed_filenames()
    if changed_files == "[No files detected]":
        log("[JUDGE] No changes detected. Auto-approving.")
        return

    for loop in range(1, MAX_JUDGE_LOOPS + 1):
        log(f"[JUDGE] Review loop {loop}/{MAX_JUDGE_LOOPS}")

        prompt = f"""You are the Senior Architect. Be direct and concise.

## Plan (Requirements)
{plan}

## Scout (File Context)
{scout}

## Constitution (Rules)
{constitution}

## Test Results
{test_output[:2000]}

## Changed Files
{changed_files}

Use `git diff HEAD -- <file>` or read files directly to review changes.

## Review Criteria
1. **Plan Alignment** - Does the diff satisfy the requirements?
2. **Constitution Adherence** - Any CLAUDE.md rule violations?
3. **Security & Edge Cases** - Obvious vulnerabilities or unhandled cases?

IGNORE: Syntax, formatting, linting (already verified by tooling).

## Output Format

If approved:
```
JUDGE_APPROVED
```

If rejected:
```
JUDGE_REJECTED

## Issues
- Issue 1: [specific problem]
- Issue 2: [specific problem]

## Fix Plan
Step 1: [specific fix action]
Step 2: [specific fix action]
```

Output ONLY the verdict and (if rejected) the issues/fix plan. No preamble."""

        output = run_claude(prompt, model=MODEL_BRAIN, timeout=TIMEOUT_EXEC)

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
        changed_files = get_changed_filenames()

        fix_prompt = f"""JUDGE FEEDBACK - Fixes Required:

{feedback}

## Constitution (CLAUDE.md)
{constitution}

## Changed Files
{changed_files}

## Original Plan
{plan}

IMPORTANT: This is a fresh session. The files listed above were modified.
READ those files first to understand current state before making fixes.

Execute the fixes above. After fixing:
1. Ensure linting passes
2. Ensure tests still pass

End with: FIXES_COMPLETE or FIXES_BLOCKED: <reason>"""

        fix_output = run_claude(fix_prompt, model=MODEL_HANDS, timeout=TIMEOUT_EXEC)

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

        # Re-run verify (tests)
        log("[JUDGE_FIX] Re-verifying tests...")
        if not phase_verify():
            log("[JUDGE_FIX] Tests failed after fixes.")
            sys.exit(1)

        # Update changed files for next judge loop
        changed_files = get_changed_filenames()

        # Clean up feedback file on retry
        if JUDGE_FEEDBACK_FILE.exists():
            JUDGE_FEEDBACK_FILE.unlink()

    # Should not reach here
    log("[JUDGE] Unexpected exit from judge loop.")
    sys.exit(1)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main():
    global DRY_RUN, WORK_DIR, SCOUT_FILE, PLAN_FILE, LOG_FILE, NOTES_FILE, BACKUP_DIR, TEST_OUTPUT_FILE, JUDGE_FEEDBACK_FILE

    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    task_file = sys.argv[1]
    task_path = Path(task_file)
    if not task_path.exists():
        print(f"ERROR: Task file not found: {task_file}")
        sys.exit(1)

    flags = set(sys.argv[2:])

    # Set up paths first (before any flag handling that uses them)
    WORK_DIR = PROJECT_ROOT / WORK_DIR_STR
    SCOUT_FILE = WORK_DIR / "scout.md"
    PLAN_FILE = WORK_DIR / "plan.md"
    LOG_FILE = WORK_DIR / "log.md"
    NOTES_FILE = WORK_DIR / "final_notes.md"
    BACKUP_DIR = WORK_DIR / "backup"
    TEST_OUTPUT_FILE = WORK_DIR / "test_output.txt"
    JUDGE_FEEDBACK_FILE = WORK_DIR / "judge_feedback.md"

    # Handle legacy work dir (without PID suffix) for --reset
    legacy_work_dir = PROJECT_ROOT / WORK_DIR_NAME

    if "--reset" in flags:
        # Clean up only this instance's work directory
        if legacy_work_dir.exists():
            shutil.rmtree(legacy_work_dir)
        if WORK_DIR.exists():
            shutil.rmtree(WORK_DIR)
        print("Reset complete.")
        WORK_DIR.mkdir(exist_ok=True)

    if "--retry" in flags and LOG_FILE.exists():
        lines = read_file(LOG_FILE).splitlines()
        cleaned = "\n".join(l for l in lines if "[COMPLETE] Step" not in l)
        write_file(LOG_FILE, cleaned)
        print("Cleared completion markers.")

    if "--dry-run" in flags:
        DRY_RUN = True
        print("Dry-run mode enabled.")

    skip_judge = "--skip-judge" in flags

    try:
        phase_scout(task_file)
        phase_plan(task_file)
        phase_implement()
        if not phase_verify():
            sys.exit(1)

        if not skip_judge and not should_skip_judge():
            phase_judge()
        else:
            if skip_judge:
                log("[JUDGE] Skipped (--skip-judge flag)")
            # else: should_skip_judge() already logged reason

        print("\n[SUCCESS]")
    except KeyboardInterrupt:
        log("[INTERRUPTED] User cancelled execution")
        print("\nInterrupted. Progress saved to log.")
        sys.exit(130)


if __name__ == "__main__":
    main()
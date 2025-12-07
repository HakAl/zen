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
from pathlib import Path
from typing import List, Optional, Tuple

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
MAX_RETRIES = int(os.getenv("ZEN_RETRIES", "2"))

PROJECT_ROOT = Path.cwd()

ZEN_ID = os.getenv("ZEN_ID", str(os.getpid()))
WORK_DIR = PROJECT_ROOT / f"{WORK_DIR_NAME}-{ZEN_ID}"

SCOUT_FILE = WORK_DIR / "scout.md"
PLAN_FILE = WORK_DIR / "plan.md"
LOG_FILE = WORK_DIR / "log.md"
NOTES_FILE = WORK_DIR / "final_notes.md"
BACKUP_DIR = WORK_DIR / "backup"

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


def run_claude(prompt: str, model: str, timeout: int = 480) -> Optional[str]:
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


# -----------------------------------------------------------------------------
# Test Detection
# -----------------------------------------------------------------------------
def detect_test_command() -> Optional[List[str]]:
    """Auto-detect the test command based on project files."""
    # Explicit pytest config
    if (PROJECT_ROOT / "pytest.ini").exists():
        return [sys.executable, "-m", "pytest"]

    # Check pyproject.toml for pytest config or dependency
    pyproject = PROJECT_ROOT / "pyproject.toml"
    if pyproject.exists():
        content = read_file(pyproject)
        if "[tool.pytest" in content or "pytest" in content.lower():
            return [sys.executable, "-m", "pytest"]

    if (PROJECT_ROOT / "package.json").exists():
        return ["npm", "test"]
    if (PROJECT_ROOT / "Cargo.toml").exists():
        return ["cargo", "test"]
    if (PROJECT_ROOT / "go.mod").exists():
        return ["go", "test", "./..."]
    if (PROJECT_ROOT / "Makefile").exists():
        return ["make", "test"]
    return None


def run_tests() -> Tuple[bool, str]:
    """Run tests directly, don't trust the agent."""
    cmd = detect_test_command()
    if not cmd:
        log("[WARN] No test framework detected. Skipping tests.")
        return True, ""

    if DRY_RUN:
        log(f"[DRY-RUN] Would run: {' '.join(cmd)}")
        return True, ""

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            timeout=TIMEOUT_EXEC
        )
        output = (result.stdout + "\n" + result.stderr).strip()
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, "Test command timed out"
    except Exception as e:
        return False, f"Test execution failed: {e}"


def verify_test_output(output: str) -> bool:
    """
    Verify that agent output contains real test results, not just claims.
    Returns True if genuine test output is detected.
    """
    # Patterns that indicate real test framework output
    real_test_patterns = [
        # pytest
        r"=+\s+\d+\s+passed",
        r"=+\s+passed in \d+",
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

        prompt = f"""Execute Step {step_num}: {step_desc}

IMPORTANT: This is a fresh session with no memory of previous steps.
READ target files first to understand current state before editing.

Full plan:
{plan}

Rules:
- DELETE old code, no shims
- UPDATE callers immediately
- No broken imports

End with: STEP_COMPLETE or STEP_BLOCKED: <reason>"""

        for attempt in range(1, MAX_RETRIES + 1):
            if attempt > 1:
                log(f"  Retry {attempt}/{MAX_RETRIES}...")

            output = run_claude(prompt, model=MODEL_HANDS, timeout=TIMEOUT_EXEC) or ""

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


def phase_verify() -> None:
    log("\n[VERIFY] Running tests...")

    plan = read_file(PLAN_FILE)
    prompt = f"""Verify implementation is complete.

IMPORTANT: This is a fresh session. Read files to understand current state.

Plan executed:
{plan}

Actions:
1. Run the project's test suite
2. Fix any broken tests caused by the changes
3. Show the full test output

End with: TESTS_PASS or TESTS_FAIL

You MUST include the actual test command output in your response."""

    output = run_claude(prompt, model=MODEL_HANDS, timeout=TIMEOUT_EXEC)

    if not output:
        log("[VERIFY] No output from agent.")
        sys.exit(1)

    if "TESTS_PASS" in output:
        if verify_test_output(output):
            log("[VERIFY] Passed (verified).")
        else:
            log("[WARN] Agent claimed TESTS_PASS but no real test output detected.")
            # Run tests ourselves to verify
            passed, test_output = run_tests()
            if passed:
                log("[VERIFY] Independent test run passed.")
            else:
                log("[VERIFY] Independent test run FAILED.")
                print(test_output[:500])
                sys.exit(1)
    else:
        log("[VERIFY] Failed.")
        sys.exit(1)

    # Generate summary
    summary = run_claude(
        f"Summarize changes made. Be concise.\n\nPlan:\n{plan}",
        model=MODEL_EYES,
        timeout=120,
    )
    if summary:
        write_file(NOTES_FILE, summary)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main():
    global DRY_RUN, WORK_DIR, SCOUT_FILE, PLAN_FILE, LOG_FILE, NOTES_FILE, BACKUP_DIR

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
    WORK_DIR = PROJECT_ROOT / f"{WORK_DIR_NAME}-{ZEN_ID}"
    SCOUT_FILE = WORK_DIR / "scout.md"
    PLAN_FILE = WORK_DIR / "plan.md"
    LOG_FILE = WORK_DIR / "log.md"
    NOTES_FILE = WORK_DIR / "final_notes.md"
    BACKUP_DIR = WORK_DIR / "backup"

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

    try:
        phase_scout(task_file)
        phase_plan(task_file)
        phase_implement()
        phase_verify()
        print("\n[SUCCESS]")
    except KeyboardInterrupt:
        log("[INTERRUPTED] User cancelled execution")
        print("\nInterrupted. Progress saved to log.")
        sys.exit(130)


if __name__ == "__main__":
    main()
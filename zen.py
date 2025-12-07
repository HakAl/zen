#!/usr/bin/env python3
"""
Zen Mode: The "Anti-Jira" Agent Workflow.

PHILOSOPHY:
1. File System is the Database.
2. Markdown is API.
3. If a file exists, that step is done.

PREREQUISITES:
- Anthropic 'claude' CLI tool installed and authenticated.
- A 'CLAUDE.md' (optional) in your root for architectural guidelines.

USAGE:
  python zen.py <TASK_FILE> [flags]

FLAGS:
  --reset        Nuke the work directory and start fresh.
  --resume       Clear completion markers to retry failed steps without replanning.
"""
from __future__ import annotations
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
WORK_DIR_NAME = os.getenv("WORK_DIR_NAME", ".zen")
MODEL_BRAIN = os.getenv("MODEL_BRAIN", "opus")
MODEL_HANDS = os.getenv("MODEL_HANDS", "sonnet")
MODEL_EYES = os.getenv("MODEL_EYES", "haiku")
TIMEOUT_EXEC = int(os.getenv("TIMEOUT_EXEC", 600))

PROJECT_ROOT = Path.cwd()
WORK_DIR = PROJECT_ROOT / WORK_DIR_NAME
SCOUT_FILE = WORK_DIR / "scout.md"
PLAN_FILE = WORK_DIR / "plan.md"
LOG_FILE = WORK_DIR / "log.md"
NOTES_FILE = WORK_DIR / "final_notes.md"

CLAUDE_EXE = shutil.which("claude") or os.getenv("CLAUDE_EXE")
if not CLAUDE_EXE:
    print("ERROR: 'claude' CLI not found in PATH.")
    print("Install: npm i -g @anthropic-ai/claude-cli")
    sys.exit(1)


# -----------------------------------------------------------------------------
# Core utils
# -----------------------------------------------------------------------------
def log(msg: str) -> None:
    """Persistent logging to file + stdout."""
    WORK_DIR.mkdir(exist_ok=True)
    ts = time.strftime("%H:%M:%S")
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")
    print(f"  {msg}")


def read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def write_file(path: Path, content: str) -> None:
    """Atomic write to avoid corruption on interrupt."""
    WORK_DIR.mkdir(exist_ok=True)
    content = re.sub(r"\n?#EOF\s*$", "", content)

    # Write to temp file first
    with tempfile.NamedTemporaryFile("w", dir=WORK_DIR, delete=False, encoding="utf-8") as tf:
        tf.write(content)
        tmp_name = tf.name

    # Atomic rename (Windows-safe: file closed, no delete-on-close)
    Path(tmp_name).replace(path)


def run_claude(prompt: str, model: str, timeout: int = 480) -> Optional[str]:
    """Run Claude in a clean subprocess using Popen for signal control."""
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
            log(f"[ERROR] Claude ({model}): {stderr[:500]}")
            return None
        return stdout

    except subprocess.TimeoutExpired:
        log(f"[ERROR] Claude ({model}) timed out")
        if proc:
            proc.kill()  # Sends SIGTERM
            proc.communicate()  # Reap zombie process
        return None
    except Exception as e:
        log(f"[ERROR] Subprocess: {e}")
        if proc:
            proc.kill()
            proc.communicate()
        return None


# -----------------------------------------------------------------------------
# Phases
# -----------------------------------------------------------------------------
def phase_1_scout(task_file: str) -> None:
    if SCOUT_FILE.exists():
        log("[SCOUT] Found existing report. Skipping.")
        return
    log(f"\n[SCOUT] Investigating {task_file}...")
    prompt = f"""TASK: Scout the codebase for: {task_file}
CONTEXT: Existing Project.
GOAL: Map the files. Do NOT plan yet.

ACTIONS:
1. `ls -R`, `find`, `grep` to find relevant files.
2. Read code to understand dependencies.
3. Identify what to DELETE (Clean Code policy).

OUTPUT: Write report to {SCOUT_FILE}
End with: #EOF
"""
    output = run_claude(prompt, model=MODEL_HANDS)
    if output and SCOUT_FILE.exists():
        log("[SCOUT] Complete.")
    else:
        log("[SCOUT] Failed to generate report.")
        sys.exit(1)


def phase_2_plan(task_file: str) -> None:
    if PLAN_FILE.exists():
        log("[PLAN] Found existing plan. Skipping.")
        return
    log("\n[PLAN] Drafting Architecture...")
    scout_data = read_file(SCOUT_FILE)
    prompt = f"""TASK: Create execution plan for {task_file}
CONTEXT: "Clean Code" > "Backward Compatibility".

SCOUT REPORT:
{scout_data}

REQUIRED:
1. Create a numbered list of ATOMIC steps (Step 1, Step 2...).
2. "DELETE file X" (No deprecation).
3. "UPDATE callers" (No adapters).
4. Include a final Verification step.

OUTPUT: Write to {PLAN_FILE}
End with: #EOF
"""
    output = run_claude(prompt, model=MODEL_BRAIN)
    if output and PLAN_FILE.exists():
        log("[PLAN] Complete.")
    else:
        log("[PLAN] Failed to generate plan.")
        sys.exit(1)


def _parse_steps(plan: str) -> List[Tuple[str, str]]:
    pattern = re.compile(
        r"(?:^|\n)(?:#{1,6}\s*)?(?:Step\s+(\d+)|(\d+)\.)[:\s]+(.*?)(?=\n(?:#{1,6}\s*)?(?:Step\s+\d+|\d+\.)|$)",
        re.DOTALL | re.IGNORECASE,
    )
    return [(m[0] or m[1], m[2].strip()) for m in pattern.findall(plan + "\n")]


def phase_3_implement() -> None:
    plan_content = read_file(PLAN_FILE)
    steps = _parse_steps(plan_content)

    if not steps:
        bullets = re.findall(r"(?:^|\n)[-*]\s+(.*?)(?=\n[-*]|$)", plan_content)
        steps = [(str(i), txt.strip()) for i, txt in enumerate(bullets, 1) if txt.strip()]

    log(f"\n[IMPLEMENT] Found {len(steps)} steps.")

    # -------------------------------------------------------------------------
    # RESUME LOGIC
    # -------------------------------------------------------------------------
    completed_steps = set()
    if LOG_FILE.exists():
        log_content = read_file(LOG_FILE)
        # 1. Trust explicit markers
        explicit_matches = re.findall(r"\[COMPLETE\] Step\s+(\d+)\b", log_content)
        completed_steps.update(int(m) for m in explicit_matches)

        # 2. Heuristic: If we see "[STEP 10]", assume 1..9 are done
        started_matches = re.findall(r"\[STEP\s+(\d+)\]", log_content)
        if started_matches:
            max_started = max(int(m) for m in started_matches)
            # We assume the *last* started step failed, so we resume from it.
            # Mark everything before it as done.
            for i in range(1, max_started):
                completed_steps.add(i)

    # -------------------------------------------------------------------------

    for idx, (step_num, step_text) in enumerate(steps, 1):
        if idx in completed_steps:
            # Quietly skip
            continue

        log(f"\n[STEP {idx}] {step_text[:80]}...")
        prompt = f"""TASK: Implement Step {idx}
STEP: {step_text}
FULL PLAN: {plan_content}

RULES:
1. DELETE old code (No shims).
2. Update callers immediately.
3. No broken imports.
4. If the step mentions specific line numbers, locate the code by context.

CRITICAL: WRITE CODE or DELETE FILES.
End with: STEP_COMPLETE or STEP_BLOCKED: <reason>
"""
        for attempt in range(1, 3):
            if attempt > 1:
                log(f"  [RETRY] Attempt {attempt}...")

            output = run_claude(prompt, model=MODEL_HANDS, timeout=TIMEOUT_EXEC) or ""

            if "STEP_COMPLETE" in output:
                # -------------------------------------------------------------
                # LINTING BLOCK (FIXED)
                # -------------------------------------------------------------
                lint_path = PROJECT_ROOT / "zen_lint.py"

                # Fallback: Check if linter is in the same folder as this script
                if not lint_path.exists():
                    script_dir = Path(sys.argv[0]).resolve().parent
                    possible_path = script_dir / "zen_lint.py"
                    if possible_path.exists():
                        lint_path = possible_path

                if not lint_path.exists():
                    log("[WARN] zen_lint.py not found. Skipping validation.")
                    # We accept the step because we can't check it
                    log(f"[COMPLETE] Step {idx}")
                    break

                # Run Linter and Capture STDERR
                lint_res = subprocess.run(
                    [sys.executable, str(lint_path)],
                    capture_output=True,
                    text=True,
                    cwd=PROJECT_ROOT
                )

                if lint_res.returncode != 0:
                    # Capture both Stdout and Stderr to see crashes/errors
                    error_msg = (lint_res.stdout + "\n" + lint_res.stderr).strip()

                    log(f"[LINT FAIL] Step {idx} validation failed.")
                    # Print indented for readability
                    print("\n".join(f"    {line}" for line in error_msg.splitlines()))

                    # Feedback to Agent
                    prompt += f"\n\nCRITICAL: Your changes failed the Clean Code Linter.\n{error_msg}\n\nFIX: Remove the prohibited patterns shown above."
                    continue
                # -------------------------------------------------------------

                log(f"[COMPLETE] Step {idx}")
                break

            if "STEP_BLOCKED" in output:
                log(f"[BLOCKED] Step {idx}")
                print(f"\n--- BLOCKED: Step {idx} ---\n{output}")
                sys.exit(1)
        else:
            log(f"[FAILED] Step {idx}")
            sys.exit(1)


def phase_4_verify() -> None:
    log("\n[VERIFY] Running Tests...")
    prompt = f"""Run tests (pytest) and verify app loads.
If tests fail due to deleted code, UPDATE THE TEST.
End with: TESTS_PASS or TESTS_FAIL
"""
    output = run_claude(prompt, model=MODEL_HANDS, timeout=TIMEOUT_EXEC)

    if output and "TESTS_PASS" in output:
        log("[VERIFY] Passed.")
    else:
        log("[VERIFY] Failed.")
        sys.exit(1)

    summary = run_claude(
        f"Summarize changes. Write to {NOTES_FILE}. End with #EOF",
        model=MODEL_EYES,
        timeout=120,
    )
    if summary:
        write_file(NOTES_FILE, summary)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python zen.py <TASK_FILE> [flags]")
        print("  (no flags)     Resume automatically (skips completed steps)")
        print("  --reset        Nuke everything and start fresh")
        print("  --retry        Clear step completion markers to force re-run")
        sys.exit(1)

    task_file = sys.argv[1]

    # Flag: Nuke everything
    if "--reset" in sys.argv and WORK_DIR.exists():
        shutil.rmtree(WORK_DIR)
        print("Reset complete.")

    # Flag: Clear implementation progress only (keep Plan/Scout)
    if "--retry" in sys.argv and LOG_FILE.exists():
        print("Retry mode: clearing completion markers...")
        lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
        # Filter out "[COMPLETE] Step X" lines so they run again
        cleaned = "\n".join(l for l in lines if "[COMPLETE] Step" not in l) + "\n"
        LOG_FILE.write_text(cleaned, encoding="utf-8")

    try:
        phase_1_scout(task_file)
        phase_2_plan(task_file)
        phase_3_implement()
        phase_4_verify()
        print("\nSUCCESS.")
    except KeyboardInterrupt:
        print("\nStopped.")
        sys.exit(130)
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)
"""Judge phase: Architectural review of implementation."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple, List

from zen_mode import utils
from zen_mode.config import (
    MODEL_BRAIN,
    MODEL_HANDS,
    TIMEOUT_EXEC,
    MAX_JUDGE_LOOPS,
    JUDGE_TRIVIAL_LINES,
    JUDGE_SMALL_REFACTOR_LINES,
    JUDGE_SIMPLE_PLAN_LINES,
    JUDGE_SIMPLE_PLAN_STEPS,
    PROJECT_ROOT,
    WORK_DIR,
)
from zen_mode.plan import parse_steps
from zen_mode.utils import Context, read_file, write_file, run_claude
from zen_mode.verify import VerifyState, phase_verify


# -----------------------------------------------------------------------------
# Git Helpers
# -----------------------------------------------------------------------------
def _git_has_head(project_root: Path) -> bool:
    """Check if git repo has at least one commit (HEAD exists)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=project_root
        )
        return result.returncode == 0
    except Exception:
        return False


def _git_is_repo(project_root: Path) -> bool:
    """Check if we're in a git repository."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True, text=True, cwd=project_root
        )
        return result.returncode == 0
    except Exception:
        return False


def _is_test_or_doc(path: str) -> bool:
    """Check if path is a test or documentation file."""
    return (path.endswith(('.md', '.txt', '.rst')) or
            '/test' in path or path.startswith('test') or
            '_test.' in path or 'test_' in path)


# -----------------------------------------------------------------------------
# Judge Prompt Builders
# -----------------------------------------------------------------------------
def build_judge_prompt(plan: str, scout: str, constitution: str,
                       test_output: str, changed_files: str) -> str:
    """Build prompt for judge review."""
    return f"""<role>Senior Architect. Be direct and concise.</role>

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


def build_judge_fix_prompt(feedback: str, constitution: str,
                           changed_files: str, plan: str) -> str:
    """Build prompt for judge fix phase."""
    return f"""<task>
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


# -----------------------------------------------------------------------------
# Skip Judge Logic
# -----------------------------------------------------------------------------
def should_skip_judge_ctx(ctx: Context, log_fn: Optional[callable] = None) -> bool:
    """Determine if judge phase can be skipped.

    Args:
        ctx: Execution context
        log_fn: Optional logging function

    Returns:
        True if judge can be skipped, False otherwise
    """
    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    if not _git_is_repo(ctx.project_root):
        return False  # Fail-safe: require judge if not a git repo

    # Get modified files (tracked)
    numstat = ""
    if _git_has_head(ctx.project_root):
        try:
            result = subprocess.run(
                ["git", "diff", "--numstat", "HEAD"],
                capture_output=True, text=True, cwd=ctx.project_root
            )
            if result.returncode == 0:
                numstat = result.stdout.strip()
        except Exception:
            pass
    else:
        try:
            result = subprocess.run(
                ["git", "diff", "--cached", "--numstat"],
                capture_output=True, text=True, cwd=ctx.project_root
            )
            if result.returncode == 0:
                numstat = result.stdout.strip()
        except Exception:
            pass

    # Get untracked files
    untracked = ""
    try:
        untracked_result = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, cwd=ctx.project_root
        )
        if untracked_result.returncode == 0:
            untracked = untracked_result.stdout.strip()
    except Exception:
        pass

    if not numstat and not untracked:
        _log("[JUDGE] Skipping: No changes detected")
        return True

    if not numstat and untracked:
        untracked_files = untracked.splitlines()
        if not all(_is_test_or_doc(f) for f in untracked_files):
            _log("[JUDGE] Required: New code files created")
            return False
        _log("[JUDGE] Skipping: Only new test/doc files")
        return True

    # Parse numstat
    total_add, total_del = 0, 0
    changed_files: List[str] = []

    for line in numstat.splitlines():
        parts = line.split('\t')
        if len(parts) >= 3:
            add = int(parts[0]) if parts[0] != '-' else 0
            delete = int(parts[1]) if parts[1] != '-' else 0
            total_add += add
            total_del += delete
            changed_files.append(parts[2])

    if untracked:
        changed_files.extend(untracked.splitlines())

    total_changes = total_add + total_del
    has_new_code_files = untracked and not all(_is_test_or_doc(f) for f in untracked.splitlines())

    # Rule B: Risky files always reviewed
    risky_patterns = ['auth', 'login', 'secur', 'payment', 'crypt', 'secret', 'token']
    for f in changed_files:
        if any(r in f.lower() for r in risky_patterns):
            _log(f"[JUDGE] Required: Sensitive file ({f})")
            return False

    # Rule A: Typo fix threshold
    if total_changes < JUDGE_TRIVIAL_LINES and not has_new_code_files:
        _log(f"[JUDGE] Skipping: Trivial ({total_changes} lines)")
        return True

    # Rule C: Pure docs/tests exempt
    if all(_is_test_or_doc(f) for f in changed_files):
        _log("[JUDGE] Skipping: Only docs/tests changed")
        return True

    # Rule D: Small refactor + simple plan
    plan = read_file(ctx.plan_file)
    steps = parse_steps(plan)
    if len(steps) <= JUDGE_SIMPLE_PLAN_STEPS and total_changes < JUDGE_SIMPLE_PLAN_LINES and not has_new_code_files:
        _log(f"[JUDGE] Skipping: Simple ({len(steps)} steps, {total_changes} lines)")
        return True

    if total_changes < JUDGE_SMALL_REFACTOR_LINES and not has_new_code_files:
        _log(f"[JUDGE] Skipping: Small refactor ({total_changes} lines)")
        return True

    return False


# -----------------------------------------------------------------------------
# Judge Phase (Context-based API)
# -----------------------------------------------------------------------------
def phase_judge_ctx(ctx: Context) -> None:
    """Execute judge phase using Context object.

    Args:
        ctx: Execution context
    """
    _log_ctx(ctx, "\n[JUDGE] Senior Architect review...")

    plan = read_file(ctx.plan_file)
    scout = read_file(ctx.scout_file)
    test_output = read_file(ctx.test_output_file)

    constitution_path = ctx.project_root / "CLAUDE.md"
    constitution = read_file(constitution_path) if constitution_path.exists() else "[No CLAUDE.md found]"

    changed_files = utils.get_changed_filenames(ctx.project_root, ctx.backup_dir)
    if changed_files == "[No files detected]":
        _log_ctx(ctx, "[JUDGE] No changes detected. Auto-approving.")
        return

    judge_feedback_file = ctx.work_dir / "judge_feedback.md"

    for loop in range(1, MAX_JUDGE_LOOPS + 1):
        _log_ctx(ctx, f"[JUDGE] Review loop {loop}/{MAX_JUDGE_LOOPS}")

        prompt = build_judge_prompt(plan, scout, constitution, test_output, changed_files)

        output = run_claude(
            prompt,
            model=MODEL_BRAIN,
            phase="judge",
            timeout=TIMEOUT_EXEC,
            project_root=ctx.project_root,
            log_fn=lambda msg: _log_ctx(ctx, msg),
            cost_callback=ctx.record_cost,
        )

        if not output:
            _log_ctx(ctx, "[JUDGE] No response from Judge.")
            try:
                choice = input(">> Judge failed. Proceed anyway? [y/N]: ").strip().lower()
                if choice == 'y':
                    _log_ctx(ctx, "[JUDGE] User approved proceeding without review.")
                    return
            except EOFError:
                pass
            _log_ctx(ctx, "[JUDGE] Aborting (fail-closed).")
            sys.exit(1)

        if "JUDGE_APPROVED" in output:
            _log_ctx(ctx, "[JUDGE_APPROVED] Code passed architectural review.")
            return

        if "JUDGE_REJECTED" not in output:
            _log_ctx(ctx, "[JUDGE] Unclear verdict from Judge.")
            try:
                choice = input(">> Judge gave unclear verdict. Proceed anyway? [y/N]: ").strip().lower()
                if choice == 'y':
                    _log_ctx(ctx, "[JUDGE] User approved proceeding despite unclear verdict.")
                    return
            except EOFError:
                pass
            _log_ctx(ctx, "[JUDGE] Aborting (fail-closed).")
            sys.exit(1)

        _log_ctx(ctx, f"[JUDGE_REJECTED] Issues found (loop {loop})")

        feedback = output.split("JUDGE_REJECTED", 1)[-1].strip()
        write_file(judge_feedback_file, feedback, ctx.work_dir)

        for line in feedback.splitlines()[:10]:
            print(f"    {line}")

        if loop >= MAX_JUDGE_LOOPS:
            _log_ctx(ctx, "[ESCALATE_TO_HUMAN] Max judge loops reached. Manual review required.")
            _log_ctx(ctx, f"[INFO] Judge feedback saved to: {judge_feedback_file}")
            sys.exit(1)

        _log_ctx(ctx, "[JUDGE_FIX] Applying fixes...")
        changed_files = utils.get_changed_filenames(ctx.project_root, ctx.backup_dir)

        fix_prompt = build_judge_fix_prompt(feedback, constitution, changed_files, plan)

        fix_output = run_claude(
            fix_prompt,
            model=MODEL_HANDS,
            phase="judge_fix",
            timeout=TIMEOUT_EXEC,
            project_root=ctx.project_root,
            log_fn=lambda msg: _log_ctx(ctx, msg),
            cost_callback=ctx.record_cost,
        )

        if not fix_output:
            _log_ctx(ctx, "[JUDGE_FIX] No response from fixer.")
            sys.exit(1)

        if "FIXES_BLOCKED" in fix_output:
            _log_ctx(ctx, "[JUDGE_FIX] Fixes blocked. Manual intervention required.")
            sys.exit(1)

        # Re-run linter
        from zen_mode.implement import run_linter_with_timeout
        passed, lint_out = run_linter_with_timeout()
        if not passed:
            _log_ctx(ctx, "[JUDGE_FIX] Lint failed after fixes.")
            for line in lint_out.splitlines()[:10]:
                print(f"    {line}")
            sys.exit(1)

        # Re-run verify
        _log_ctx(ctx, "[JUDGE_FIX] Checking tests...")
        state, _ = phase_verify()
        if state == VerifyState.FAIL:
            _log_ctx(ctx, "[JUDGE_FIX] Tests failed after fixes.")
            sys.exit(1)
        elif state == VerifyState.ERROR:
            _log_ctx(ctx, "[JUDGE_FIX] Test runner error.")
            sys.exit(1)
        elif state == VerifyState.RUNTIME_MISSING:
            _log_ctx(ctx, "[JUDGE_FIX] Runtime not installed, skipping tests.")

        changed_files = utils.get_changed_filenames(ctx.project_root, ctx.backup_dir)

        if judge_feedback_file.exists():
            judge_feedback_file.unlink()

    _log_ctx(ctx, "[JUDGE] Unexpected exit from judge loop.")
    sys.exit(1)


def _log_ctx(ctx: Context, msg: str) -> None:
    """Log using context's log file."""
    from zen_mode.utils import log
    log(msg, ctx.log_file, ctx.work_dir)

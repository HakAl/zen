"""Judge phase: Architectural review of implementation."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

from zen_mode import git
from zen_mode.claude import run_claude
from zen_mode.config import (
    MODEL_BRAIN,
    MODEL_HANDS,
    TIMEOUT_EXEC,
    MAX_JUDGE_LOOPS,
    JUDGE_TRIVIAL_LINES,
    JUDGE_SMALL_REFACTOR_LINES,
    JUDGE_SIMPLE_PLAN_LINES,
    JUDGE_SIMPLE_PLAN_STEPS,
)
from zen_mode.context import Context
from zen_mode.exceptions import JudgeError
from zen_mode.files import write_file, get_full_constitution, log
from zen_mode.plan import parse_steps
from zen_mode.verify import VerifyState, phase_verify


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
def should_skip_judge_ctx(ctx: Context, log_fn: Optional[Callable[[str], None]] = None) -> bool:
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

    if not git.is_repo(ctx.project_root):
        return False  # Fail-safe: require judge if not a git repo

    # Get diff stats and untracked files
    stats = git.get_diff_stats(ctx.project_root)
    untracked_files = git.get_untracked_files(ctx.project_root)

    if stats.total == 0 and not untracked_files:
        _log("[JUDGE] Skipping: No changes detected")
        return True

    if stats.total == 0 and untracked_files:
        if not all(_is_test_or_doc(f) for f in untracked_files):
            _log("[JUDGE] Required: New code files created")
            return False
        _log("[JUDGE] Skipping: Only new test/doc files")
        return True

    # Combine tracked and untracked files
    changed_files: List[str] = stats.files + untracked_files
    total_changes = stats.total
    has_new_code_files = untracked_files and not all(_is_test_or_doc(f) for f in untracked_files)

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
    plan = ctx.plan_file.read_text(encoding="utf-8")
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
def phase_judge_ctx(ctx: Context, non_interactive: bool = False) -> None:
    """Execute judge phase using Context object.

    Args:
        ctx: Execution context
        non_interactive: If True, skip input() prompts and fail-closed
    """
    ctx.log( "\n[JUDGE] Senior Architect review...")

    plan = ctx.plan_file.read_text(encoding="utf-8")
    scout = ctx.scout_file.read_text(encoding="utf-8")
    test_output = ctx.test_output_file.read_text(encoding="utf-8") if ctx.test_output_file.exists() else ""

    # Get full constitution: zen defaults + project CLAUDE.md (or AGENTS.md)
    constitution = get_full_constitution(ctx.project_root, "GOLDEN RULES", "ARCHITECTURE", "CODE STYLE", "TESTING")

    changed_files = git.get_changed_filenames(ctx.project_root, ctx.backup_dir)
    if changed_files == "[No files detected]":
        ctx.log( "[JUDGE] No changes detected. Auto-approving.")
        return

    judge_feedback_file = ctx.work_dir / "judge_feedback.md"

    for loop in range(1, MAX_JUDGE_LOOPS + 1):
        ctx.log( f"[JUDGE] Review loop {loop}/{MAX_JUDGE_LOOPS}")

        prompt = build_judge_prompt(plan, scout, constitution, test_output, changed_files)

        output = run_claude(
            prompt,
            model=MODEL_BRAIN,
            phase="judge",
            timeout=TIMEOUT_EXEC,
            project_root=ctx.project_root,
            log_fn=ctx.log,
            cost_callback=ctx.record_cost,
        )

        if not output:
            ctx.log( "[JUDGE] No response from Judge.")
            if non_interactive:
                ctx.log( "[JUDGE] Non-interactive mode: auto-failing (fail-closed).")
                raise JudgeError("Judge failed in non-interactive mode (fail-closed)")
            try:
                choice = input(">> Judge failed. Proceed anyway? [y/N]: ").strip().lower()
                if choice == 'y':
                    ctx.log( "[JUDGE] User approved proceeding without review.")
                    return
            except EOFError:
                pass
            ctx.log( "[JUDGE] Aborting (fail-closed).")
            raise JudgeError("Judge aborted by user (fail-closed)")

        if "JUDGE_APPROVED" in output:
            ctx.log( "[JUDGE_APPROVED] Code passed architectural review.")
            return

        if "JUDGE_REJECTED" not in output:
            ctx.log( "[JUDGE] Unclear verdict from Judge.")
            if non_interactive:
                ctx.log( "[JUDGE] Non-interactive mode: auto-failing (fail-closed).")
                raise JudgeError("Judge unclear verdict in non-interactive mode (fail-closed)")
            try:
                choice = input(">> Judge gave unclear verdict. Proceed anyway? [y/N]: ").strip().lower()
                if choice == 'y':
                    ctx.log( "[JUDGE] User approved proceeding despite unclear verdict.")
                    return
            except EOFError:
                pass
            ctx.log( "[JUDGE] Aborting (fail-closed).")
            raise JudgeError("Judge aborted by user - unclear verdict (fail-closed)")

        ctx.log( f"[JUDGE_REJECTED] Issues found (loop {loop})")

        feedback = output.split("JUDGE_REJECTED", 1)[-1].strip()
        write_file(judge_feedback_file, feedback, ctx.work_dir)

        for line in feedback.splitlines()[:10]:
            logger.info(f"    {line}")

        if loop >= MAX_JUDGE_LOOPS:
            ctx.log( "[ESCALATE_TO_HUMAN] Max judge loops reached. Manual review required.")
            ctx.log( f"[INFO] Judge feedback saved to: {judge_feedback_file}")
            raise JudgeError("Max judge loops reached - manual review required")

        ctx.log( "[JUDGE_FIX] Applying fixes...")
        changed_files = git.get_changed_filenames(ctx.project_root, ctx.backup_dir)

        fix_prompt = build_judge_fix_prompt(feedback, constitution, changed_files, plan)

        fix_output = run_claude(
            fix_prompt,
            model=MODEL_HANDS,
            phase="judge_fix",
            timeout=TIMEOUT_EXEC,
            project_root=ctx.project_root,
            log_fn=ctx.log,
            cost_callback=ctx.record_cost,
        )

        if not fix_output:
            ctx.log( "[JUDGE_FIX] No response from fixer.")
            raise JudgeError("No response from fixer")

        if "FIXES_BLOCKED" in fix_output:
            ctx.log( "[JUDGE_FIX] Fixes blocked. Manual intervention required.")
            raise JudgeError("Fixes blocked - manual intervention required")

        # Re-run linter
        from zen_mode.implement import run_linter_with_timeout
        passed, lint_out = run_linter_with_timeout()
        if not passed:
            ctx.log( "[JUDGE_FIX] Lint failed after fixes.")
            for line in lint_out.splitlines()[:10]:
                logger.info(f"    {line}")
            raise JudgeError("Lint check failed after judge fixes")

        # Re-run verify
        ctx.log( "[JUDGE_FIX] Checking tests...")
        state, _ = phase_verify(ctx)
        if state == VerifyState.FAIL:
            ctx.log( "[JUDGE_FIX] Tests failed after fixes.")
            raise JudgeError("Tests failed after judge fixes")
        elif state == VerifyState.ERROR:
            ctx.log( "[JUDGE_FIX] Test runner error.")
            raise JudgeError("Test runner error after judge fixes")
        elif state == VerifyState.RUNTIME_MISSING:
            ctx.log( "[JUDGE_FIX] Runtime not installed, skipping tests.")

        changed_files = git.get_changed_filenames(ctx.project_root, ctx.backup_dir)

        if judge_feedback_file.exists():
            judge_feedback_file.unlink()

    ctx.log( "[JUDGE] Unexpected exit from judge loop.")
    raise JudgeError("Unexpected exit from judge loop")



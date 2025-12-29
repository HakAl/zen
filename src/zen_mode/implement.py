"""Implement phase: Execute plan steps."""
from __future__ import annotations

import hashlib
import logging
import re
import sys
import threading
from pathlib import Path
from typing import List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

from zen_mode import git, linter
from zen_mode.claude import run_claude
from zen_mode.config import (
    MODEL_BRAIN,
    MODEL_HANDS,
    TIMEOUT_EXEC,
    TIMEOUT_LINTER,
    MAX_RETRIES,
)
from zen_mode.context import Context
from zen_mode.exceptions import ImplementError
from zen_mode.files import backup_file, get_full_constitution, log
from zen_mode.plan import parse_steps, get_completed_steps


# -----------------------------------------------------------------------------
# Linter Integration
# -----------------------------------------------------------------------------
def run_linter_with_timeout(timeout: Optional[int] = None, paths: Optional[List[str]] = None) -> Tuple[bool, str]:
    """Run the linter with timeout.

    Args:
        timeout: Timeout in seconds (default from config)
        paths: Files to lint (default: git changed files)

    Returns:
        Tuple of (passed, output)
    """
    timeout = timeout or TIMEOUT_LINTER
    result: List = [False, f"Linter timed out after {timeout}s"]

    # Get changed files from git if no paths provided
    if paths is None:
        paths = git.get_changed_files(Path.cwd())

    def target():
        result[0], result[1] = linter.run_lint(paths=paths)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        return False, f"Linter timed out after {timeout}s"

    return result[0], result[1]


# -----------------------------------------------------------------------------
# Backup Utilities
# -----------------------------------------------------------------------------
def backup_scout_files_ctx(ctx: Context) -> None:
    """Backup files identified in scout phase before modification.

    Args:
        ctx: Execution context
    """
    scout = ctx.scout_file.read_text(encoding="utf-8") if ctx.scout_file.exists() else ""
    if not scout:
        return

    file_pattern = re.compile(r"`([^`]+\.\w+)`")
    for match in file_pattern.finditer(scout):
        filepath = ctx.project_root / match.group(1)
        if filepath.exists() and filepath.is_file():
            backup_file(
                filepath,
                ctx.backup_dir,
                ctx.project_root,
                log_fn=ctx.log
            )


# -----------------------------------------------------------------------------
# Step Context Helpers
# -----------------------------------------------------------------------------
def extract_plan_goal(plan: str) -> str:
    """Extract the Goal line from a plan.

    Plans follow format: **Goal:** [description]
    Returns the goal text or a fallback.
    """
    match = re.search(r'\*\*Goal:\*\*\s*(.+?)(?:\n|$)', plan)
    if match:
        return match.group(1).strip()
    # Fallback: first non-empty line after header
    lines = [l.strip() for l in plan.split('\n') if l.strip() and not l.startswith('#')]
    return lines[0][:100] if lines else "Complete the implementation"


def get_step_context(steps: List[Tuple[int, str]], current_idx: int) -> dict:
    """Get navigation context for a step.

    Args:
        steps: List of (step_num, step_desc) tuples
        current_idx: Index of current step in the list

    Returns:
        Dict with 'prev', 'next', 'total' keys
    """
    total = len(steps)
    prev_desc = steps[current_idx - 1][1][:80] if current_idx > 0 else None
    next_desc = steps[current_idx + 1][1][:80] if current_idx < total - 1 else None
    return {
        'prev': prev_desc,
        'next': next_desc,
        'total': total,
    }


# -----------------------------------------------------------------------------
# Implement Prompt Builders
# -----------------------------------------------------------------------------
def build_verify_prompt(step_desc: str, plan: str, goal: Optional[str] = None,
                        include_full_plan: bool = False) -> str:
    """Build prompt for verification-only step.

    Args:
        step_desc: Step description to verify
        plan: Full plan text (used if include_full_plan=True)
        goal: Extracted goal from plan
        include_full_plan: If True, include full plan
    """
    if include_full_plan:
        context_block = f"""<context>
Full plan:
{plan}
</context>"""
    else:
        goal_text = goal or "Verify the implementation"
        context_block = f"""<context>
Goal: {goal_text}

If you need more context, READ .zen/plan.md for the full plan.
</context>"""

    return f"""<task>
Verify that the task described below is already complete.
</task>

<verification>
{step_desc}
</verification>

{context_block}

<instructions>
1. READ the relevant files to confirm the task is complete
2. If complete, explain what was already in place
3. If NOT complete, explain what's missing

Do NOT make any changes. This is verification only.
</instructions>

<output>
End with: STEP_COMPLETE (if verified) or STEP_BLOCKED: <reason> (if not complete)
</output>"""


def build_implement_prompt(step_num: int, step_desc: str, plan: str,
                           project_root: Path, allowed_files: Optional[str] = None,
                           step_context: Optional[dict] = None, goal: Optional[str] = None,
                           include_full_plan: bool = False) -> str:
    """Build prompt for implementation step.

    Args:
        step_num: Current step number
        step_desc: Current step description
        plan: Full plan text (used for full_plan mode or fallback)
        project_root: Project root path
        allowed_files: Optional glob pattern for allowed files
        step_context: Dict with 'prev', 'next', 'total' keys for navigation
        goal: Extracted goal from plan
        include_full_plan: If True, include full plan (for escalation/retry)
    """
    constitution = get_full_constitution(project_root, "GOLDEN RULES", "CODE STYLE", "TESTING")

    # Build navigation context
    if step_context and not include_full_plan:
        total = step_context.get('total', '?')
        prev = step_context.get('prev')
        next_step = step_context.get('next')

        nav_lines = []
        if prev:
            nav_lines.append(f"Previous: {prev}")
        if next_step:
            nav_lines.append(f"Next: {next_step}")
        else:
            nav_lines.append("Next: (final step)")

        navigation = "\n".join(nav_lines)
        goal_text = goal or "Complete the implementation"

        context_block = f"""<context>
Step {step_num} of {total}: {step_desc}

Goal: {goal_text}

<navigation>
{navigation}
</navigation>

READ target files first to understand current state before editing.
</context>

<recovery>
If blocked or need more context:
1. READ .zen/plan.md for full implementation plan
2. READ .zen/scout.md for codebase context
3. Output STEP_BLOCKED: <reason> if still stuck
</recovery>"""
    else:
        # Full plan mode (escalation, retry, or no step_context)
        context_block = f"""<context>
IMPORTANT: This is a fresh session with no memory of previous steps.
READ target files first to understand current state before editing.

Full plan:
{plan}
</context>"""

    base = f"""<task>
Execute Step {step_num}: {step_desc}
</task>

{context_block}

<constitution>
{constitution}
</constitution>

<preflight>
Before making any changes, verify:
1. Can you read the source files you need to edit? (FILES)
2. Is the task clearly defined with enough detail to implement? (TASK)

Output: PREFLIGHT: FILES=YES/NO, TASK=YES/NO

If either is NO, output STEP_BLOCKED: <reason> and stop immediately.
Do not attempt to implement with missing files or unclear requirements.
</preflight>

<EXAMPLES>
BAD (scope creep - task was "add retry logic"):
- Added retry logic
- Also added logging framework
- Also refactored error handling
- Also added config file support
- Created 5 new helper functions

GOOD (minimal complete - same task):
- Added retry logic with 3 attempts
- Used existing logger
- Done
</EXAMPLES>

<output>
End with: STEP_COMPLETE or STEP_BLOCKED: <reason>
</output>"""

    if allowed_files:
        base += f"""

<SCOPE>
You MUST ONLY modify files matching this glob pattern:
{allowed_files}

Do not create, modify, or delete any files outside this scope.
</SCOPE>"""

    return base


def build_escalation_suffix(attempt: int, last_error: str) -> str:
    """Build escalation suffix for final retry."""
    return f"""

ESCALATION: Previous {attempt - 1} attempts by a junior model failed.
Last error: {last_error}
You are the senior specialist. Analyze the problem fresh and fix it definitively.

<ESCALATION_EXAMPLES>
BAD (over-engineering):
Error: missing type hint on `process_data`
Response: Refactored entire module, added type hints to all functions, created TypedDict classes, added runtime validation

GOOD (targeted fix):
Error: missing type hint on `process_data`
Response: Added `-> dict` return type to `process_data`, done
</ESCALATION_EXAMPLES>"""


# -----------------------------------------------------------------------------
# Implement Phase (Context-based API)
# -----------------------------------------------------------------------------
def phase_implement_ctx(ctx: Context, allowed_files: Optional[str] = None) -> None:
    """Execute implement phase using Context object.

    Args:
        ctx: Execution context
        allowed_files: Optional glob pattern restricting file modifications
    """
    plan = ctx.plan_file.read_text(encoding="utf-8")
    steps = parse_steps(plan)

    if not steps:
        ctx.log( "[IMPLEMENT] No steps found in plan.")
        raise ImplementError("No steps found in plan")

    # Extract goal for lean prompts
    goal = extract_plan_goal(plan)

    # Check that plan includes a verification step
    last_step_desc = steps[-1][1].lower() if steps else ""
    verify_keywords = ['verify', 'test', 'check', 'validate', 'confirm']
    has_verify_step = any(kw in last_step_desc for kw in verify_keywords)
    if not has_verify_step:
        ctx.log( "[WARN] Plan missing verification step. Adding implicit verify.")

    backup_scout_files_ctx(ctx)

    ctx.log( f"\n[IMPLEMENT] {len(steps)} steps to execute.")
    completed = get_completed_steps(ctx.log_file)
    seen_lint_hashes: Set[str] = set()
    consecutive_retry_steps = 0

    for step_idx, (step_num, step_desc) in enumerate(steps):
        if step_num in completed:
            continue

        ctx.log( f"\n[STEP {step_num}] {step_desc[:60]}...")

        is_verify_only = "OPERATION: VERIFY_COMPLETE" in plan

        # Build step context for lean prompts
        step_context = get_step_context(steps, step_idx)

        # First attempt uses lean context; retries/escalation get full plan
        use_full_plan = False
        last_error_summary = ""
        step_succeeded_on_attempt = 1

        for attempt in range(1, MAX_RETRIES + 1):
            if attempt > 1:
                ctx.log( f"  Retry {attempt}/{MAX_RETRIES}...")
                use_full_plan = True  # Retries get full context

            if attempt == MAX_RETRIES:
                ctx.log( f"  Escalating to {MODEL_BRAIN}...")
                use_full_plan = True  # Escalation always gets full context
                model = MODEL_BRAIN
            else:
                model = MODEL_HANDS

            # Build prompt with appropriate context level
            if is_verify_only:
                base_prompt = build_verify_prompt(step_desc, plan, goal=goal,
                                                  include_full_plan=use_full_plan)
            else:
                base_prompt = build_implement_prompt(
                    step_num, step_desc, plan, ctx.project_root, allowed_files,
                    step_context=step_context, goal=goal,
                    include_full_plan=use_full_plan
                )

            prompt = base_prompt
            if attempt == MAX_RETRIES:
                prompt = base_prompt + build_escalation_suffix(attempt, last_error_summary)

            output = run_claude(
                prompt,
                model=model,
                phase="implement",
                timeout=TIMEOUT_EXEC,
                project_root=ctx.project_root,
                log_fn=ctx.log,
                cost_callback=ctx.record_cost,
            ) or ""

            last_line = output.strip().split('\n')[-1] if output.strip() else ""
            if last_line.startswith("STEP_BLOCKED"):
                ctx.log( f"[BLOCKED] Step {step_num}")
                logger.info(f"\n{output}")
                raise ImplementError(f"Step {step_num} blocked: {last_line}")

            if "STEP_COMPLETE" in output:
                passed, lint_out = run_linter_with_timeout()
                if not passed:
                    ctx.log( f"[LINT FAIL] Step {step_num}")
                    for line in lint_out.splitlines()[:20]:
                        logger.info(f"    {line}")

                    truncated = "\n".join(lint_out.splitlines()[:30])
                    last_error_summary = truncated[:300]

                    lint_hash = hashlib.md5(lint_out.encode()).hexdigest()
                    if lint_hash in seen_lint_hashes:
                        prompt += f"\n\nLINT FAILED (same as a previous attempt—try a different fix):\n{truncated}"
                    else:
                        prompt += f"\n\nLINT FAILED:\n{truncated}\n\nFix the issues above."
                    seen_lint_hashes.add(lint_hash)

                    if len(seen_lint_hashes) >= MAX_RETRIES + 1:
                        ctx.log( f"[FAILED] Step {step_num}: {len(seen_lint_hashes)} distinct lint failures")
                        if ctx.backup_dir.exists():
                            ctx.log( f"[RECOVERY] Backups available in: {ctx.backup_dir}")
                        raise ImplementError(f"Step {step_num} failed: {len(seen_lint_hashes)} distinct lint failures")
                    continue

                ctx.log( f"[COMPLETE] Step {step_num}")
                seen_lint_hashes.clear()
                step_succeeded_on_attempt = attempt
                break
        else:
            ctx.log( f"[FAILED] Step {step_num} after {MAX_RETRIES} attempts")
            if ctx.backup_dir.exists():
                ctx.log( f"[RECOVERY] Backups available in: {ctx.backup_dir}")
            raise ImplementError(f"Step {step_num} failed after {MAX_RETRIES} attempts")

        if step_succeeded_on_attempt > 1:
            consecutive_retry_steps += 1
            if consecutive_retry_steps >= 2:
                ctx.log( "[CHECKPOINT] Multiple consecutive steps needed retries.")
                ctx.log( "  → Something may be wrong with the plan.")
                ctx.log( "  → Review .zen/log.md and consider --reset if plan needs rework.")
        else:
            consecutive_retry_steps = 0





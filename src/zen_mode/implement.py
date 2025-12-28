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
from zen_mode.files import read_file, backup_file, get_full_constitution, log
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
    scout = read_file(ctx.scout_file)
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
                log_fn=lambda msg: _log_ctx(ctx, msg)
            )


# -----------------------------------------------------------------------------
# Implement Prompt Builders
# -----------------------------------------------------------------------------
def build_verify_prompt(step_desc: str, plan: str) -> str:
    """Build prompt for verification-only step."""
    return f"""<task>
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


def build_implement_prompt(step_num: int, step_desc: str, plan: str,
                           project_root: Path, allowed_files: Optional[str] = None) -> str:
    """Build prompt for implementation step."""
    constitution = get_full_constitution(project_root, "GOLDEN RULES", "CODE STYLE", "TESTING")
    base = f"""<task>
Execute Step {step_num}: {step_desc}
</task>

<context>
IMPORTANT: This is a fresh session with no memory of previous steps.
READ target files first to understand current state before editing.

Full plan:
{plan}
</context>

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
    plan = read_file(ctx.plan_file)
    steps = parse_steps(plan)

    if not steps:
        _log_ctx(ctx, "[IMPLEMENT] No steps found in plan.")
        raise ImplementError("No steps found in plan")

    # Check that plan includes a verification step
    last_step_desc = steps[-1][1].lower() if steps else ""
    verify_keywords = ['verify', 'test', 'check', 'validate', 'confirm']
    has_verify_step = any(kw in last_step_desc for kw in verify_keywords)
    if not has_verify_step:
        _log_ctx(ctx, "[WARN] Plan missing verification step. Adding implicit verify.")

    backup_scout_files_ctx(ctx)

    _log_ctx(ctx, f"\n[IMPLEMENT] {len(steps)} steps to execute.")
    completed = get_completed_steps(ctx.log_file)
    seen_lint_hashes: Set[str] = set()
    consecutive_retry_steps = 0

    for step_num, step_desc in steps:
        if step_num in completed:
            continue

        _log_ctx(ctx, f"\n[STEP {step_num}] {step_desc[:60]}...")

        is_verify_only = "OPERATION: VERIFY_COMPLETE" in plan

        if is_verify_only:
            base_prompt = build_verify_prompt(step_desc, plan)
        else:
            base_prompt = build_implement_prompt(step_num, step_desc, plan, ctx.project_root, allowed_files)

        prompt = base_prompt
        last_error_summary = ""
        step_succeeded_on_attempt = 1

        for attempt in range(1, MAX_RETRIES + 1):
            if attempt > 1:
                _log_ctx(ctx, f"  Retry {attempt}/{MAX_RETRIES}...")

            if attempt == MAX_RETRIES:
                _log_ctx(ctx, f"  Escalating to {MODEL_BRAIN}...")
                prompt = base_prompt + build_escalation_suffix(attempt, last_error_summary)
                model = MODEL_BRAIN
            else:
                model = MODEL_HANDS

            output = run_claude(
                prompt,
                model=model,
                phase="implement",
                timeout=TIMEOUT_EXEC,
                project_root=ctx.project_root,
                log_fn=lambda msg: _log_ctx(ctx, msg),
                cost_callback=ctx.record_cost,
            ) or ""

            last_line = output.strip().split('\n')[-1] if output.strip() else ""
            if last_line.startswith("STEP_BLOCKED"):
                _log_ctx(ctx, f"[BLOCKED] Step {step_num}")
                logger.info(f"\n{output}")
                raise ImplementError(f"Step {step_num} blocked: {last_line}")

            if "STEP_COMPLETE" in output:
                passed, lint_out = run_linter_with_timeout()
                if not passed:
                    _log_ctx(ctx, f"[LINT FAIL] Step {step_num}")
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
                        _log_ctx(ctx, f"[FAILED] Step {step_num}: {len(seen_lint_hashes)} distinct lint failures")
                        if ctx.backup_dir.exists():
                            _log_ctx(ctx, f"[RECOVERY] Backups available in: {ctx.backup_dir}")
                        raise ImplementError(f"Step {step_num} failed: {len(seen_lint_hashes)} distinct lint failures")
                    continue

                _log_ctx(ctx, f"[COMPLETE] Step {step_num}")
                seen_lint_hashes.clear()
                step_succeeded_on_attempt = attempt
                break
        else:
            _log_ctx(ctx, f"[FAILED] Step {step_num} after {MAX_RETRIES} attempts")
            if ctx.backup_dir.exists():
                _log_ctx(ctx, f"[RECOVERY] Backups available in: {ctx.backup_dir}")
            raise ImplementError(f"Step {step_num} failed after {MAX_RETRIES} attempts")

        if step_succeeded_on_attempt > 1:
            consecutive_retry_steps += 1
            if consecutive_retry_steps >= 2:
                _log_ctx(ctx, "[CHECKPOINT] Multiple consecutive steps needed retries.")
                _log_ctx(ctx, "  → Something may be wrong with the plan.")
                _log_ctx(ctx, "  → Review .zen/log.md and consider --reset if plan needs rework.")
        else:
            consecutive_retry_steps = 0


def _log_ctx(ctx: Context, msg: str) -> None:
    """Log using context's log file."""
    log(msg, ctx.log_file, ctx.work_dir)



"""Plan phase: Create execution plan for task."""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List, Optional, Set, Tuple

from zen_mode.claude import run_claude
from zen_mode.config import MODEL_BRAIN
from zen_mode.context import Context
from zen_mode.files import read_file, write_file, get_full_constitution
from zen_mode.utils import log


# -----------------------------------------------------------------------------
# Plan Prompt Builder
# -----------------------------------------------------------------------------
def build_plan_prompt(task_file: str, plan_file: Path, scout_content: str, project_root: Path) -> str:
    """Build plan prompt for creating execution plan."""
    constitution = get_full_constitution(project_root, "GOLDEN RULES", "ARCHITECTURE", "PROCESS")
    return f"""<role>
You are a senior software architect creating an execution plan. Each step will be executed in isolation with only the plan as context. Your plans are precise, atomic, and efficient.
</role>

<constitution>
{constitution}
</constitution>

<rules>
- Every plan MUST start with this header:
# [Feature Name] Implementation Plan

**Goal:** [One sentence that describes the feature]
**Architecture:** [A sentence or two about approach]
**Dependencies:** [what this feature touches]

- Final step MUST be verification (test/verify/validate)
</rules>

<EXAMPLES>
BAD PLAN (missing interfaces, vague steps):
## Step 1: Update the user model
## Step 2: Add validation
## Step 3: Write tests
## Step 4: Update callers

GOOD PLAN (interfaces first, symbol references):
# Email Validation Implementation Plan

**Goal:** Add email validation to User model before save
**Architecture:** Single validation method on User, raises custom exception, caller handles
**Dependencies:** User model, registration endpoint, InvalidEmailError exception

## Interfaces
- `User.validate_email() -> None`: Raises `InvalidEmailError` if invalid
- `InvalidEmailError(Exception)`: Custom error for validation failures

## Steps

## Step 1: Add email validation to User model
Files: `src/models/user.py`
Target: `User` class, add method after `save()`
Action: Add `validate_email()` method

## Step 2: Update registration to use validation
Files: `src/api/auth.py` (modify), `src/models/user.py` (read)
Target: `register_user()` function
Action: Call `user.validate_email()` before save

## Step 3: Add tests for email validation
Files: `tests/test_user.py` (create)
Action: Test valid, invalid, and edge case

## Step 4: Verify all tests pass
Action: Run `pytest tests/test_user.py -v`
</EXAMPLES>

<output_format>
Format (strict markdown):
# [Feature Name] Implementation Plan

**Goal:** [One sentence that describes the feature]
**Architecture:** [A sentence or two about approach]
**Dependencies:** [what this feature touches]

## Interfaces (REQUIRED)
Define signatures that will change:
- `function_name(args) -> ReturnType`: purpose
- `ClassName.method(args) -> ReturnType`: purpose

## Steps
## Step 1: <action verb> <specific target>
## Step 2: <action verb> <specific target>
...
## Step N: Verify changes and run tests

Each step includes: Files, Target symbol, Action.
</output_format>

<task>
Create execution plan for: {task_file}
Write output to: {plan_file}
</task>

<context>
{scout_content}
</context>"""


# -----------------------------------------------------------------------------
# Step Parsing
# -----------------------------------------------------------------------------
def parse_steps(plan: str) -> List[Tuple[int, str]]:
    """Parse steps from plan markdown.

    Supports multiple formats:
    - Strict: ## Step N: description
    - Flexible: Step N: or N. description
    - Fallback: bullet points
    """
    # Strict format: ## Step N: description
    strict = re.findall(r"^## Step (\d+):\s*(.+)$", plan, re.M)
    if strict:
        seen: Set[int] = set()
        result: List[Tuple[int, str]] = []
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


def validate_plan_has_interfaces(plan: str) -> Tuple[bool, str]:
    """Reject plans without ## Interfaces section before steps.

    Interface-first design is a core architectural principle. Plans must
    define signatures/types before describing implementation steps.

    Args:
        plan: Plan content as markdown string

    Returns:
        Tuple of (valid, error_message). If valid, error_message is empty.
    """
    if not plan or not plan.strip():
        return True, ""  # Empty plan handled elsewhere

    # Normalize headers (# -> ##) for consistent parsing
    normalized = re.sub(r'^#\s+', '## ', plan, flags=re.MULTILINE)

    # Extract all section headers
    sections = [line.strip().lower() for line in normalized.splitlines()
                if line.strip().startswith("## ")]

    if not sections:
        return True, ""  # No sections at all, handled by other validators

    # Check for interfaces section
    has_interface = any("interface" in s for s in sections)
    if not has_interface:
        return False, "Plan must include '## Interfaces' section defining signatures"

    # Find positions of interfaces and first step
    interface_idx = next((i for i, s in enumerate(sections) if "interface" in s), 999)
    step_idx = next((i for i, s in enumerate(sections) if "step" in s), 999)

    if step_idx < interface_idx:
        return False, "## Interfaces must come BEFORE ## Steps"

    return True, ""


def get_completed_steps(log_file: Path) -> Set[int]:
    """Get set of completed step numbers from log file."""
    if not log_file.exists():
        return set()

    log_content = read_file(log_file)
    completed: Set[int] = set()

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


# -----------------------------------------------------------------------------
# Plan Phase (Context-based API)
# -----------------------------------------------------------------------------
def phase_plan_ctx(ctx: Context) -> None:
    """Execute plan phase using Context object.

    Args:
        ctx: Execution context with work_dir, task_file, etc.
    """
    if ctx.plan_file.exists():
        _log_ctx(ctx, "[PLAN] Cached. Skipping.")
        return

    _log_ctx(ctx, "\n[PLAN] Creating execution plan...")
    scout_content = read_file(ctx.scout_file)
    prompt = build_plan_prompt(ctx.task_file, ctx.plan_file, scout_content, ctx.project_root)

    output = run_claude(
        prompt,
        model=MODEL_BRAIN,
        phase="plan",
        project_root=ctx.project_root,
        log_fn=lambda msg: _log_ctx(ctx, msg),
        cost_callback=ctx.record_cost,
    )

    # Write plan if Claude didn't use Write tool
    if not ctx.plan_file.exists():
        if not output:
            _log_ctx(ctx, "[PLAN] Failed.")
            sys.exit(1)
        write_file(ctx.plan_file, output, ctx.work_dir)

    plan_content = read_file(ctx.plan_file)
    steps = parse_steps(plan_content)

    # Validate interface-first structure
    iface_valid, iface_msg = validate_plan_has_interfaces(plan_content)
    if not iface_valid:
        _log_ctx(ctx, f"[PLAN] Warning: {iface_msg}")

    # Validate efficiency (warn only, don't retry - Opus doesn't consolidate well)
    eff_valid, efficiency_msg = validate_plan_efficiency(steps)
    if not eff_valid:
        _log_ctx(ctx, f"[PLAN] Warning: {efficiency_msg}")

    _log_ctx(ctx, f"[PLAN] Done. {len(steps)} steps.")


def _log_ctx(ctx: Context, msg: str) -> None:
    """Log using context's log file."""
    log(msg, ctx.log_file, ctx.work_dir)



"""Scout phase: Map codebase for task execution."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set

from zen_mode.config import MODEL_EYES, PROJECT_ROOT, WORK_DIR
from zen_mode.utils import Context, read_file, write_file, run_claude


# -----------------------------------------------------------------------------
# Targeted Files Parser
# -----------------------------------------------------------------------------
def parse_targeted_files(scout_content: str) -> List[str]:
    """Extract file paths from ## Targeted Files section.

    Args:
        scout_content: Content of scout.md file

    Returns:
        List of file paths from the Targeted Files section
    """
    files: List[str] = []
    in_section = False

    for line in scout_content.splitlines():
        if line.startswith("## Targeted Files"):
            in_section = True
            continue
        if line.startswith("## ") and in_section:
            break
        if in_section and line.strip().startswith("- `"):
            match = re.match(r"- `([^`]+)`", line.strip())
            if match:
                files.append(match.group(1))

    return files


# -----------------------------------------------------------------------------
# Grep Impact (Golden Rule Enforcement)
# -----------------------------------------------------------------------------
def grep_impact(targeted_files: List[str], project_root: Path) -> Dict[str, List[str]]:
    """Find all files that reference the targeted files.

    Uses filename stem for broad matching to catch:
    - from module import
    - import module
    - from .module import (relative)
    - from package.module import

    Args:
        targeted_files: List of file paths to check
        project_root: Project root directory

    Returns:
        Dict mapping target file to list of files that reference it
    """
    impact: Dict[str, List[str]] = {}

    for target in targeted_files:
        stem = Path(target).stem  # "user_model.py" -> "user_model"

        # Use git grep if available (faster, respects .gitignore)
        # Fall back to grep/findstr
        matches: Set[str] = set()

        try:
            # Try git grep first (cross-platform, respects .gitignore)
            result = subprocess.run(
                ["git", "grep", "-l", stem, "--", "*.py"],
                capture_output=True,
                text=True,
                cwd=project_root,
                timeout=30
            )
            if result.returncode == 0 and result.stdout.strip():
                for f in result.stdout.strip().split("\n"):
                    if f and f != target:
                        matches.add(f)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            # git not available or timeout, try platform-specific grep
            try:
                # Unix grep
                result = subprocess.run(
                    ["grep", "-rl", "--include=*.py", stem, "."],
                    capture_output=True,
                    text=True,
                    cwd=project_root,
                    timeout=30
                )
                if result.returncode == 0 and result.stdout.strip():
                    for f in result.stdout.strip().split("\n"):
                        # Normalize path (remove ./ prefix)
                        f = f.lstrip("./")
                        if f and f != target:
                            matches.add(f)
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass  # grep not available, skip

        impact[target] = list(matches)

    return impact


def expand_dependencies(targeted_files: List[str], project_root: Path) -> List[str]:
    """Return files that reference any of the targeted files.

    Args:
        targeted_files: List of file paths being modified
        project_root: Project root directory

    Returns:
        List of additional files that reference targeted files
    """
    impact = grep_impact(targeted_files, project_root)
    all_deps: Set[str] = set()
    for deps in impact.values():
        all_deps.update(deps)
    return list(all_deps - set(targeted_files))


def append_grep_impact_to_scout(scout_file: Path, targeted_files: List[str],
                                 project_root: Path, log_fn: Optional[callable] = None) -> None:
    """Append grep impact section to scout file.

    Args:
        scout_file: Path to scout.md
        targeted_files: List of targeted file paths
        project_root: Project root directory
        log_fn: Optional logging function
    """
    if not targeted_files:
        return

    deps = expand_dependencies(targeted_files, project_root)

    if deps:
        if log_fn:
            log_fn(f"[SCOUT] Found {len(deps)} files referencing targeted files")

        with scout_file.open("a", encoding="utf-8") as f:
            f.write("\n## Grep Impact (callers/importers)\n")
            for dep in sorted(deps):
                f.write(f"- `{dep}`: references targeted file\n")
    elif log_fn:
        log_fn("[SCOUT] No additional callers/importers found")


# -----------------------------------------------------------------------------
# Scout Prompt Builder
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
# Scout Phase (Context-based API)
# -----------------------------------------------------------------------------
def phase_scout_ctx(ctx: Context) -> None:
    """Execute scout phase using Context object.

    Args:
        ctx: Execution context with work_dir, task_file, etc.
    """
    if ctx.scout_file.exists():
        _log_ctx(ctx, "[SCOUT] Cached. Skipping.")
        return

    _log_ctx(ctx, f"\n[SCOUT] Mapping codebase for {ctx.task_file}...")
    prompt = build_scout_prompt(ctx.task_file, str(ctx.scout_file))

    output = run_claude(
        prompt,
        model=MODEL_EYES,
        phase="scout",
        project_root=ctx.project_root,
        dry_run=ctx.dry_run,
        log_fn=lambda msg: _log_ctx(ctx, msg),
        cost_callback=ctx.record_cost,
    )

    if not output:
        _log_ctx(ctx, "[SCOUT] Failed.")
        sys.exit(1)

    # Fallback: write output if Claude didn't
    if not ctx.scout_file.exists():
        write_file(ctx.scout_file, output, ctx.work_dir)

    # Golden Rule: grep for callers/importers of targeted files
    scout_content = read_file(ctx.scout_file)
    targeted_files = parse_targeted_files(scout_content)
    if targeted_files:
        append_grep_impact_to_scout(
            ctx.scout_file,
            targeted_files,
            ctx.project_root,
            log_fn=lambda msg: _log_ctx(ctx, msg)
        )

    _log_ctx(ctx, "[SCOUT] Done.")


def _log_ctx(ctx: Context, msg: str) -> None:
    """Log using context's log file."""
    from zen_mode.utils import log
    log(msg, ctx.log_file, ctx.work_dir)



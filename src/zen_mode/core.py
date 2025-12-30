"""
Zen Mode: The "Anti-Jira" Agent Workflow.

PHILOSOPHY:
1. File System is the Database.
2. Markdown is the API.
3. If a file exists, that step is done.
"""
from __future__ import annotations
import logging
import shutil
import sys
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

from zen_mode.claude import run_claude
from zen_mode.config import MODEL_EYES, WORK_DIR_NAME, PROJECT_ROOT
from zen_mode.context import Context
from zen_mode.exceptions import ZenError, ConfigError, VerifyError
from zen_mode.files import write_file, log
from zen_mode.implement import phase_implement_ctx
from zen_mode.judge import phase_judge_ctx, should_skip_judge_ctx
from zen_mode.plan import phase_plan_ctx
from zen_mode.scout import phase_scout_ctx
from zen_mode.triage import parse_triage, should_fast_track, generate_synthetic_plan
from zen_mode.verify import verify_and_fix, project_has_tests, VerifyTimeout


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _write_cost_summary(ctx: Context) -> None:
    """Write cost summary to log and final_notes."""
    if not ctx.costs:
        return

    # Aggregate costs by phase
    phase_costs: Dict[str, float] = {}
    phase_tokens: Dict[str, Dict[str, int]] = {}
    for entry in ctx.costs:
        p = entry["phase"]
        phase_costs[p] = phase_costs.get(p, 0) + entry["cost"]
        phase_tokens.setdefault(p, {"in": 0, "out": 0, "cache_read": 0})
        for k, v in entry["tokens"].items():
            phase_tokens[p][k] = phase_tokens[p].get(k, 0) + v

    total = sum(phase_costs.values())
    total_in = sum(t["in"] for t in phase_tokens.values())
    total_out = sum(t["out"] for t in phase_tokens.values())
    total_cache = sum(t.get("cache_read", 0) for t in phase_tokens.values())
    breakdown = ", ".join(f"{k}=${v:.3f}" for k, v in phase_costs.items())

    summary = f"[COST] Total: ${total:.3f} ({breakdown})"

    # Log to file and console
    log(summary, ctx.log_file, ctx.work_dir)

    # Append to final_notes.md
    with ctx.notes_file.open("a", encoding="utf-8") as f:
        f.write("\n## Cost Summary\n")
        f.write(f"Total: ${total:.3f}\n")
        f.write(f"Tokens: {total_in} in, {total_out} out, {total_cache} cache read\n")
        f.write(f"Breakdown: {breakdown}\n")


def _check_previous_completion(notes_file: Path) -> bool:
    """Check if previous run completed successfully."""
    if not notes_file.exists():
        return False
    try:
        content = notes_file.read_text(encoding="utf-8")
        return "## Cost Summary" in content
    except (OSError, UnicodeDecodeError):
        return False


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------
def run(task_file: str, flags: Optional[set] = None, scout_context: Optional[str] = None, allowed_files: Optional[str] = None, non_interactive: bool = False) -> None:
    """
    Run the Zen workflow on a task file.

    Args:
        task_file: Path to task markdown file
        flags: Set of flags (--reset, --retry)
        scout_context: Optional path to pre-computed scout context file
        allowed_files: Optional glob pattern for allowed files to modify
        non_interactive: If True, skip input() prompts and fail-closed
    """
    flags = flags or set()

    task_path = Path(task_file)
    resolved_path = task_path.resolve()
    if not resolved_path.is_relative_to(PROJECT_ROOT.resolve()):
        raise ConfigError(f"Task file must be within project directory: {task_file}")
    if not task_path.exists():
        raise ConfigError(f"Task file not found: {task_file}")

    # Set up paths (local, not global)
    work_dir = PROJECT_ROOT / WORK_DIR_NAME
    notes_file = work_dir / "final_notes.md"
    log_file = work_dir / "log.md"

    if "--reset" in flags:
        if work_dir.exists():
            shutil.rmtree(work_dir)
        logger.info("Reset complete.")
        work_dir.mkdir(exist_ok=True)

    if "--reset" not in flags and _check_previous_completion(notes_file):
        logger.info("[COMPLETE] Previous run finished successfully.")
        logger.info(f"  -> See {notes_file.relative_to(PROJECT_ROOT)} for summary")
        logger.info("  -> Use --reset to start fresh")
        return

    if "--retry" in flags and log_file.exists():
        lines = log_file.read_text(encoding="utf-8").splitlines()
        cleaned = "\n".join(line for line in lines if "[COMPLETE] Step" not in line)
        write_file(log_file, cleaned, work_dir)
        logger.info("Cleared completion markers.")

    skip_judge = "--skip-judge" in flags
    skip_verify = "--skip-verify" in flags

    # Create execution context - all paths derived from context
    ctx = Context(
        work_dir=work_dir,
        task_file=task_file,
        project_root=PROJECT_ROOT,
        flags=flags,
    )

    def _log(msg: str) -> None:
        log(msg, ctx.log_file, ctx.work_dir)

    try:
        # Scout phase
        if scout_context:
            scout_path = Path(scout_context)
            resolved_scout = scout_path.resolve()
            if not resolved_scout.is_relative_to(PROJECT_ROOT.resolve()):
                raise ConfigError(f"Scout context file must be within project directory: {scout_context}")
            if not scout_path.exists():
                raise ConfigError(f"Scout context file not found: {scout_context}")
            ctx.work_dir.mkdir(exist_ok=True)
            shutil.copy(str(scout_path), str(ctx.scout_file))
            _log(f"[SCOUT] Using provided context: {scout_context}")
        else:
            phase_scout_ctx(ctx)

        # Triage check
        scout_output = ctx.scout_file.read_text(encoding="utf-8")
        triage = parse_triage(scout_output)
        fast_track_succeeded = False

        if should_fast_track(triage):
            _log(f"[TRIAGE] FAST_TRACK (confidence={triage.confidence:.2f})")

            # Generate synthetic plan from micro-spec
            write_file(ctx.plan_file, generate_synthetic_plan(triage), ctx.work_dir)

            # Fast track uses Haiku (MODEL_EYES) for implement phase
            phase_implement_ctx(ctx, allowed_files=allowed_files, fast_track=True)

            if skip_verify:
                _log("[VERIFY] Skipped (--skip-verify flag)")
                fast_track_succeeded = True
            elif not project_has_tests(ctx.project_root):
                _log("[VERIFY] Skipped (no test files in project)")
                fast_track_succeeded = True
            elif verify_and_fix(ctx):
                _log("[TRIAGE] Fast Track verified. Skipping Judge.")
                fast_track_succeeded = True
            else:
                _log("[TRIAGE] Fast Track failed verify. Escalating to Planner...")
                # Clear synthetic plan and completion markers for fresh start
                if ctx.plan_file.exists():
                    ctx.plan_file.unlink()
                if ctx.log_file.exists():
                    lines = ctx.log_file.read_text(encoding="utf-8").splitlines()
                    cleaned = "\n".join(line for line in lines if "[COMPLETE] Step" not in line)
                    write_file(ctx.log_file, cleaned, ctx.work_dir)

        if not fast_track_succeeded:
            # Standard path
            phase_plan_ctx(ctx)
            phase_implement_ctx(ctx, allowed_files=allowed_files)

            if skip_verify:
                _log("[VERIFY] Skipped (--skip-verify flag)")
            elif not project_has_tests(ctx.project_root):
                _log("[VERIFY] Skipped (no test files in project)")
            elif not verify_and_fix(ctx):
                raise VerifyError("Verification failed")

            if not skip_judge and not should_skip_judge_ctx(ctx, log_fn=_log):
                phase_judge_ctx(ctx, non_interactive=non_interactive)
            elif skip_judge:
                _log("[JUDGE] Skipped (--skip-judge flag)")

        # Generate summary
        plan = ctx.plan_file.read_text(encoding="utf-8")
        summary = run_claude(
            f"Summarize the completed changes in 3-5 bullets.\n\nPlan:\n{plan}",
            model=MODEL_EYES,
            phase="summary",
            timeout=60,
            project_root=ctx.project_root,
            log_fn=_log,
            cost_callback=ctx.record_cost,
        )
        if summary:
            write_file(ctx.notes_file, summary, ctx.work_dir)
        else:
            _log("[SUMMARY] Skipped (timeout)")

        _write_cost_summary(ctx)

        logger.info("[SUCCESS]")
    except KeyboardInterrupt:
        _log("[INTERRUPTED] User cancelled execution")
        logger.info("Interrupted. Progress saved to log.")
        raise KeyboardInterrupt("User cancelled execution")
    except VerifyTimeout as e:
        _log(f"[TIMEOUT] {e}")
        logger.error(f"[TIMEOUT] {e}")
        logger.error("Run again to retry.")
        raise ZenError(f"Timeout: {e}")

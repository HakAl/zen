"""
Zen Mode: The "Anti-Jira" Agent Workflow.

PHILOSOPHY:
1. File System is the Database.
2. Markdown is the API.
3. If a file exists, that step is done.
"""
from __future__ import annotations
import shutil
import sys
from pathlib import Path
from typing import Dict, Optional

from zen_mode.claude import run_claude
from zen_mode.config import MODEL_EYES, WORK_DIR_NAME, PROJECT_ROOT, WORK_DIR
from zen_mode.context import Context
from zen_mode.files import read_file, write_file, log
from zen_mode.implement import phase_implement_ctx
from zen_mode.judge import phase_judge_ctx, should_skip_judge_ctx
from zen_mode.plan import phase_plan_ctx
from zen_mode.scout import phase_scout_ctx
from zen_mode.triage import parse_triage, should_fast_track, generate_synthetic_plan
from zen_mode.verify import verify_and_fix, project_has_tests, VerifyTimeout

# -----------------------------------------------------------------------------
# Derived Paths (from config)
# -----------------------------------------------------------------------------
SCOUT_FILE = WORK_DIR / "scout.md"
PLAN_FILE = WORK_DIR / "plan.md"
LOG_FILE = WORK_DIR / "log.md"
NOTES_FILE = WORK_DIR / "final_notes.md"
BACKUP_DIR = WORK_DIR / "backup"
TEST_OUTPUT_FILE = WORK_DIR / "test_output.txt"
JUDGE_FEEDBACK_FILE = WORK_DIR / "judge_feedback.md"

# -----------------------------------------------------------------------------
# Runtime state
# -----------------------------------------------------------------------------
ALLOWED_FILES: Optional[str] = None


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


def _check_previous_completion() -> bool:
    """Check if previous run completed successfully."""
    if not NOTES_FILE.exists():
        return False
    try:
        content = read_file(NOTES_FILE)
        return "## Cost Summary" in content
    except Exception:
        return False


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------
def run(task_file: str, flags: Optional[set] = None, scout_context: Optional[str] = None, allowed_files: Optional[str] = None) -> None:
    """
    Run the Zen workflow on a task file.

    Args:
        task_file: Path to task markdown file
        flags: Set of flags (--reset, --retry)
        scout_context: Optional path to pre-computed scout context file
        allowed_files: Optional glob pattern for allowed files to modify
    """
    global WORK_DIR, SCOUT_FILE, PLAN_FILE, LOG_FILE, NOTES_FILE, BACKUP_DIR, TEST_OUTPUT_FILE, JUDGE_FEEDBACK_FILE, ALLOWED_FILES

    ALLOWED_FILES = allowed_files
    flags = flags or set()

    task_path = Path(task_file)
    resolved_path = task_path.resolve()
    if not resolved_path.is_relative_to(PROJECT_ROOT.resolve()):
        print(f"ERROR: Task file must be within project directory: {task_file}")
        sys.exit(1)
    if not task_path.exists():
        print(f"ERROR: Task file not found: {task_file}")
        sys.exit(1)

    # Set up paths
    WORK_DIR = PROJECT_ROOT / WORK_DIR_NAME
    SCOUT_FILE = WORK_DIR / "scout.md"
    PLAN_FILE = WORK_DIR / "plan.md"
    LOG_FILE = WORK_DIR / "log.md"
    NOTES_FILE = WORK_DIR / "final_notes.md"
    BACKUP_DIR = WORK_DIR / "backup"
    TEST_OUTPUT_FILE = WORK_DIR / "test_output.txt"
    JUDGE_FEEDBACK_FILE = WORK_DIR / "judge_feedback.md"

    if "--reset" in flags:
        if WORK_DIR.exists():
            shutil.rmtree(WORK_DIR)
        print("Reset complete.")
        WORK_DIR.mkdir(exist_ok=True)

    if "--reset" not in flags and _check_previous_completion():
        print("[COMPLETE] Previous run finished successfully.")
        print(f"  → See {NOTES_FILE.relative_to(PROJECT_ROOT)} for summary")
        print("  → Use --reset to start fresh")
        return

    if "--retry" in flags and LOG_FILE.exists():
        lines = read_file(LOG_FILE).splitlines()
        cleaned = "\n".join(line for line in lines if "[COMPLETE] Step" not in line)
        write_file(LOG_FILE, cleaned, WORK_DIR)
        print("Cleared completion markers.")

    skip_judge = "--skip-judge" in flags
    skip_verify = "--skip-verify" in flags

    # Create execution context
    ctx = Context(
        work_dir=WORK_DIR,
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
            if not scout_path.exists():
                print(f"ERROR: Scout context file not found: {scout_context}")
                sys.exit(1)
            WORK_DIR.mkdir(exist_ok=True)
            shutil.copy(str(scout_path), str(ctx.scout_file))
            _log(f"[SCOUT] Using provided context: {scout_context}")
        else:
            phase_scout_ctx(ctx)

        # Triage check
        scout_output = read_file(ctx.scout_file)
        triage = parse_triage(scout_output)
        fast_track_succeeded = False

        if should_fast_track(triage):
            _log(f"[TRIAGE] FAST_TRACK (confidence={triage.confidence:.2f})")

            # Generate synthetic plan from micro-spec
            write_file(ctx.plan_file, generate_synthetic_plan(triage), ctx.work_dir)

            phase_implement_ctx(ctx, allowed_files=allowed_files)

            if skip_verify:
                _log("[VERIFY] Skipped (--skip-verify flag)")
                fast_track_succeeded = True
            elif not project_has_tests():
                _log("[VERIFY] Skipped (no test files in project)")
                fast_track_succeeded = True
            elif verify_and_fix():
                _log("[TRIAGE] Fast Track verified. Skipping Judge.")
                fast_track_succeeded = True
            else:
                _log("[TRIAGE] Fast Track failed verify. Escalating to Planner...")
                # Clear synthetic plan and completion markers for fresh start
                if ctx.plan_file.exists():
                    ctx.plan_file.unlink()
                if ctx.log_file.exists():
                    lines = read_file(ctx.log_file).splitlines()
                    cleaned = "\n".join(line for line in lines if "[COMPLETE] Step" not in line)
                    write_file(ctx.log_file, cleaned, ctx.work_dir)

        if not fast_track_succeeded:
            # Standard path
            phase_plan_ctx(ctx)
            phase_implement_ctx(ctx, allowed_files=allowed_files)

            if skip_verify:
                _log("[VERIFY] Skipped (--skip-verify flag)")
            elif not project_has_tests():
                _log("[VERIFY] Skipped (no test files in project)")
            elif not verify_and_fix():
                sys.exit(1)

            if not skip_judge and not should_skip_judge_ctx(ctx, log_fn=_log):
                phase_judge_ctx(ctx)
            elif skip_judge:
                _log("[JUDGE] Skipped (--skip-judge flag)")

        # Generate summary
        plan = read_file(ctx.plan_file)
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

        print("\n[SUCCESS]")
    except KeyboardInterrupt:
        _log("[INTERRUPTED] User cancelled execution")
        print("\nInterrupted. Progress saved to log.")
        sys.exit(130)
    except VerifyTimeout as e:
        _log(f"[TIMEOUT] {e}")
        print(f"\n[TIMEOUT] {e}")
        print("Run again to retry.")
        sys.exit(1)

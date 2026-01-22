"""
Zen Mode CLI - argparse-based command line interface.
"""
import argparse
import logging
import os
import sys
from pathlib import Path
from types import SimpleNamespace

from . import __version__
from .exceptions import ZenError


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the CLI.

    Args:
        verbose: If True, enable DEBUG level. Otherwise INFO level.
    """
    level = logging.DEBUG if verbose else logging.INFO

    # Simple format - just the message for clean CLI output
    # Errors get prefixed automatically by using logger.error()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))

    # Configure root logger for zen_mode package
    root_logger = logging.getLogger("zen_mode")
    root_logger.setLevel(level)
    root_logger.addHandler(handler)

    # Prevent propagation to root logger (avoids duplicate messages)
    root_logger.propagate = False


logger = logging.getLogger(__name__)


def cmd_init(args: argparse.Namespace) -> None:
    """Initialize .zen/ directory and create CLAUDE.md if none exists."""
    zen_dir = Path.cwd() / ".zen"
    zen_dir.mkdir(exist_ok=True)

    claude_md = Path.cwd() / "CLAUDE.md"
    if not claude_md.exists():
        # Copy default template
        try:
            import importlib.resources as resources
            if hasattr(resources, 'files'):
                # Python 3.9+
                template = resources.files('zen_mode.defaults').joinpath('CLAUDE.md').read_text()
            else:
                # Python 3.7-3.8 fallback
                with resources.open_text('zen_mode.defaults', 'CLAUDE.md') as f:
                    template = f.read()
            claude_md.write_text(template, encoding='utf-8')
            logger.info(f"Created {claude_md}")
        except Exception as e:
            logger.warning(f"Could not copy default CLAUDE.md: {e}")
    else:
        logger.info("CLAUDE.md already exists, skipping.")

    logger.info(f"Initialized {zen_dir}")
    logger.info("Run 'zen <task.md>' to start.")


def cmd_run(args: argparse.Namespace) -> None:
    """Run the 4-phase workflow on a task file."""
    task_file = args.task_file

    # Check for local zen.py first (ejected mode)
    local_zen = Path.cwd() / "zen.py"
    if local_zen.exists():
        logger.warning("Executing local ./zen.py - ensure you trust this file")
        trust_local = getattr(args, 'trust_local', False)
        if not trust_local:
            if sys.stdin.isatty():
                try:
                    choice = input(">> Execute local zen.py? [y/N]: ").strip().lower()
                    if choice != 'y':
                        logger.info("Aborted by user.")
                        sys.exit(1)
                except EOFError:
                    logger.error("Cannot confirm in non-interactive mode. Use --trust-local to proceed.")
                    sys.exit(1)
            else:
                logger.error("Cannot execute local zen.py in non-interactive mode without --trust-local")
                sys.exit(1)
        import subprocess
        cmd = [sys.executable, str(local_zen), task_file]
        if args.reset:
            cmd.append("--reset")
        if args.retry:
            cmd.append("--retry")
        if args.skip_judge:
            cmd.append("--skip-judge")
        if args.skip_verify:
            cmd.append("--skip-verify")
        if args.scout_context:
            cmd.append("--scout-context")
            cmd.append(args.scout_context)
        if args.allowed_files:
            cmd.append("--allowed-files")
            cmd.append(args.allowed_files)
        try:
            # Use run() with timeout instead of call() to prevent indefinite hangs
            result = subprocess.run(cmd, timeout=3600)  # 1 hour timeout for local zen.py
            sys.exit(result.returncode)
        except subprocess.TimeoutExpired:
            logger.error("Local zen.py timed out after 1 hour")
            sys.exit(124)  # Standard timeout exit code

    # Use package core
    from . import core

    flags = set()
    if args.reset:
        flags.add("--reset")
    if args.retry:
        flags.add("--retry")
    if args.skip_judge:
        flags.add("--skip-judge")
    if args.skip_verify:
        flags.add("--skip-verify")

    # Auto-detect non-interactive mode when stdin is not a TTY (e.g., swarm subprocess)
    non_interactive = not sys.stdin.isatty()

    try:
        core.run(task_file, flags, scout_context=args.scout_context, allowed_files=args.allowed_files, non_interactive=non_interactive)
    except KeyboardInterrupt:
        sys.exit(130)
    except ZenError as e:
        logger.error(str(e))
        sys.exit(1)


def cmd_swarm(args: argparse.Namespace) -> None:
    """Execute multiple tasks in parallel with conflict detection."""
    from . import swarm

    if not args.tasks:
        logger.error("At least one task file required")
        sys.exit(1)

    # Validate task files
    for task_file in args.tasks:
        task_path = Path(task_file)
        if not task_path.exists():
            logger.error(f"Task file not found: {task_file}")
            sys.exit(1)

    # Build config with validation
    try:
        config = swarm.SwarmConfig(
            tasks=args.tasks,
            workers=args.workers,
            project_root=Path.cwd(),
            verbose=getattr(args, 'verbose', False),
            strategy=getattr(args, 'strategy', 'auto')
        )
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)

    # Execute
    dispatcher = swarm.SwarmDispatcher(config)
    try:
        summary = dispatcher.execute()
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)

    # Print report
    print(summary.pass_fail_report())

    # Exit with failure if any tasks failed
    sys.exit(0 if summary.failed == 0 else 1)


def main() -> None:
    # Check for --verbose early so logging is configured before any output
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    setup_logging(verbose=verbose)

    # Log security-relevant config (validates env vars, fails fast on invalid)
    from .config import log_security_config
    log_security_config()

    # Check for subcommands first, before argparse sees the args
    if len(sys.argv) >= 2:
        cmd = sys.argv[1]
        if cmd == "init":
            cmd_init(SimpleNamespace())
            return
        elif cmd == "swarm":
            # zen swarm <task1.md> [task2.md ...] [--workers N] [--strategy S] [--verbose] [--experimental]
            parser = argparse.ArgumentParser(prog="zen swarm")
            parser.add_argument("tasks", nargs="+", help="Task files to execute in parallel")
            parser.add_argument("--workers", type=int, default=None, help="Number of parallel workers (default: auto)")
            parser.add_argument("--strategy", choices=["worktree", "sequential", "auto"], default="auto",
                              help="Execution strategy: worktree (git worktrees), sequential (same-dir), auto (worktree with fallback)")
            parser.add_argument("--verbose", "-v", action="store_true", help="Show full logs instead of status ticker")
            parser.add_argument("--experimental", action="store_true", help="Acknowledge swarm is experimental")
            args = parser.parse_args(sys.argv[2:])

            # Gate: require --experimental flag
            if not args.experimental:
                logger.error("Swarm is experimental and may produce unexpected results.")
                logger.error("Known issues: merge conflicts, worktree cleanup, cross-platform edge cases.")
                logger.error("")
                logger.error("Use 'zen swarm --experimental <tasks...>' to proceed anyway.")
                sys.exit(1)

            # Auto-calculate workers if not specified: min(tasks, cpu_count, 8)
            if args.workers is None:
                args.workers = max(1, min(len(args.tasks), os.cpu_count() or 4, 8))

            cmd_swarm(args)
            return
        elif cmd in ("--help", "-h"):
            pass  # Let argparse handle it
        elif cmd in ("--version", "-V"):
            print(f"zen-mode {__version__}")
            return
        elif not cmd.startswith("-"):
            # Assume it's a task file
            parser = argparse.ArgumentParser(prog="zen")
            parser.add_argument("task_file", help="Path to task markdown file")
            parser.add_argument("--reset", action="store_true", help="Reset work directory")
            parser.add_argument("--retry", action="store_true", help="Clear completion markers")
            parser.add_argument("--skip-judge", action="store_true", help="Skip Judge phase review")
            parser.add_argument("--skip-verify", action="store_true", help="Skip Verify phase (for infra-only tasks)")
            parser.add_argument("--scout-context", type=str, default=None, help="Path to pre-computed scout context file")
            parser.add_argument("--allowed-files", type=str, default=None, help="Glob pattern for allowed files to modify")
            parser.add_argument("--trust-local", action="store_true", help="Trust local zen.py without confirmation")
            parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose/debug output")
            args = parser.parse_args(sys.argv[1:])
            cmd_run(args)
            return

    # Default: show help
    print(f"""zen-mode {__version__} - Minimalist Autonomous Agent Runner

Usage:
  zen init                    Initialize .zen/ directory
  zen <task.md>               Run the 5-phase workflow

Options:
  --reset                     Reset work directory and start fresh
  --retry                     Clear completion markers to retry failed steps
  --skip-judge                Skip Judge phase review (Opus architectural review)
  --skip-verify               Skip Verify phase (for infra-only tasks)
  --trust-local               Trust local zen.py without confirmation
  --verbose, -v               Enable verbose/debug output

Examples:
  zen init
  zen task.md
  zen task.md --reset
  zen task.md --skip-judge

Experimental:
  zen swarm --experimental <task1.md> ...   (parallel execution, use with caution)
""")


if __name__ == "__main__":
    main()

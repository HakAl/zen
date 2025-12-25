"""
Zen Mode CLI - argparse-based command line interface.
"""
import argparse
import os
import sys
from pathlib import Path

from . import __version__


def cmd_init(args):
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
            print(f"Created {claude_md}")
        except Exception as e:
            print(f"Warning: Could not copy default CLAUDE.md: {e}")
    else:
        print("CLAUDE.md already exists, skipping.")

    print(f"Initialized {zen_dir}")
    print("Run 'zen <task.md>' to start.")


def cmd_run(args):
    """Run the 4-phase workflow on a task file."""
    task_file = args.task_file

    # Check for local zen.py first (ejected mode)
    local_zen = Path.cwd() / "zen.py"
    if local_zen.exists():
        print(f"Using local {local_zen} (ejected mode)")
        import subprocess
        cmd = [sys.executable, str(local_zen), task_file]
        if args.reset:
            cmd.append("--reset")
        if args.retry:
            cmd.append("--retry")
        if args.dry_run:
            cmd.append("--dry-run")
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
        sys.exit(subprocess.call(cmd))

    # Use package core
    from . import core

    flags = set()
    if args.reset:
        flags.add("--reset")
    if args.retry:
        flags.add("--retry")
    if args.dry_run:
        flags.add("--dry-run")
    if args.skip_judge:
        flags.add("--skip-judge")
    if args.skip_verify:
        flags.add("--skip-verify")

    core.run(task_file, flags, scout_context=args.scout_context, allowed_files=args.allowed_files)


def cmd_swarm(args):
    """Execute multiple tasks in parallel with conflict detection."""
    from . import swarm

    if not args.tasks:
        print("Error: At least one task file required")
        sys.exit(1)

    # Validate task files
    for task_file in args.tasks:
        task_path = Path(task_file)
        if not task_path.exists():
            print(f"Error: Task file not found: {task_file}")
            sys.exit(1)

    # Build config with validation
    try:
        config = swarm.SwarmConfig(
            tasks=args.tasks,
            workers=args.workers,
            dry_run=args.dry_run,
            project_root=Path.cwd(),
            verbose=getattr(args, 'verbose', False)
        )
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Execute
    dispatcher = swarm.SwarmDispatcher(config)
    try:
        summary = dispatcher.execute()
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Print report
    print(summary.pass_fail_report())

    # Exit with failure if any tasks failed
    sys.exit(0 if summary.failed == 0 else 1)


def main():
    # Check for subcommands first, before argparse sees the args
    if len(sys.argv) >= 2:
        cmd = sys.argv[1]
        if cmd == "init":
            class Args:
                pass
            cmd_init(Args())
            return
        elif cmd == "eject":
            class Args:
                pass
            cmd_eject(Args())
            return
        elif cmd == "swarm":
            # zen swarm <task1.md> [task2.md ...] [--workers N] [--dry-run] [--verbose]
            parser = argparse.ArgumentParser(prog="zen swarm")
            parser.add_argument("tasks", nargs="+", help="Task files to execute in parallel")
            parser.add_argument("--workers", type=int, default=None, help="Number of parallel workers (default: auto)")
            parser.add_argument("--dry-run", action="store_true", help="Show what would happen without executing")
            parser.add_argument("--verbose", "-v", action="store_true", help="Show full logs instead of status ticker")
            args = parser.parse_args(sys.argv[2:])

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
            parser.add_argument("--dry-run", action="store_true", help="Show what would happen")
            parser.add_argument("--skip-judge", action="store_true", help="Skip Judge phase review")
            parser.add_argument("--skip-verify", action="store_true", help="Skip Verify phase (for infra-only tasks)")
            parser.add_argument("--scout-context", type=str, default=None, help="Path to pre-computed scout context file")
            parser.add_argument("--allowed-files", type=str, default=None, help="Glob pattern for allowed files to modify")
            args = parser.parse_args(sys.argv[1:])
            cmd_run(args)
            return

    # Default: show help
    print(f"""zen-mode {__version__} - Minimalist Autonomous Agent Runner

Usage:
  zen init                    Initialize .zen/ directory
  zen <task.md>               Run the 4-phase workflow
  zen swarm <task1.md> ...    Execute multiple tasks in parallel

Options:
  --reset                     Reset work directory and start fresh
  --retry                     Clear completion markers to retry failed steps
  --dry-run                   Show what would happen without executing
  --skip-judge                Skip Judge phase review (Opus architectural review)
  --skip-verify               Skip Verify phase (for infra-only tasks)
  --workers N                 Number of parallel workers for swarm (default: auto)
  --verbose, -v               Show full logs instead of status ticker (swarm)

Examples:
  zen init
  zen task.md
  zen task.md --reset
  zen task.md --skip-judge
  zen swarm task1.md task2.md --workers 4
  zen swarm task1.md task2.md --verbose
""")


if __name__ == "__main__":
    main()

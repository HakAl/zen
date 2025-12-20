"""
Zen Mode CLI - argparse-based command line interface.
"""
import argparse
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
            project_root=Path.cwd()
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


def cmd_eject(args):
    """Copy core.py and linter.py to local directory as standalone scripts."""
    try:
        import importlib.resources as resources

        # Read source files from package
        if hasattr(resources, 'files'):
            # Python 3.9+
            pkg = resources.files('zen_mode')
            core_src = pkg.joinpath('core.py').read_text()
            linter_src = pkg.joinpath('linter.py').read_text()
        else:
            # Python 3.7-3.8 fallback
            with resources.open_text('zen_mode', 'core.py') as f:
                core_src = f.read()
            with resources.open_text('zen_mode', 'linter.py') as f:
                linter_src = f.read()

        # Add shebang and main block to core.py -> zen.py
        zen_header = '''#!/usr/bin/env python3
# Standalone version - ejected from zen-mode package
# Modify as needed for your project
'''
        zen_main = '''

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Zen Mode - Autonomous Agent Runner")
    parser.add_argument("task_file", help="Path to task markdown file")
    parser.add_argument("--reset", action="store_true", help="Reset work directory")
    parser.add_argument("--retry", action="store_true", help="Clear completion markers")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen")
    args = parser.parse_args()

    flags = set()
    if args.reset:
        flags.add("--reset")
    if args.retry:
        flags.add("--retry")
    if args.dry_run:
        flags.add("--dry-run")

    run(args.task_file, flags)


if __name__ == "__main__":
    main()
'''

        # Fix the linter import for standalone mode
        core_standalone = core_src.replace(
            'from . import linter',
            'import zen_lint as linter'
        )

        zen_py = Path.cwd() / "zen.py"
        zen_py.write_text(zen_header + core_standalone + zen_main, encoding='utf-8')
        print(f"Created {zen_py}")

        # Add shebang to linter.py -> zen_lint.py
        lint_header = '''#!/usr/bin/env python3
# Standalone version - ejected from zen-mode package
# Modify as needed for your project
'''
        lint_main = '''

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Zen Lint - Code Quality Linter")
    parser.add_argument("paths", nargs="*", help="Files or directories to scan")
    parser.add_argument("-s", "--severity", choices=["HIGH", "MEDIUM", "LOW"], default="LOW",
                        help="Minimum severity level")
    args = parser.parse_args()

    passed, output = run_lint(args.paths if args.paths else None, args.severity)
    print(output)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
'''

        zen_lint_py = Path.cwd() / "zen_lint.py"
        zen_lint_py.write_text(lint_header + linter_src + lint_main, encoding='utf-8')
        print(f"Created {zen_lint_py}")

        print("\nEjected. Run 'python zen.py <task.md>' directly.")
        print("The 'zen' command will now use your local versions.")

    except Exception as e:
        print(f"Error ejecting: {e}")
        sys.exit(1)


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
            # zen swarm <task1.md> [task2.md ...] [--workers N] [--dry-run]
            parser = argparse.ArgumentParser(prog="zen swarm")
            parser.add_argument("tasks", nargs="+", help="Task files to execute in parallel")
            parser.add_argument("--workers", type=int, default=2, help="Number of parallel workers (default: 2)")
            parser.add_argument("--dry-run", action="store_true", help="Show what would happen without executing")
            args = parser.parse_args(sys.argv[2:])
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
  zen eject                   Copy scripts to local directory

Options:
  --reset                     Reset work directory and start fresh
  --retry                     Clear completion markers to retry failed steps
  --dry-run                   Show what would happen without executing
  --skip-judge                Skip Judge phase review (Opus architectural review)
  --workers N                 Number of parallel workers for swarm (default: 2)

Examples:
  zen init
  zen task.md
  zen task.md --reset
  zen task.md --skip-judge
  zen swarm task1.md task2.md --workers 4
  zen eject
""")


if __name__ == "__main__":
    main()

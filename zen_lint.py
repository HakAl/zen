#!/usr/bin/env python3
"""
Zen Lint: Universal "Lazy Coder" Detector.
Scans for forbidden patterns (TODO, FIXME, SHIM).
"""
import sys
import re
import subprocess
from pathlib import Path

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
FORBIDDEN_RULES = [
    ("DEPRECATED", re.compile(r"\bdeprecated\b", re.I)),
    ("LEGACY", re.compile(r"\blegacy\b", re.I)),
    ("SHIM", re.compile(r"\bshim\b", re.I)),
    ("TODO", re.compile(r"\bTODO\b")),
    ("FIXME", re.compile(r"\bFIXME\b")),
    ("PLACEHOLDER", re.compile(r"\b[A-Z_]+_HERE\b")),  # e.g. API_KEY_HERE
]

# Files to ignore completely
IGNORE_DIRS = {".git", ".zen", "__pycache__", "node_modules", "venv", "env"}
IGNORE_EXTS = {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".md", ".txt"}


def is_text_file(path: Path) -> bool:
    """Simple heuristic to check if file is text."""
    if path.suffix.lower() in IGNORE_EXTS:
        return False
    try:
        # Try reading the first 1kb
        with path.open("rb") as f:
            chunk = f.read(1024)
            return b"\0" not in chunk  # Null bytes usually mean binary
    except Exception:
        return False


def get_context(lines: list[str], lineno: int, context: int = 2) -> str:
    """Returns the offending line with surrounding context for the LLM."""
    start = max(0, lineno - 1 - context)
    end = min(len(lines), lineno + context)

    snippet = []
    for i in range(start, end):
        prefix = ">>" if i == (lineno - 1) else "  "
        snippet.append(f"{prefix} {i + 1:4d} | {lines[i]}")
    return "\n".join(snippet)


def check_file(path: str) -> list[str]:
    p = Path(path)
    if not p.exists() or not p.is_file():
        return []

    # Path filtering
    if any(part in IGNORE_DIRS for part in p.parts):
        return []

    if not is_text_file(p):
        return []

    errors = []
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()

        for i, line in enumerate(lines, 1):
            for name, regex in FORBIDDEN_RULES:
                if regex.search(line):
                    # Ignore the linter itself
                    if p.name == "zen_lint.py": continue

                    ctx = get_context(lines, i)
                    msg = (
                        f"VIOLATION [{name}] in {p}:\n"
                        f"{ctx}\n"
                        f"Action: REMOVE '{name}' or DELETE the code block."
                    )
                    errors.append(msg)
                    # Stop checking this line after one match to avoid duplicate noise
                    break

    except Exception as e:
        return [f"Error reading {path}: {e}"]

    return errors


def get_git_changes():
    """Returns list of changed files (Staged, Unstaged, Untracked)."""
    files = set()
    try:
        # Modified/Staged
        cmd_mod = ["git", "ls-files", "-m", "--exclude-standard"]
        files.update(subprocess.check_output(cmd_mod, text=True).splitlines())

        # Untracked (New)
        cmd_new = ["git", "ls-files", "-o", "--exclude-standard"]
        files.update(subprocess.check_output(cmd_new, text=True).splitlines())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []  # Not a git repo or git not found

    return [f for f in files if f.strip()]


if __name__ == "__main__":
    # 1. Determine files to scan
    if len(sys.argv) > 1:
        paths = sys.argv[1:]
    else:
        paths = get_git_changes()
        if not paths:
            # Fallback: scan everything if git returns nothing (optional)
            paths = ["."]

    # 2. Scan
    all_errors = []
    for root_arg in paths:
        root_path = Path(root_arg)
        if root_path.is_file():
            all_errors.extend(check_file(str(root_path)))
        else:
            for p in root_path.rglob("*"):
                if p.is_file():
                    all_errors.extend(check_file(str(p)))

    # 3. Report
    if all_errors:
        print(f"LINT FAIL: Found {len(all_errors)} violations in changed files.")
        print("=" * 60)
        for e in all_errors:
            print(e)
            print("-" * 60)
        sys.exit(1)
"""Git operations for zen_mode.

Consolidates git subprocess calls from linter, judge, utils, and scout.
All functions accept a project_root parameter and return clean data structures.

All functions gracefully degrade when git is unavailable or errors occur,
returning sensible defaults (False, None, [], empty stats).
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set

from zen_mode.files import should_ignore_path

# Logger for debugging git operations - disabled by default
_logger = logging.getLogger(__name__)

# Exceptions we expect from subprocess git calls
_GIT_ERRORS = (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError)


# -----------------------------------------------------------------------------
# Repository State
# -----------------------------------------------------------------------------
def is_repo(project_root: Path) -> bool:
    """Check if path is inside a git repository."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            cwd=project_root,
            timeout=5
        )
        return result.returncode == 0
    except _GIT_ERRORS as e:
        _logger.debug("is_repo check failed: %s", e)
        return False


def has_head(project_root: Path) -> bool:
    """Check if git repo has at least one commit (HEAD exists)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            cwd=project_root,
            timeout=5
        )
        return result.returncode == 0
    except _GIT_ERRORS as e:
        _logger.debug("has_head check failed: %s", e)
        return False


def get_head_commit(project_root: Path) -> Optional[str]:
    """Get current HEAD commit hash, or None if no commits."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except _GIT_ERRORS as e:
        _logger.debug("get_head_commit failed: %s", e)
    return None


# -----------------------------------------------------------------------------
# Changed Files
# -----------------------------------------------------------------------------
def get_staged_files(project_root: Path) -> List[str]:
    """Get list of staged files (in index, not yet committed)."""
    try:
        if has_head(project_root):
            result = subprocess.run(
                ["git", "diff", "--name-only", "--cached", "HEAD"],
                capture_output=True,
                text=True,
                cwd=project_root,
                timeout=30
            )
        else:
            # No commits yet - just get staged files
            result = subprocess.run(
                ["git", "diff", "--name-only", "--cached"],
                capture_output=True,
                text=True,
                cwd=project_root,
                timeout=30
            )
        if result.returncode == 0:
            return [f for f in result.stdout.strip().splitlines() if f]
    except _GIT_ERRORS as e:
        _logger.debug("get_staged_files failed: %s", e)
    return []


def get_unstaged_files(project_root: Path) -> List[str]:
    """Get list of modified but unstaged files."""
    if not has_head(project_root):
        return []  # No commits = no unstaged changes possible
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only"],
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=30
        )
        if result.returncode == 0:
            return [f for f in result.stdout.strip().splitlines() if f]
    except _GIT_ERRORS as e:
        _logger.debug("get_unstaged_files failed: %s", e)
    return []


def get_untracked_files(project_root: Path) -> List[str]:
    """Get list of untracked files (respects .gitignore)."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=30
        )
        if result.returncode == 0:
            return [f for f in result.stdout.strip().splitlines() if f]
    except _GIT_ERRORS as e:
        _logger.debug("get_untracked_files failed: %s", e)
    return []


def get_changed_files(
    project_root: Path,
    include_staged: bool = True,
    include_unstaged: bool = True,
    include_untracked: bool = True,
) -> List[str]:
    """Get all changed files (staged, unstaged, and/or untracked).

    Args:
        project_root: Root of the git repository
        include_staged: Include staged files
        include_unstaged: Include modified but unstaged files
        include_untracked: Include untracked files

    Returns:
        Deduplicated list of file paths relative to project_root
    """
    if not is_repo(project_root):
        return []

    files: Set[str] = set()

    if include_staged:
        files.update(get_staged_files(project_root))
    if include_unstaged:
        files.update(get_unstaged_files(project_root))
    if include_untracked:
        files.update(get_untracked_files(project_root))

    return sorted(files)


# -----------------------------------------------------------------------------
# Diff Statistics
# -----------------------------------------------------------------------------
@dataclass
class DiffStats:
    """Statistics from git diff --numstat."""
    added: int = 0
    deleted: int = 0
    files: List[str] = None

    def __post_init__(self):
        if self.files is None:
            self.files = []

    @property
    def total(self) -> int:
        return self.added + self.deleted


def get_diff_stats(project_root: Path) -> DiffStats:
    """Get line change statistics for working directory.

    Returns:
        DiffStats with added/deleted line counts and list of files
    """
    stats = DiffStats()

    if not is_repo(project_root):
        return stats

    try:
        if has_head(project_root):
            result = subprocess.run(
                ["git", "diff", "--numstat", "HEAD"],
                capture_output=True,
                text=True,
                cwd=project_root,
                timeout=30
            )
        else:
            result = subprocess.run(
                ["git", "diff", "--cached", "--numstat"],
                capture_output=True,
                text=True,
                cwd=project_root,
                timeout=30
            )

        if result.returncode == 0 and result.stdout.strip():
            for line in result.stdout.strip().splitlines():
                parts = line.split("\t")
                if len(parts) >= 3:
                    added, deleted, filepath = parts[0], parts[1], parts[2]
                    # Binary files show "-" for added/deleted
                    if added != "-":
                        stats.added += int(added)
                    if deleted != "-":
                        stats.deleted += int(deleted)
                    stats.files.append(filepath)
    except _GIT_ERRORS as e:
        _logger.debug("get_diff_stats failed: %s", e)

    return stats


# -----------------------------------------------------------------------------
# Search
# -----------------------------------------------------------------------------
def grep_files(
    pattern: str,
    project_root: Path,
    extensions: Optional[List[str]] = None,
    timeout: int = 30
) -> List[str]:
    """Search for pattern in files using git grep.

    Args:
        pattern: Search pattern (literal string, not regex)
        project_root: Root of the git repository
        extensions: File extensions to search (e.g., [".py", ".js"])
        timeout: Timeout in seconds

    Returns:
        List of file paths containing the pattern
    """
    if not is_repo(project_root):
        return []

    cmd = ["git", "grep", "-l", pattern]

    # Add file patterns for extensions
    if extensions:
        cmd.append("--")
        for ext in extensions:
            # Normalize extension format
            ext = ext if ext.startswith(".") else f".{ext}"
            cmd.append(f"*{ext}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=timeout
        )
        if result.returncode == 0:
            return [f for f in result.stdout.strip().splitlines() if f]
    except _GIT_ERRORS as e:
        _logger.debug("grep_files failed: %s", e)

    return []


# -----------------------------------------------------------------------------
# Changed Files (Formatted)
# -----------------------------------------------------------------------------
def get_changed_filenames(project_root: Path, backup_dir: Path) -> str:
    """Get list of changed files, filtered to exclude ignored directories.

    This function:
    1. Gets changed files from git (or backup dir as fallback)
    2. Filters out files in ignored directories (node_modules, build, etc.)
    3. Returns newline-separated list of file paths

    We ALWAYS filter ignored directories, even if they're in git, because:
    - Users may forget .gitignore
    - We should never scan build/cache/node_modules
    - Prevents false positives from generated code

    Args:
        project_root: Project root directory
        backup_dir: Backup directory for fallback

    Returns:
        Newline-separated list of changed file paths (filtered)
    """
    # Get changed files from git (staged, unstaged, untracked)
    changed_files = get_changed_files(project_root)

    # CRITICAL: Filter out ignored directories (node_modules, build, etc.)
    # We do this even if files are tracked in git, because users may forget .gitignore
    if changed_files:
        filtered_files = [f for f in changed_files if not should_ignore_path(f)]
        if filtered_files:
            return "\n".join(sorted(filtered_files))

    # Fallback: list files from backup directory (also filtered)
    if backup_dir.exists():
        files = [
            str(f.relative_to(backup_dir))
            for f in backup_dir.rglob("*")
            if f.is_file() and not should_ignore_path(str(f.relative_to(backup_dir)))
        ]
        if files:
            return "\n".join(files)

    return "[No files detected]"

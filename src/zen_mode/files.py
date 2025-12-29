"""File I/O utilities for zen_mode."""
from __future__ import annotations

import fnmatch
import logging
import re
import shutil
import tempfile
import time
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# Directories to ignore during linting and file scanning
IGNORE_DIRS: Set[str] = {
    # Version control
    ".git", ".svn", ".hg", ".zen",
    # Python
    "__pycache__", "venv", ".venv", "env", ".eggs", "*.egg-info",
    ".mypy_cache", ".pytest_cache", ".tox", ".nox", ".ruff_cache",
    "site-packages", "htmlcov", ".hypothesis",
    # JavaScript/Node
    "node_modules", "bower_components", ".npm", ".yarn", ".pnpm",
    # Build outputs
    "dist", "build", "target", "bin", "obj", "out", "_build",
    "cmake-build-debug", "cmake-build-release", "CMakeFiles",
    # IDE/Editor
    ".idea", ".vscode", ".vs", ".eclipse", ".settings",
    # Coverage
    "coverage", ".coverage", ".nyc_output",
    # Framework-specific
    ".next", ".nuxt", ".output", ".svelte-kit", ".astro",
    ".angular", ".docusaurus", ".meteor",
    # Infrastructure/Deploy
    ".terraform", ".serverless", ".aws-sam", "cdk.out",
    ".vercel", ".netlify", ".firebase",
    # Other languages
    ".gradle", ".cargo", ".stack-work", "Pods", "Carthage",
    "DerivedData", "vendor", "deps", "elm-stuff",
    # Misc
    "tmp", "temp", "cache", ".cache", "logs",
}

# Files to ignore during linting and file scanning
IGNORE_FILES: Set[str] = {
    # Lock files
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "go.sum",
    "Cargo.lock", "Gemfile.lock", "poetry.lock", "composer.lock",
    "packages.lock.json", "flake.lock", "pubspec.lock",
    # OS artifacts
    ".DS_Store", "Thumbs.db", "desktop.ini",
    # Editor artifacts
    ".gitignore", ".gitattributes", ".editorconfig",
    # Docs/meta (not code)
    "LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE",
    "CHANGELOG.md", "CHANGELOG", "HISTORY.md",
    "AUTHORS", "CONTRIBUTORS", "CODEOWNERS",
    # Config files (too many false positives)
    ".prettierrc", ".eslintrc", ".stylelintrc",
    "tsconfig.json", "jsconfig.json",
    # Misc
    ".npmrc", ".nvmrc", ".python-version", ".ruby-version",
    ".tool-versions", "requirements.txt", "Pipfile",
    # Environment files (should be gitignored, not our job)
    ".env", ".env.local", ".env.development", ".env.production",
    ".env.test", ".env.staging", ".env.example",
}

# Binary file extensions that should NEVER be processed
# These are filtered from git changes and never linted
BINARY_EXTS: Set[str] = {
    # Images
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg", ".bmp",
    # Documents (binary formats)
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    # Archives
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    # Binaries
    ".exe", ".dll", ".so", ".dylib", ".class", ".pyc", ".pyo", ".o", ".a",
    # Fonts
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    # Media
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv", ".flac", ".ogg",
}


def should_ignore_path(path_str: str) -> bool:
    """Check if path should be filtered from git changes and processing.

    Checks:
    1. Directories in path (node_modules, build, etc.)
    2. Hidden directories (starts with .)
    3. Ignored filenames (package-lock.json, .DS_Store, etc.)
    4. Binary extensions (.png, .exe, .zip, etc.)

    Args:
        path_str: File or directory path to check

    Returns:
        True if path should be ignored, False otherwise
    """
    path = Path(path_str)

    # Check if any part of the path is an ignored directory
    for part in path.parts:
        # Check exact match in IGNORE_DIRS
        if part in IGNORE_DIRS:
            return True
        # Check glob patterns in IGNORE_DIRS (e.g., *.egg-info)
        if any(fnmatch.fnmatch(part, pattern) for pattern in IGNORE_DIRS if '*' in pattern):
            return True
        # Check if starts with dot (hidden directory)
        if part.startswith('.'):
            return True

    # Check if filename is in IGNORE_FILES
    if path.name in IGNORE_FILES:
        return True

    # Check if file has a binary extension
    if any(path.name.endswith(ext) for ext in BINARY_EXTS):
        return True

    return False


def write_file(path: Path, content: str, work_dir: Optional[Path] = None) -> None:
    """Write content to file atomically."""
    if work_dir:
        work_dir.mkdir(exist_ok=True)
        temp_dir = work_dir
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_dir = path.parent

    with tempfile.NamedTemporaryFile("w", dir=temp_dir, delete=False, encoding="utf-8") as tf:
        tf.write(content)
        tmp = tf.name

    # Atomic replace with Windows retry
    try:
        Path(tmp).replace(path)
    except OSError:
        # Windows: file may be busy (virus scanner, IDE)
        time.sleep(0.3)
        try:
            Path(tmp).replace(path)
        except OSError as e:
            Path(tmp).unlink(missing_ok=True)
            raise OSError(f"Failed to write {path}: {e}")


def backup_file(path: Path, backup_dir: Path, project_root: Path, log_fn: Optional[Callable[[str], None]] = None) -> None:
    """Create a backup of a file before modification."""
    if not path.exists():
        return

    backup_dir.mkdir(parents=True, exist_ok=True)
    rel_path = path.relative_to(project_root) if path.is_relative_to(project_root) else path

    # Preserve directory structure to avoid collisions
    backup_path = backup_dir / rel_path
    backup_path.parent.mkdir(parents=True, exist_ok=True)

    # Only backup if we haven't already
    if not backup_path.exists():
        shutil.copy2(path, backup_path)
        if log_fn:
            log_fn(f"[BACKUP] {rel_path}")


def load_constitution(*sections: str) -> str:
    """Load specified sections from defaults/CLAUDE.md constitution.

    Extracts sections by header name (e.g., "GOLDEN RULES", "ARCHITECTURE").
    Returns formatted markdown with requested sections joined by newlines.

    Args:
        *sections: Section names to extract (case-insensitive header match)

    Returns:
        Formatted string with requested sections, empty string if none found.

    Example:
        >>> load_constitution("GOLDEN RULES", "ARCHITECTURE")
        '## GOLDEN RULES\\n- Verify, then Delete...\\n\\n## ARCHITECTURE\\n...'
    """
    constitution_path = Path(__file__).parent / "defaults" / "CLAUDE.md"
    if not constitution_path.exists():
        return ""

    try:
        content = constitution_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        logger.error(f"Failed to load constitution from {constitution_path}: {e}")
        return ""
    result = []

    for section in sections:
        # Match ## SECTION_NAME through next ## or EOF (case-insensitive)
        # Section name must be followed by: end-of-line, or space+paren (for subtitles)
        pattern = rf"^## {re.escape(section)}(?:\s*$|\s+\().*?(?=^## |\Z)"
        match = re.search(pattern, content, re.MULTILINE | re.DOTALL | re.IGNORECASE)
        if match:
            result.append(match.group().strip())

    return "\n\n".join(result)


def get_full_constitution(project_root: Path, *sections: str) -> str:
    """Merge zen defaults + project rules (CLAUDE.md or AGENTS.md).

    Loads specified sections from zen's internal constitution, then appends
    project-specific rules from CLAUDE.md (preferred) or AGENTS.md (fallback).

    Args:
        project_root: Path to project root directory
        *sections: Section names to extract from zen defaults

    Returns:
        Combined constitution string with zen defaults and project rules.
    """
    # Use cached helper with hashable args (str path, tuple of sections)
    return _get_full_constitution_cached(str(project_root), sections)


@lru_cache(maxsize=4)
def _get_full_constitution_cached(project_root_str: str, sections: Tuple[str, ...]) -> str:
    """Cached implementation of get_full_constitution.

    Args:
        project_root_str: String path to project root (hashable)
        sections: Tuple of section names (hashable)

    Returns:
        Combined constitution string.
    """
    project_root = Path(project_root_str)
    zen_rules = load_constitution(*sections)

    # Prefer CLAUDE.md, fall back to AGENTS.md
    project_path = project_root / "CLAUDE.md"
    if not project_path.exists():
        project_path = project_root / "AGENTS.md"

    project_rules = project_path.read_text(encoding="utf-8") if project_path.exists() else ""

    if project_rules:
        return f"{zen_rules}\n\n## Project Rules\n{project_rules}"
    return zen_rules


def log(msg: str, log_file: Path, work_dir: Path) -> None:
    """Log message to file and stdout."""
    work_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    with log_file.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    logger.info(msg)

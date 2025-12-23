"""Shared utility functions for zen_mode."""
import fnmatch
import subprocess
from pathlib import Path
from typing import Set

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
    changed_files: Set[str] = set()

    # Helper to check if git repo exists
    def _git_is_repo() -> bool:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                capture_output=True,
                cwd=project_root,
                timeout=2
            )
            return result.returncode == 0
        except Exception:
            return False

    # Helper to check if git has commits
    def _git_has_head() -> bool:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                cwd=project_root,
                timeout=2
            )
            return result.returncode == 0
        except Exception:
            return False

    if _git_is_repo():
        # Try git diff against HEAD (works if commits exist)
        if _git_has_head():
            try:
                result = subprocess.run(
                    ["git", "diff", "--name-only", "HEAD"],
                    capture_output=True, text=True, cwd=project_root
                )
                if result.returncode == 0 and result.stdout.strip():
                    changed_files.update(result.stdout.strip().splitlines())
            except Exception:
                pass
        else:
            # No commits yet - use git diff --cached to find staged files
            try:
                result = subprocess.run(
                    ["git", "diff", "--cached", "--name-only"],
                    capture_output=True, text=True, cwd=project_root
                )
                if result.returncode == 0 and result.stdout.strip():
                    changed_files.update(result.stdout.strip().splitlines())
            except Exception:
                pass

        # Always check for untracked files (works even with no commits)
        try:
            result = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard"],
                capture_output=True, text=True, cwd=project_root
            )
            if result.returncode == 0 and result.stdout.strip():
                changed_files.update(result.stdout.strip().splitlines())
        except Exception:
            pass

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

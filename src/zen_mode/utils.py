"""Shared utility functions for zen_mode."""
from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

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


# -----------------------------------------------------------------------------
# Context Dataclass (replaces global state)
# -----------------------------------------------------------------------------
@dataclass
class Context:
    """Execution context passed to all phases. Enables testing."""
    work_dir: Path
    task_file: str
    project_root: Path = field(default_factory=lambda: Path.cwd())
    flags: Set[str] = field(default_factory=set)
    costs: List[Dict[str, Any]] = field(default_factory=list)
    tokens: int = 0

    # Derived paths (computed on first access)
    _scout_file: Optional[Path] = field(default=None, repr=False)
    _plan_file: Optional[Path] = field(default=None, repr=False)
    _log_file: Optional[Path] = field(default=None, repr=False)
    _notes_file: Optional[Path] = field(default=None, repr=False)
    _backup_dir: Optional[Path] = field(default=None, repr=False)
    _test_output_file: Optional[Path] = field(default=None, repr=False)

    @property
    def scout_file(self) -> Path:
        if self._scout_file is None:
            self._scout_file = self.work_dir / "scout.md"
        return self._scout_file

    @property
    def plan_file(self) -> Path:
        if self._plan_file is None:
            self._plan_file = self.work_dir / "plan.md"
        return self._plan_file

    @property
    def log_file(self) -> Path:
        if self._log_file is None:
            self._log_file = self.work_dir / "log.md"
        return self._log_file

    @property
    def notes_file(self) -> Path:
        if self._notes_file is None:
            self._notes_file = self.work_dir / "final_notes.md"
        return self._notes_file

    @property
    def backup_dir(self) -> Path:
        if self._backup_dir is None:
            self._backup_dir = self.work_dir / "backup"
        return self._backup_dir

    @property
    def test_output_file(self) -> Path:
        if self._test_output_file is None:
            self._test_output_file = self.work_dir / "test_output.txt"
        return self._test_output_file

    def record_cost(self, phase: str, cost: float, tokens: Dict[str, int]) -> None:
        """Record cost and tokens for a phase."""
        self.costs.append({
            "phase": phase,
            "cost": cost,
            "tokens": tokens,
        })
        self.tokens += tokens.get("in", 0) + tokens.get("out", 0)


# -----------------------------------------------------------------------------
# File I/O Helpers
# -----------------------------------------------------------------------------
def log(msg: str, log_file: Path, work_dir: Path) -> None:
    """Log message to file and stdout."""
    work_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    with log_file.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(f"  {msg}")


def read_file(path: Path) -> str:
    """Read file contents, returning empty string if not exists."""
    return path.read_text(encoding="utf-8") if path.exists() else ""


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

    content = constitution_path.read_text(encoding="utf-8")
    result = []

    for section in sections:
        # Match ## SECTION_NAME through next ## or EOF (case-insensitive)
        # Section name must be followed by: end-of-line, or space+paren (for subtitles)
        pattern = rf"^## {re.escape(section)}(?:\s*$|\s+\().*?(?=^## |\Z)"
        match = re.search(pattern, content, re.MULTILINE | re.DOTALL | re.IGNORECASE)
        if match:
            result.append(match.group().strip())

    return "\n\n".join(result)


def backup_file(path: Path, backup_dir: Path, project_root: Path, log_fn: Optional[callable] = None) -> None:
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


# -----------------------------------------------------------------------------
# Claude CLI Runner
# -----------------------------------------------------------------------------
_claude_exe: Optional[str] = None


def _init_claude() -> str:
    """Initialize Claude CLI path. Returns path or exits."""
    global _claude_exe
    if _claude_exe:
        return _claude_exe
    _claude_exe = shutil.which("claude") or os.getenv("CLAUDE_EXE")
    if not _claude_exe:
        print("ERROR: 'claude' CLI not found.")
        print("Install: npm i -g @anthropic-ai/claude-cli")
        sys.exit(1)
    return _claude_exe


def _parse_json_response(stdout: str) -> Optional[dict]:
    """Parse JSON from CLI output, stripping any warning prefixes."""
    start = stdout.find("{")
    if start == -1:
        return None
    try:
        return json.loads(stdout[start:])
    except json.JSONDecodeError:
        return None


def _extract_cost(raw: dict) -> Tuple[float, Dict[str, int]]:
    """Extract cost and token counts from CLI JSON response."""
    cost = float(raw.get("total_cost_usd") or 0)
    usage = raw.get("usage") or {}
    return cost, {
        "in": int(usage.get("input_tokens") or 0),
        "out": int(usage.get("output_tokens") or 0),
        "cache_read": int(usage.get("cache_read_input_tokens") or 0),
    }


def run_claude(
    prompt: str,
    model: str,
    *,
    phase: str = "unknown",
    timeout: Optional[int] = None,
    project_root: Path,
    log_fn: Optional[callable] = None,
    cost_callback: Optional[callable] = None,
    show_costs: bool = True,
) -> Optional[str]:
    """Run Claude CLI with prompt and return response.

    Args:
        prompt: The prompt to send to Claude
        model: Model name (e.g., "opus", "sonnet", "haiku")
        phase: Phase name for cost tracking
        timeout: Timeout in seconds (default from config)
        project_root: Project root directory for CWD
        log_fn: Optional logging function
        cost_callback: Optional callback(phase, cost, tokens) for cost tracking
        show_costs: Whether to log cost info

    Returns:
        Response text or None on error
    """
    from zen_mode.config import TIMEOUT_EXEC

    timeout = timeout or TIMEOUT_EXEC

    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)
        else:
            print(f"  {msg}")

    claude_exe = _init_claude()
    cmd = [claude_exe, "-p", "--dangerously-skip-permissions", "--model", model,
           "--output-format", "json"]
    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=project_root,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        try:
            proc.stdin.write(prompt)
            proc.stdin.close()
        except BrokenPipeError:
            _log(f"[WARN] Claude ({model}) stdin closed early")
        stdout, stderr = proc.communicate(timeout=timeout)

        if proc.returncode != 0:
            _log(f"[ERROR] Claude ({model}): {stderr[:300]}")
            return None

        data = _parse_json_response(stdout)
        if not isinstance(data, dict):
            _log("[WARN] Failed to parse JSON response, cost not tracked")
            return stdout

        try:
            cost, tokens = _extract_cost(data)
            if cost_callback:
                cost_callback(phase, cost, tokens)

            if show_costs:
                total_tok = tokens["in"] + tokens["out"]
                _log(f"[COST] {model} {phase}: ${cost:.4f} ({tokens['in']}+{tokens['out']}={total_tok} tok)")
        except (KeyError, TypeError, ValueError) as e:
            _log(f"[WARN] Cost extraction failed: {e}")

        return data.get("result")

    except subprocess.TimeoutExpired:
        _log(f"[ERROR] Claude ({model}) timed out")
        if proc:
            proc.terminate()
            try:
                stdout, stderr = proc.communicate(timeout=5)
                if phase == "verify":
                    _log(f"[DEBUG] Timeout partial: stdout_len={len(stdout) if stdout else 0}")
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
        return None
    except Exception as e:
        _log(f"[ERROR] Subprocess: {e}")
        if proc:
            proc.terminate()
            proc.communicate()
        return None

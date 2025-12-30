"""
Zen Mode Configuration.

Centralized configuration constants. All env vars and defaults in one place.
"""
import logging
import os
import re
import shutil
from pathlib import Path
from typing import List, Optional

from zen_mode.exceptions import ConfigError

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Validation Helpers
# -----------------------------------------------------------------------------
def _get_int_env(name: str, default: str, min_val: int = 0) -> int:
    """Get integer from env var with validation.

    Args:
        name: Environment variable name
        default: Default value as string
        min_val: Minimum allowed value

    Returns:
        Validated integer value

    Raises:
        ConfigError: If value is not a valid integer or below minimum
    """
    raw = os.getenv(name, default)
    try:
        val = int(raw)
    except ValueError:
        raise ConfigError(f"{name}={raw!r} is not a valid integer")
    if val < min_val:
        raise ConfigError(f"{name}={val} must be >= {min_val}")
    return val


def _get_model_env(name: str, default: str) -> str:
    """Get model name from env var with validation.

    Args:
        name: Environment variable name
        default: Default model name

    Returns:
        Validated model name

    Raises:
        ConfigError: If model name is not in allowlist
    """
    allowed = {"opus", "sonnet", "haiku"}
    val = os.getenv(name, default)
    if val not in allowed:
        raise ConfigError(f"{name}={val!r} not in {allowed}")
    return val


def _get_bool_env(name: str, default: str) -> bool:
    """Get boolean from env var with validation.

    Args:
        name: Environment variable name
        default: Default value as string ("true" or "false")

    Returns:
        Validated boolean value

    Raises:
        ConfigError: If value is not a valid boolean string
    """
    raw = os.getenv(name, default).lower()
    if raw in ("true", "1", "yes", "on"):
        return True
    if raw in ("false", "0", "no", "off"):
        return False
    raise ConfigError(
        f"{name}={raw!r} is not a valid boolean. "
        f"Use: true/false, 1/0, yes/no, on/off"
    )


def _get_dir_name_env(name: str, default: str) -> str:
    """Get directory name from env var with validation.

    Validates that the value is a safe directory name (no path traversal).

    Args:
        name: Environment variable name
        default: Default directory name

    Returns:
        Validated directory name

    Raises:
        ConfigError: If value contains path traversal or invalid characters
    """
    val = os.getenv(name, default)
    # Reject path separators and traversal patterns
    if "/" in val or "\\" in val:
        raise ConfigError(f"{name}={val!r} must be a directory name, not a path")
    if val in (".", "..") or ".." in val:
        raise ConfigError(f"{name}={val!r} contains path traversal")
    # Reject empty or whitespace-only
    if not val.strip():
        raise ConfigError(f"{name} cannot be empty or whitespace")
    # Reject names that would be problematic on Windows or Unix
    if re.search(r'[<>:"|?*\x00-\x1f]', val):
        raise ConfigError(f"{name}={val!r} contains invalid characters")
    return val


def _get_paths_env(name: str) -> List[Path]:
    """Get list of paths from env var with validation.

    Paths are separated by os.pathsep (: on Unix, ; on Windows).
    Empty value returns empty list.

    Args:
        name: Environment variable name

    Returns:
        List of validated Path objects (only existing paths)

    Raises:
        ConfigError: If any specified path does not exist
    """
    raw = os.getenv(name, "")
    if not raw.strip():
        return []

    paths = []
    for part in raw.split(os.pathsep):
        part = part.strip()
        if not part:
            continue
        p = Path(part)
        if not p.exists():
            raise ConfigError(f"{name}: path {part!r} does not exist")
        paths.append(p.resolve())
    return paths


def _get_exe_env(name: str) -> Optional[str]:
    """Get executable path from env var with validation.

    Args:
        name: Environment variable name

    Returns:
        Validated executable path or None if not set

    Raises:
        ConfigError: If specified path does not exist or is not executable
    """
    raw = os.getenv(name)
    if not raw:
        return None
    # Check if it exists and is executable
    resolved = shutil.which(raw)
    if resolved:
        return resolved
    # shutil.which failed - check if path exists at all
    p = Path(raw)
    if not p.exists():
        raise ConfigError(f"{name}={raw!r} does not exist")
    raise ConfigError(f"{name}={raw!r} exists but is not executable")


# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------
MODEL_BRAIN = _get_model_env("ZEN_MODEL_BRAIN", "opus")
MODEL_HANDS = _get_model_env("ZEN_MODEL_HANDS", "sonnet")
MODEL_EYES = _get_model_env("ZEN_MODEL_EYES", "haiku")

# -----------------------------------------------------------------------------
# Timeouts (seconds)
# -----------------------------------------------------------------------------
TIMEOUT_EXEC = _get_int_env("ZEN_TIMEOUT", "600", min_val=1)
TIMEOUT_VERIFY = _get_int_env("ZEN_VERIFY_TIMEOUT", "180", min_val=1)
TIMEOUT_FIX = _get_int_env("ZEN_FIX_TIMEOUT", "300", min_val=1)
TIMEOUT_LINTER = _get_int_env("ZEN_LINTER_TIMEOUT", "120", min_val=1)
TIMEOUT_SUMMARY = _get_int_env("ZEN_SUMMARY_TIMEOUT", "180", min_val=1)

# -----------------------------------------------------------------------------
# Retries / Loops
# -----------------------------------------------------------------------------
MAX_RETRIES = _get_int_env("ZEN_RETRIES", "2", min_val=0)
MAX_FIX_ATTEMPTS = _get_int_env("ZEN_FIX_ATTEMPTS", "2", min_val=0)
MAX_JUDGE_LOOPS = _get_int_env("ZEN_JUDGE_LOOPS", "2", min_val=0)

# -----------------------------------------------------------------------------
# Judge Thresholds
# -----------------------------------------------------------------------------
JUDGE_TRIVIAL_LINES = _get_int_env("ZEN_JUDGE_TRIVIAL", "5", min_val=0)
JUDGE_SMALL_REFACTOR_LINES = _get_int_env("ZEN_JUDGE_SMALL", "20", min_val=0)
JUDGE_SIMPLE_PLAN_LINES = _get_int_env("ZEN_JUDGE_SIMPLE_LINES", "30", min_val=0)
JUDGE_SIMPLE_PLAN_STEPS = _get_int_env("ZEN_JUDGE_SIMPLE_STEPS", "2", min_val=0)

# -----------------------------------------------------------------------------
# Output Limits
# -----------------------------------------------------------------------------
MAX_TEST_OUTPUT_RAW = 50 * 1024      # 50KB for file
MAX_TEST_OUTPUT_PROMPT = 2 * 1024    # 2KB for prompt
PARSE_TEST_THRESHOLD = _get_int_env("ZEN_PARSE_THRESHOLD", "500", min_val=0)

# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------
WORK_DIR_NAME = _get_dir_name_env("ZEN_WORK_DIR", ".zen")
PROJECT_ROOT = Path.cwd()
WORK_DIR = PROJECT_ROOT / WORK_DIR_NAME
TEST_OUTPUT_PATH = WORK_DIR / "test_output.txt"
TEST_OUTPUT_PATH_STR = WORK_DIR_NAME + "/test_output.txt"  # For prompts

# -----------------------------------------------------------------------------
# Display
# -----------------------------------------------------------------------------
SHOW_COSTS = _get_bool_env("ZEN_SHOW_COSTS", "true")

# -----------------------------------------------------------------------------
# Cost Budget
# -----------------------------------------------------------------------------
def _get_float_env(name: str, default: str, min_val: float = 0.0) -> float:
    """Get float from env var with validation.

    Args:
        name: Environment variable name
        default: Default value as string
        min_val: Minimum allowed value

    Returns:
        Validated float value

    Raises:
        ConfigError: If value is not a valid float or below minimum
    """
    raw = os.getenv(name, default)
    try:
        val = float(raw)
    except ValueError:
        raise ConfigError(f"{name}={raw!r} is not a valid number")
    if val < min_val:
        raise ConfigError(f"{name}={val} must be >= {min_val}")
    return val


# Maximum cost per task in USD (0 = no limit)
MAX_COST_PER_TASK = _get_float_env("ZEN_MAX_COST", "0.0", min_val=0.0)


# -----------------------------------------------------------------------------
# Security-Relevant Configuration
# These are read dynamically (not cached) to support testing and runtime changes
# -----------------------------------------------------------------------------


def _get_skip_permissions() -> bool:
    """Get ZEN_SKIP_PERMISSIONS value (dynamic, not cached).

    Returns:
        True if permissions should be skipped (default), False otherwise

    Raises:
        ConfigError: If value is not a valid boolean
    """
    return _get_bool_env("ZEN_SKIP_PERMISSIONS", "true")


def _get_trust_roots() -> List[Path]:
    """Get ZEN_TRUST_ROOTS value (dynamic, not cached).

    Returns:
        List of trusted root paths, empty if not set

    Raises:
        ConfigError: If any specified path does not exist
    """
    return _get_paths_env("ZEN_TRUST_ROOTS")


def _get_claude_exe_config() -> Optional[str]:
    """Get CLAUDE_EXE value (dynamic, not cached).

    Returns:
        Path to Claude CLI or None if not configured

    Raises:
        ConfigError: If specified path does not exist or is not executable
    """
    return _get_exe_env("CLAUDE_EXE")


def log_security_config() -> None:
    """Log security-relevant configuration at startup.

    Called once during CLI initialization to provide visibility
    into security-relevant settings.
    """
    skip_perms = _get_skip_permissions()
    trust_roots = _get_trust_roots()
    claude_exe = _get_claude_exe_config()

    if not skip_perms:
        logger.warning(
            "[CONFIG] ZEN_SKIP_PERMISSIONS=false - Claude will prompt for permissions"
        )
    elif trust_roots:
        roots_str = ", ".join(str(r) for r in trust_roots)
        logger.info(f"[CONFIG] ZEN_TRUST_ROOTS={roots_str}")
    # else: default behavior (skip permissions globally), no log needed

    if claude_exe:
        logger.info(f"[CONFIG] CLAUDE_EXE={claude_exe}")


def is_trusted_directory(cwd: Path) -> bool:
    """Check if cwd is within a trusted root.

    If ZEN_TRUST_ROOTS is set, only directories within those roots are trusted.
    If ZEN_TRUST_ROOTS is not set, falls back to ZEN_SKIP_PERMISSIONS behavior.

    Args:
        cwd: Current working directory to check

    Returns:
        True if directory is trusted for skip-permissions
    """
    trust_roots = _get_trust_roots()
    if not trust_roots:
        # No roots specified - fall back to global SKIP_PERMISSIONS
        return _get_skip_permissions()

    cwd_path = cwd.resolve()
    for root_path in trust_roots:
        try:
            cwd_path.relative_to(root_path)
            return True
        except ValueError:
            continue
    return False


def get_claude_exe() -> Optional[str]:
    """Get configured Claude executable path.

    Returns:
        Path to Claude CLI or None if not configured via env var
    """
    return _get_claude_exe_config()

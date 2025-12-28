"""
Zen Mode Configuration.

Centralized configuration constants. All env vars and defaults in one place.
"""
import os
from pathlib import Path

from zen_mode.exceptions import ConfigError


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
WORK_DIR_NAME = os.getenv("ZEN_WORK_DIR", ".zen")
PROJECT_ROOT = Path.cwd()
WORK_DIR = PROJECT_ROOT / WORK_DIR_NAME
TEST_OUTPUT_PATH = WORK_DIR / "test_output.txt"
TEST_OUTPUT_PATH_STR = WORK_DIR_NAME + "/test_output.txt"  # For prompts

# -----------------------------------------------------------------------------
# Display
# -----------------------------------------------------------------------------
SHOW_COSTS = os.getenv("ZEN_SHOW_COSTS", "true").lower() == "true"

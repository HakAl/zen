"""
Zen Mode Configuration.

Centralized configuration constants. All env vars and defaults in one place.
"""
import os
from pathlib import Path

# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------
MODEL_BRAIN = os.getenv("ZEN_MODEL_BRAIN", "opus")
MODEL_HANDS = os.getenv("ZEN_MODEL_HANDS", "sonnet")
MODEL_EYES = os.getenv("ZEN_MODEL_EYES", "haiku")

# -----------------------------------------------------------------------------
# Timeouts (seconds)
# -----------------------------------------------------------------------------
TIMEOUT_EXEC = int(os.getenv("ZEN_TIMEOUT", "600"))
TIMEOUT_VERIFY = int(os.getenv("ZEN_VERIFY_TIMEOUT", "180"))  # was 120
TIMEOUT_FIX = int(os.getenv("ZEN_FIX_TIMEOUT", "300"))
TIMEOUT_LINTER = int(os.getenv("ZEN_LINTER_TIMEOUT", "120"))
TIMEOUT_SUMMARY = int(os.getenv("ZEN_SUMMARY_TIMEOUT", "180"))

# -----------------------------------------------------------------------------
# Retries / Loops
# -----------------------------------------------------------------------------
MAX_RETRIES = int(os.getenv("ZEN_RETRIES", "2"))
MAX_FIX_ATTEMPTS = int(os.getenv("ZEN_FIX_ATTEMPTS", "2"))
MAX_JUDGE_LOOPS = int(os.getenv("ZEN_JUDGE_LOOPS", "2"))

# -----------------------------------------------------------------------------
# Judge Thresholds
# -----------------------------------------------------------------------------
JUDGE_TRIVIAL_LINES = int(os.getenv("ZEN_JUDGE_TRIVIAL", "5"))
JUDGE_SMALL_REFACTOR_LINES = int(os.getenv("ZEN_JUDGE_SMALL", "20"))
JUDGE_SIMPLE_PLAN_LINES = int(os.getenv("ZEN_JUDGE_SIMPLE_LINES", "30"))
JUDGE_SIMPLE_PLAN_STEPS = int(os.getenv("ZEN_JUDGE_SIMPLE_STEPS", "2"))

# -----------------------------------------------------------------------------
# Output Limits
# -----------------------------------------------------------------------------
MAX_TEST_OUTPUT_RAW = 50 * 1024      # 50KB for file
MAX_TEST_OUTPUT_PROMPT = 2 * 1024    # 2KB for prompt
PARSE_TEST_THRESHOLD = int(os.getenv("ZEN_PARSE_THRESHOLD", "500"))

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

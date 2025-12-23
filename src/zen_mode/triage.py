"""
Triage module for fast-track detection.
Keeps complexity logic separate from core.py.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

__all__ = [
    "TriageResult",
    "TRIAGE_PROMPT_SECTION",
    "parse_triage",
    "should_fast_track",
    "generate_synthetic_plan",
]

logger = logging.getLogger(__name__)


@dataclass
class TriageResult:
    """Result of triage analysis."""
    fast_track: bool = False
    confidence: float = 0.0
    micro_spec: Optional[str] = None
    target_file: Optional[str] = None


# Prompt section to append to scout prompt
TRIAGE_PROMPT_SECTION = """
## Triage
After investigation, assess complexity:

<TRIAGE>
COMPLEXITY: [LOW|HIGH]
CONFIDENCE: [0.0-1.0]
FAST_TRACK: [YES|NO]
</TRIAGE>

IF FAST_TRACK=YES, provide:
<MICRO_SPEC>
TARGET_FILE: path/to/file
LINE_HINT: ~42
OPERATION: [UPDATE|INSERT|DELETE]
INSTRUCTION: Exact change (e.g., "Add // TODO at line 42")
</MICRO_SPEC>

FAST_TRACK criteria:
- 1-2 files only
- No new imports/dependencies
- Obvious solution (can describe in 2 sentences)
- Not auth/payments/infra

IMPORTANT: If unsure, output FAST_TRACK=NO.
If cannot provide precise MICRO_SPEC, set FAST_TRACK=NO.
"""


def parse_triage(scout_output: str) -> TriageResult:
    """Extract triage decision from scout output.

    Parses triage info from scout output in either:
    - XML format: <TRIAGE>...</TRIAGE> and <MICRO_SPEC>...</MICRO_SPEC>
    - Markdown format: ## Triage and ## Micro Spec sections

    Returns TriageResult with fast_track=False if parsing fails or
    safety checks don't pass.
    """
    result = TriageResult()

    # Try XML format first
    triage_match = re.search(r'<TRIAGE>(.*?)</TRIAGE>', scout_output, re.DOTALL | re.IGNORECASE)
    spec_match = re.search(r'<MICRO_SPEC>(.*?)</MICRO_SPEC>', scout_output, re.DOTALL | re.IGNORECASE)

    # Fall back to markdown format: ## Triage section until next ## or ---
    if not triage_match:
        triage_match = re.search(r'##\s*Triage\s*\n(.*?)(?=\n##|\n---|\Z)', scout_output, re.DOTALL | re.IGNORECASE)
    if not spec_match:
        spec_match = re.search(r'##\s*Micro\s*Spec\s*\n(.*?)(?=\n##|\n---|\Z)', scout_output, re.DOTALL | re.IGNORECASE)

    if triage_match:
        content = triage_match.group(1)
        # Handle both "FAST_TRACK: YES" and "**FAST_TRACK:** YES" formats
        if re.search(r'\*?\*?FAST_TRACK\*?\*?:\*?\*?\s*YES', content, re.IGNORECASE):
            result.fast_track = True
            # Handle both "CONFIDENCE: 0.95" and "**CONFIDENCE:** 0.95"
            conf_match = re.search(r'\*?\*?CONFIDENCE\*?\*?:\*?\*?\s*([\d.]+)', content, re.IGNORECASE)
            if conf_match:
                try:
                    result.confidence = float(conf_match.group(1))
                except ValueError:
                    logger.warning("Invalid CONFIDENCE value: %r", conf_match.group(1))
                    result.confidence = 0.0

    # Get spec content - from dedicated section or from triage section itself
    if spec_match:
        spec_content = spec_match.group(1).strip()
    elif triage_match:
        # New simpler format: spec fields are in the Triage section
        spec_content = triage_match.group(1).strip()
    else:
        spec_content = None

    if spec_content:
        result.micro_spec = spec_content

        # Extract target file - handle markdown backticks and bold
        # Matches: "TARGET_FILE: path", "**TARGET_FILE:** `path`", etc.
        target_match = re.search(r'\*?\*?TARGET_FILE\*?\*?:\*?\*?\s*`?([^\s#`]+)`?', spec_content, re.IGNORECASE)
        if target_match:
            result.target_file = target_match.group(1)

    # Safety guards - require all three mandatory fields
    if result.fast_track:
        if not result.micro_spec:
            result.fast_track = False
        else:
            # Require TARGET_FILE, OPERATION, and INSTRUCTION fields (handle markdown bold)
            required_fields = re.search(
                r'\*?\*?TARGET_FILE\*?\*?:\*?\*?\s*`?[^\s#`]+`?.*\*?\*?OPERATION\*?\*?:\*?\*?\s*(UPDATE|INSERT|DELETE).*\*?\*?INSTRUCTION\*?\*?:\*?\*?\s*\S+',
                result.micro_spec,
                re.IGNORECASE | re.DOTALL
            )
            if not required_fields:
                logger.debug("MICRO_SPEC missing required fields, disabling fast track")
                result.fast_track = False

    return result


def should_fast_track(triage: TriageResult, threshold: float = 0.9) -> bool:
    """Determine if task should use fast-track path.

    Args:
        triage: TriageResult from parse_triage()
        threshold: Minimum confidence required (default 0.9)

    Returns:
        True if task qualifies for fast-track execution
    """
    return triage.fast_track and triage.confidence >= threshold


def _sanitize_header(text: str, max_len: int = 60) -> str:
    """Sanitize text for use in markdown header.

    - Strips leading/trailing whitespace
    - Replaces newlines with spaces
    - Removes markdown special chars that break headers
    - Truncates to max_len at word boundary
    """
    if not text:
        return "Apply changes"

    # Strip and replace newlines
    clean = text.strip().replace('\n', ' ').replace('\r', '')

    # Remove chars that break markdown headers
    clean = re.sub(r'[#\[\]`]', '', clean)

    # Collapse multiple spaces
    clean = re.sub(r'\s+', ' ', clean)

    # Truncate at word boundary if needed
    if len(clean) > max_len:
        # Leave room for "..."
        cut = clean[:max_len - 3]
        # Try to break at word boundary
        parts = cut.rsplit(' ', 1)
        if len(parts) > 1:
            clean = parts[0] + "..."
        else:
            # No space found, just truncate
            clean = cut + "..."

    return clean or "Apply changes"


def generate_synthetic_plan(triage: TriageResult) -> str:
    """Generate plan.md content from micro-spec.

    Creates a synthetic plan that matches the format expected by
    parse_steps() in core.py (## Step N: description).

    Args:
        triage: TriageResult with micro_spec populated

    Returns:
        Plan content string suitable for writing to plan.md
    """
    # Format must match parse_steps() regex: ## Step N: description
    description = _sanitize_header(triage.micro_spec)
    target = triage.target_file or "see instructions"

    return (
        "# Fast Track Plan\n\n"
        f"## Step 1: {description}\n\n"
        f"**Target:** {target}\n\n"
        f"**Instructions:**\n{triage.micro_spec}"
    )

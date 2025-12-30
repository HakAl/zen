"""Lint ratchet: capture baseline and detect new violations.

The ratchet model allows pre-existing violations to pass through while
blocking new ones. This prevents the "fix everything first" blocker.

Storage format: .zen/lint_baseline.json
{
    "file.py::RULE_NAME": 3,  // (file, rule) -> count
    ...
}

Line numbers are intentionally ignored for shift tolerance - if code moves
around, we still recognize the same violation count.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from zen_mode import linter

logger = logging.getLogger(__name__)


# Type alias for baseline: "(file, rule)" -> count
Baseline = Dict[str, int]


def _make_key(file: str, rule: str) -> str:
    """Create baseline key from file and rule.

    Uses "::" separator since it's unlikely in filenames and
    makes the JSON human-readable.
    """
    return f"{file}::{rule}"


def _parse_key(key: str) -> Tuple[str, str]:
    """Parse baseline key back to (file, rule)."""
    parts = key.rsplit("::", 1)
    if len(parts) != 2:
        return key, ""
    return parts[0], parts[1]


def capture_baseline(
    paths: List[str],
    baseline_file: Path,
    log_fn: Optional[Callable[[str], None]] = None,
) -> Baseline:
    """Capture lint violations as baseline.

    Runs linter on provided paths and stores (file, rule) -> count mapping.
    Line numbers are ignored for shift tolerance.

    Args:
        paths: File paths to lint
        baseline_file: Where to store baseline JSON
        log_fn: Optional logging function

    Returns:
        The baseline dict that was captured

    Raises:
        OSError: If baseline file cannot be written
    """
    if not paths:
        if log_fn:
            log_fn("[BASELINE] No files to baseline")
        return {}

    # Filter to existing files only
    existing = [p for p in paths if Path(p).exists()]
    if not existing:
        if log_fn:
            log_fn("[BASELINE] No existing files to baseline")
        return {}

    # Run linter - we want ALL violations for baseline, so use LOW severity
    try:
        violations: List[Dict] = []
        for path in existing:
            violations.extend(linter.check_file(path, min_severity="LOW"))
    except OSError as e:
        if log_fn:
            log_fn(f"[BASELINE] Linter error (continuing): {e}")
        return {}

    # Build baseline: (file, rule) -> count
    baseline: Baseline = {}
    for v in violations:
        key = _make_key(v["file"], v["rule"])
        baseline[key] = baseline.get(key, 0) + 1

    # Write baseline file
    baseline_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        baseline_file.write_text(json.dumps(baseline, indent=2, sort_keys=True))
    except OSError as e:
        if log_fn:
            log_fn(f"[BASELINE] Failed to write baseline: {e}")
        raise

    # Log summary
    total = sum(baseline.values())
    if log_fn:
        if total == 0:
            log_fn("[BASELINE] Clean - no pre-existing violations")
        else:
            log_fn(f"[BASELINE] Captured {total} pre-existing violations across {len(baseline)} (file, rule) pairs")

    return baseline


def load_baseline(baseline_file: Path) -> Baseline:
    """Load baseline from file.

    Args:
        baseline_file: Path to baseline JSON

    Returns:
        Baseline dict, or empty dict if file doesn't exist
    """
    if not baseline_file.exists():
        return {}

    try:
        return json.loads(baseline_file.read_text())
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        logger.warning(f"Could not load baseline from {baseline_file}: {e} - treating as empty")
        return {}

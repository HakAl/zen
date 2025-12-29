"""Claude CLI wrapper for zen_mode."""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from zen_mode.exceptions import ConfigError

logger = logging.getLogger(__name__)

_claude_exe: Optional[str] = None


def is_trusted_directory(cwd: Path) -> bool:
    """Check if cwd is within a trusted root.

    If ZEN_TRUST_ROOTS is set, only directories within those roots are trusted.
    If ZEN_TRUST_ROOTS is not set, falls back to ZEN_SKIP_PERMISSIONS behavior.

    Args:
        cwd: Current working directory to check

    Returns:
        True if directory is trusted for skip-permissions
    """
    trust_roots = os.getenv("ZEN_TRUST_ROOTS", "").split(os.pathsep)
    trust_roots = [r.strip() for r in trust_roots if r.strip()]

    if not trust_roots:
        # No roots specified - fall back to ZEN_SKIP_PERMISSIONS behavior
        return os.getenv("ZEN_SKIP_PERMISSIONS", "true").lower() != "false"

    cwd_path = cwd.resolve()
    for root in trust_roots:
        root_path = Path(root).resolve()
        try:
            cwd_path.relative_to(root_path)
            return True
        except ValueError:
            continue
    return False


def _init_claude() -> str:
    """Initialize Claude CLI path. Returns path or exits."""
    global _claude_exe
    if _claude_exe:
        return _claude_exe
    _claude_exe = shutil.which("claude") or os.getenv("CLAUDE_EXE")
    if not _claude_exe:
        raise ConfigError(
            "'claude' CLI not found. Install: npm i -g @anthropic-ai/claude-cli"
        )
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
    log_fn: Optional[Callable[[str], None]] = None,
    cost_callback: Optional[Callable[..., Any]] = None,
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
            logger.info(msg)

    claude_exe = _init_claude()
    cmd = [claude_exe, "-p", "--model", model, "--output-format", "json"]

    # Skip Claude permission prompts if directory is trusted
    # Trust is determined by ZEN_TRUST_ROOTS (scope-limited) or ZEN_SKIP_PERMISSIONS (global)
    if is_trusted_directory(project_root):
        cmd.insert(2, "--dangerously-skip-permissions")
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
        if data is None:
            _log(f"[ERROR] Failed to parse JSON response (len={len(stdout)}, first_100={stdout[:100]!r})")
            return None  # NOT raw stdout

        try:
            cost, tokens = _extract_cost(data)
            if cost_callback:
                cost_callback(phase, cost, tokens)

            if show_costs:
                total_tok = tokens["in"] + tokens["out"]
                _log(f"[COST] {model} {phase}: ${cost:.4f} ({tokens['in']}+{tokens['out']}={total_tok} tok)")
        except (KeyError, TypeError, ValueError) as e:
            _log(f"[WARN] Cost extraction failed: {e}")

        result = data.get("result")
        if result is not None and not isinstance(result, str):
            _log(f"[ERROR] result field is {type(result).__name__}, expected str")
            return None
        return result

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
                proc.wait()  # Process is dead, just reap it
        return None
    except OSError as e:
        # File not found, permission denied, etc.
        _log(f"[ERROR] OS error running Claude: {e}")
        if proc:
            proc.terminate()
            proc.communicate()
        return None
    except subprocess.SubprocessError as e:
        # Other subprocess-related errors
        _log(f"[ERROR] Subprocess error: {e}")
        if proc:
            proc.terminate()
            proc.communicate()
        return None

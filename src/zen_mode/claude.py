"""Claude CLI wrapper for zen_mode."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple


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

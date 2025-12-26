"""Logging utility for zen_mode."""
from __future__ import annotations

import time
from pathlib import Path


def log(msg: str, log_file: Path, work_dir: Path) -> None:
    """Log message to file and stdout."""
    work_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    with log_file.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(f"  {msg}")

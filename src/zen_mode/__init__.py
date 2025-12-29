"""Zen Mode: Minimalist autonomous agent runner."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("zen-mode")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"  # Not installed as package

from zen_mode.context import Context
from zen_mode.files import write_file, log
from zen_mode.claude import run_claude
from zen_mode.core import run

__all__ = [
    "Context",
    "write_file",
    "log",
    "run_claude",
    "run",
]

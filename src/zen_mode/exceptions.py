"""
Zen Mode Exception Hierarchy.

All exceptions raised by zen_mode should inherit from ZenError.
This enables library usage and proper testing (no sys.exit() in library code).
"""


class ZenError(Exception):
    """Base exception for all zen errors."""
    pass


class ScoutError(ZenError):
    """Error during scout phase."""
    pass


class PlanError(ZenError):
    """Error during planning phase."""
    pass


class ImplementError(ZenError):
    """Error during implementation phase."""
    pass


class VerifyError(ZenError):
    """Error during verification phase."""
    pass


class JudgeError(ZenError):
    """Error during judge phase."""
    pass


class ConfigError(ZenError):
    """Configuration or environment error."""
    pass


class CostBudgetExceeded(ZenError):
    """Task cost exceeded configured budget limit."""
    pass


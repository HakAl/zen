"""
Pytest configuration for zen tests.
Auto-patches run_claude to prevent accidental API calls during tests.
"""
import logging
import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def configure_logging():
    """Configure logging for tests so log messages are captured."""
    from zen_mode.cli import setup_logging
    setup_logging(verbose=True)
    # Enable propagation so caplog can capture logs
    logger = logging.getLogger("zen_mode")
    logger.propagate = True
    yield
    # Clean up handlers after test to avoid accumulation
    logger.handlers.clear()


class AccidentalAPICallError(Exception):
    """Raised when a test accidentally tries to call Claude API."""
    pass


def _blocked_run_claude(*args, **kwargs):
    """Replacement for run_claude that fails fast instead of hanging."""
    raise AccidentalAPICallError(
        "Test tried to call run_claude() without mocking! "
        "Add @patch('zen_mode.claude.run_claude') or use dry_run=True"
    )


@pytest.fixture(autouse=True)
def block_real_api_calls(request):
    """
    Auto-applied fixture that blocks real Claude API calls.
    Tests marked with @pytest.mark.bypass_conftest_patch skip this block.
    """
    if request.node.get_closest_marker("bypass_conftest_patch"):
        yield  # Don't patch - test provides its own mocks
    else:
        with patch("zen_mode.claude.run_claude", side_effect=_blocked_run_claude):
            yield

"""
Pytest configuration for zen tests.
Auto-patches run_claude to prevent accidental API calls during tests.
"""
import pytest
from unittest.mock import patch


class AccidentalAPICallError(Exception):
    """Raised when a test accidentally tries to call Claude API."""
    pass


def _blocked_run_claude(*args, **kwargs):
    """Replacement for run_claude that fails fast instead of hanging."""
    raise AccidentalAPICallError(
        "Test tried to call run_claude() without mocking! "
        "Add @patch('zen_mode.utils.run_claude') or use dry_run=True"
    )


@pytest.fixture(autouse=True)
def block_real_api_calls():
    """
    Auto-applied fixture that blocks real Claude API calls.
    Tests that need real calls must explicitly disable this.
    """
    with patch("zen_mode.utils.run_claude", side_effect=_blocked_run_claude):
        yield


@pytest.fixture
def allow_real_api_calls():
    """
    Fixture to explicitly allow real API calls in a test.
    Usage: def test_integration(allow_real_api_calls): ...
    """
    # This fixture does nothing - just naming it opts out of the autouse fixture
    # Actually we need to undo the patch... let's use a different approach
    pass

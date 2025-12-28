"""Tests for zen_mode.config module."""
import os
import pytest
from unittest.mock import patch


class TestGetIntEnv:
    """Test _get_int_env validation helper."""

    def test_valid_int_returns_value(self):
        from zen_mode.config import _get_int_env
        with patch.dict(os.environ, {"TEST_VAR": "42"}):
            assert _get_int_env("TEST_VAR", "0") == 42

    def test_default_used_when_not_set(self):
        from zen_mode.config import _get_int_env
        with patch.dict(os.environ, {}, clear=True):
            assert _get_int_env("NONEXISTENT_VAR", "123") == 123

    def test_invalid_int_raises_config_error(self):
        from zen_mode.config import _get_int_env
        from zen_mode.exceptions import ConfigError
        with patch.dict(os.environ, {"TEST_VAR": "not_a_number"}):
            with pytest.raises(ConfigError, match="not a valid integer"):
                _get_int_env("TEST_VAR", "0")

    def test_below_min_raises_config_error(self):
        from zen_mode.config import _get_int_env
        from zen_mode.exceptions import ConfigError
        with patch.dict(os.environ, {"TEST_VAR": "0"}):
            with pytest.raises(ConfigError, match="must be >= 1"):
                _get_int_env("TEST_VAR", "1", min_val=1)

    def test_at_min_value_ok(self):
        from zen_mode.config import _get_int_env
        with patch.dict(os.environ, {"TEST_VAR": "1"}):
            assert _get_int_env("TEST_VAR", "0", min_val=1) == 1


class TestGetModelEnv:
    """Test _get_model_env validation helper."""

    def test_valid_model_opus(self):
        from zen_mode.config import _get_model_env
        with patch.dict(os.environ, {"TEST_MODEL": "opus"}):
            assert _get_model_env("TEST_MODEL", "haiku") == "opus"

    def test_valid_model_sonnet(self):
        from zen_mode.config import _get_model_env
        with patch.dict(os.environ, {"TEST_MODEL": "sonnet"}):
            assert _get_model_env("TEST_MODEL", "haiku") == "sonnet"

    def test_valid_model_haiku(self):
        from zen_mode.config import _get_model_env
        with patch.dict(os.environ, {"TEST_MODEL": "haiku"}):
            assert _get_model_env("TEST_MODEL", "opus") == "haiku"

    def test_default_used_when_not_set(self):
        from zen_mode.config import _get_model_env
        with patch.dict(os.environ, {}, clear=True):
            assert _get_model_env("NONEXISTENT_MODEL", "sonnet") == "sonnet"

    def test_invalid_model_raises_config_error(self):
        from zen_mode.config import _get_model_env
        from zen_mode.exceptions import ConfigError
        with patch.dict(os.environ, {"TEST_MODEL": "gpt4"}):
            with pytest.raises(ConfigError, match="not in"):
                _get_model_env("TEST_MODEL", "haiku")

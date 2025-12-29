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


class TestGetBoolEnv:
    """Test _get_bool_env validation helper."""

    def test_true_values(self):
        from zen_mode.config import _get_bool_env
        for val in ("true", "True", "TRUE", "1", "yes", "YES", "on", "ON"):
            with patch.dict(os.environ, {"TEST_BOOL": val}):
                assert _get_bool_env("TEST_BOOL", "false") is True

    def test_false_values(self):
        from zen_mode.config import _get_bool_env
        for val in ("false", "False", "FALSE", "0", "no", "NO", "off", "OFF"):
            with patch.dict(os.environ, {"TEST_BOOL": val}):
                assert _get_bool_env("TEST_BOOL", "true") is False

    def test_default_used_when_not_set(self):
        from zen_mode.config import _get_bool_env
        with patch.dict(os.environ, {}, clear=True):
            assert _get_bool_env("NONEXISTENT_BOOL", "true") is True
            assert _get_bool_env("NONEXISTENT_BOOL", "false") is False

    def test_invalid_bool_raises_config_error(self):
        from zen_mode.config import _get_bool_env
        from zen_mode.exceptions import ConfigError
        with patch.dict(os.environ, {"TEST_BOOL": "maybe"}):
            with pytest.raises(ConfigError, match="not a valid boolean"):
                _get_bool_env("TEST_BOOL", "true")


class TestGetDirNameEnv:
    """Test _get_dir_name_env validation helper."""

    def test_valid_dir_name(self):
        from zen_mode.config import _get_dir_name_env
        with patch.dict(os.environ, {"TEST_DIR": ".zen"}):
            assert _get_dir_name_env("TEST_DIR", ".default") == ".zen"

    def test_default_used_when_not_set(self):
        from zen_mode.config import _get_dir_name_env
        with patch.dict(os.environ, {}, clear=True):
            assert _get_dir_name_env("NONEXISTENT_DIR", ".zen") == ".zen"

    def test_path_with_slash_raises_error(self):
        from zen_mode.config import _get_dir_name_env
        from zen_mode.exceptions import ConfigError
        with patch.dict(os.environ, {"TEST_DIR": "foo/bar"}):
            with pytest.raises(ConfigError, match="must be a directory name"):
                _get_dir_name_env("TEST_DIR", ".zen")

    def test_path_with_backslash_raises_error(self):
        from zen_mode.config import _get_dir_name_env
        from zen_mode.exceptions import ConfigError
        with patch.dict(os.environ, {"TEST_DIR": "foo\\bar"}):
            with pytest.raises(ConfigError, match="must be a directory name"):
                _get_dir_name_env("TEST_DIR", ".zen")

    def test_dotdot_raises_error(self):
        from zen_mode.config import _get_dir_name_env
        from zen_mode.exceptions import ConfigError
        with patch.dict(os.environ, {"TEST_DIR": ".."}):
            with pytest.raises(ConfigError, match="path traversal"):
                _get_dir_name_env("TEST_DIR", ".zen")

    def test_empty_raises_error(self):
        from zen_mode.config import _get_dir_name_env
        from zen_mode.exceptions import ConfigError
        with patch.dict(os.environ, {"TEST_DIR": ""}):
            with pytest.raises(ConfigError, match="cannot be empty"):
                _get_dir_name_env("TEST_DIR", ".zen")

    def test_invalid_chars_raises_error(self):
        from zen_mode.config import _get_dir_name_env
        from zen_mode.exceptions import ConfigError
        with patch.dict(os.environ, {"TEST_DIR": "foo:bar"}):
            with pytest.raises(ConfigError, match="invalid characters"):
                _get_dir_name_env("TEST_DIR", ".zen")


class TestGetPathsEnv:
    """Test _get_paths_env validation helper."""

    def test_empty_returns_empty_list(self):
        from zen_mode.config import _get_paths_env
        with patch.dict(os.environ, {"TEST_PATHS": ""}):
            assert _get_paths_env("TEST_PATHS") == []

    def test_not_set_returns_empty_list(self):
        from zen_mode.config import _get_paths_env
        with patch.dict(os.environ, {}, clear=True):
            assert _get_paths_env("NONEXISTENT_PATHS") == []

    def test_single_existing_path(self, tmp_path):
        from zen_mode.config import _get_paths_env
        with patch.dict(os.environ, {"TEST_PATHS": str(tmp_path)}):
            result = _get_paths_env("TEST_PATHS")
            assert len(result) == 1
            assert result[0] == tmp_path.resolve()

    def test_multiple_existing_paths(self, tmp_path):
        from zen_mode.config import _get_paths_env
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()
        with patch.dict(os.environ, {"TEST_PATHS": f"{dir1}{os.pathsep}{dir2}"}):
            result = _get_paths_env("TEST_PATHS")
            assert len(result) == 2
            assert dir1.resolve() in result
            assert dir2.resolve() in result

    def test_nonexistent_path_raises_error(self):
        from zen_mode.config import _get_paths_env
        from zen_mode.exceptions import ConfigError
        with patch.dict(os.environ, {"TEST_PATHS": "/nonexistent/path"}):
            with pytest.raises(ConfigError, match="does not exist"):
                _get_paths_env("TEST_PATHS")


class TestGetExeEnv:
    """Test _get_exe_env validation helper."""

    def test_not_set_returns_none(self):
        from zen_mode.config import _get_exe_env
        with patch.dict(os.environ, {}, clear=True):
            assert _get_exe_env("NONEXISTENT_EXE") is None

    def test_empty_returns_none(self):
        from zen_mode.config import _get_exe_env
        with patch.dict(os.environ, {"TEST_EXE": ""}):
            assert _get_exe_env("TEST_EXE") is None

    def test_valid_exe_in_path(self):
        from zen_mode.config import _get_exe_env
        # Python should be in PATH on any test system
        with patch.dict(os.environ, {"TEST_EXE": "python"}):
            result = _get_exe_env("TEST_EXE")
            assert result is not None
            assert "python" in result.lower()

    def test_nonexistent_exe_raises_error(self):
        from zen_mode.config import _get_exe_env
        from zen_mode.exceptions import ConfigError
        with patch.dict(os.environ, {"TEST_EXE": "/nonexistent/binary"}):
            with pytest.raises(ConfigError, match="does not exist"):
                _get_exe_env("TEST_EXE")

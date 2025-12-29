"""
Tests for zen_mode.claude module - Claude CLI wrapper.

Tests cover:
1. _init_claude() - Finds Claude CLI executable
2. is_trusted_directory() - Trust roots checking (via import from config)
3. run_claude() - Main function (mock subprocess.Popen)
4. _parse_json_response() - Parse JSON from CLI output
5. _extract_cost() - Extracts cost from JSON response
6. Command building - Check flags like --dangerously-skip-permissions
7. Timeout handling
8. Error responses from Claude
"""
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, Mock

import pytest

# Add src to path so zen_mode can be imported
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestInitClaude:
    """Tests for _init_claude() function."""

    def test_returns_cached_exe_if_set(self):
        """Should return cached exe without looking up again."""
        from zen_mode import claude

        # Set cached value
        original = claude._claude_exe
        try:
            claude._claude_exe = "/cached/claude"
            result = claude._init_claude()
            assert result == "/cached/claude"
        finally:
            claude._claude_exe = original

    def test_uses_config_exe_first(self, monkeypatch):
        """Should use CLAUDE_EXE from config if set."""
        from zen_mode import claude
        from zen_mode.config import _get_exe_env

        original = claude._claude_exe
        try:
            claude._claude_exe = None
            # Mock get_claude_exe to return a configured path
            monkeypatch.setattr(
                "zen_mode.claude.get_claude_exe",
                lambda: "/configured/claude"
            )
            result = claude._init_claude()
            assert result == "/configured/claude"
        finally:
            claude._claude_exe = original

    def test_falls_back_to_path(self, monkeypatch):
        """Should fall back to shutil.which if config not set."""
        from zen_mode import claude

        original = claude._claude_exe
        try:
            claude._claude_exe = None
            # Mock get_claude_exe to return None
            monkeypatch.setattr("zen_mode.claude.get_claude_exe", lambda: None)
            # Mock shutil.which to return a path
            monkeypatch.setattr("zen_mode.claude.shutil.which", lambda x: "/path/claude")
            result = claude._init_claude()
            assert result == "/path/claude"
        finally:
            claude._claude_exe = original

    def test_raises_config_error_if_not_found(self, monkeypatch):
        """Should raise ConfigError if claude not found anywhere."""
        from zen_mode import claude
        from zen_mode.exceptions import ConfigError

        original = claude._claude_exe
        try:
            claude._claude_exe = None
            monkeypatch.setattr("zen_mode.claude.get_claude_exe", lambda: None)
            monkeypatch.setattr("zen_mode.claude.shutil.which", lambda x: None)

            with pytest.raises(ConfigError, match="CLI not found"):
                claude._init_claude()
        finally:
            claude._claude_exe = original


class TestParseJsonResponse:
    """Tests for _parse_json_response() function."""

    def test_parses_clean_json(self):
        """Should parse clean JSON response."""
        from zen_mode.claude import _parse_json_response

        stdout = '{"result": "test output", "total_cost_usd": 0.01}'
        result = _parse_json_response(stdout)
        assert result == {"result": "test output", "total_cost_usd": 0.01}

    def test_strips_warning_prefix(self):
        """Should strip warning text before JSON."""
        from zen_mode.claude import _parse_json_response

        stdout = 'Warning: some warning\n{"result": "test"}'
        result = _parse_json_response(stdout)
        assert result == {"result": "test"}

    def test_returns_none_for_no_json(self):
        """Should return None if no JSON found."""
        from zen_mode.claude import _parse_json_response

        stdout = "No JSON here at all"
        result = _parse_json_response(stdout)
        assert result is None

    def test_returns_none_for_invalid_json(self):
        """Should return None for invalid JSON."""
        from zen_mode.claude import _parse_json_response

        stdout = '{"result": "incomplete'
        result = _parse_json_response(stdout)
        assert result is None

    def test_handles_nested_json(self):
        """Should parse nested JSON structures."""
        from zen_mode.claude import _parse_json_response

        data = {
            "result": "test",
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "total_cost_usd": 0.01
        }
        stdout = json.dumps(data)
        result = _parse_json_response(stdout)
        assert result == data


class TestExtractCost:
    """Tests for _extract_cost() function."""

    def test_extracts_cost_and_tokens(self):
        """Should extract cost and token counts."""
        from zen_mode.claude import _extract_cost

        raw = {
            "total_cost_usd": 0.0123,
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_read_input_tokens": 10
            }
        }
        cost, tokens = _extract_cost(raw)
        assert cost == 0.0123
        assert tokens == {"in": 100, "out": 50, "cache_read": 10}

    def test_handles_missing_cost(self):
        """Should handle missing total_cost_usd."""
        from zen_mode.claude import _extract_cost

        raw = {"usage": {"input_tokens": 100, "output_tokens": 50}}
        cost, tokens = _extract_cost(raw)
        assert cost == 0.0

    def test_handles_missing_usage(self):
        """Should handle missing usage field."""
        from zen_mode.claude import _extract_cost

        raw = {"total_cost_usd": 0.01}
        cost, tokens = _extract_cost(raw)
        assert tokens == {"in": 0, "out": 0, "cache_read": 0}

    def test_handles_empty_dict(self):
        """Should handle empty response."""
        from zen_mode.claude import _extract_cost

        raw = {}
        cost, tokens = _extract_cost(raw)
        assert cost == 0.0
        assert tokens == {"in": 0, "out": 0, "cache_read": 0}

    def test_handles_none_values(self):
        """Should handle None values in usage."""
        from zen_mode.claude import _extract_cost

        raw = {
            "total_cost_usd": None,
            "usage": {
                "input_tokens": None,
                "output_tokens": None,
                "cache_read_input_tokens": None
            }
        }
        cost, tokens = _extract_cost(raw)
        assert cost == 0.0
        assert tokens == {"in": 0, "out": 0, "cache_read": 0}


class TestRunClaudeCommandBuilding:
    """Tests for command construction in run_claude()."""

    @pytest.mark.bypass_conftest_patch
    @patch('zen_mode.claude.subprocess.Popen')
    @patch('zen_mode.claude._init_claude', return_value='/usr/bin/claude')
    def test_basic_command_structure(self, mock_init, mock_popen, tmp_path, monkeypatch):
        """Should build correct basic command."""
        monkeypatch.delenv("ZEN_SKIP_PERMISSIONS", raising=False)
        monkeypatch.delenv("ZEN_TRUST_ROOTS", raising=False)

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ('{"result": "test"}', '')
        mock_popen.return_value = mock_proc

        from zen_mode.claude import run_claude
        run_claude("test prompt", "sonnet", project_root=tmp_path)

        call_args = mock_popen.call_args
        cmd = call_args[0][0]

        # Check basic structure
        assert cmd[0] == '/usr/bin/claude'
        assert '-p' in cmd
        assert '--model' in cmd
        assert 'sonnet' in cmd
        assert '--output-format' in cmd
        assert 'json' in cmd

    @pytest.mark.bypass_conftest_patch
    @patch('zen_mode.claude.subprocess.Popen')
    @patch('zen_mode.claude._init_claude', return_value='/usr/bin/claude')
    def test_skip_permissions_flag_when_trusted(self, mock_init, mock_popen, tmp_path, monkeypatch):
        """Should include --dangerously-skip-permissions when directory is trusted."""
        monkeypatch.delenv("ZEN_TRUST_ROOTS", raising=False)
        monkeypatch.setenv("ZEN_SKIP_PERMISSIONS", "true")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ('{"result": "test"}', '')
        mock_popen.return_value = mock_proc

        from zen_mode.claude import run_claude
        run_claude("test prompt", "sonnet", project_root=tmp_path)

        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        assert "--dangerously-skip-permissions" in cmd

    @pytest.mark.bypass_conftest_patch
    @patch('zen_mode.claude.subprocess.Popen')
    @patch('zen_mode.claude._init_claude', return_value='/usr/bin/claude')
    def test_no_skip_permissions_when_untrusted(self, mock_init, mock_popen, tmp_path, monkeypatch):
        """Should NOT include --dangerously-skip-permissions when untrusted."""
        monkeypatch.setenv("ZEN_SKIP_PERMISSIONS", "false")
        monkeypatch.delenv("ZEN_TRUST_ROOTS", raising=False)

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ('{"result": "test"}', '')
        mock_popen.return_value = mock_proc

        from zen_mode.claude import run_claude
        run_claude("test prompt", "sonnet", project_root=tmp_path)

        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        assert "--dangerously-skip-permissions" not in cmd

    @pytest.mark.bypass_conftest_patch
    @patch('zen_mode.claude.subprocess.Popen')
    @patch('zen_mode.claude._init_claude', return_value='/usr/bin/claude')
    def test_different_models(self, mock_init, mock_popen, tmp_path, monkeypatch):
        """Should use specified model in command."""
        monkeypatch.setenv("ZEN_SKIP_PERMISSIONS", "false")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ('{"result": "test"}', '')
        mock_popen.return_value = mock_proc

        from zen_mode.claude import run_claude

        for model in ["opus", "sonnet", "haiku"]:
            run_claude("test", model, project_root=tmp_path)
            call_args = mock_popen.call_args
            cmd = call_args[0][0]
            model_idx = cmd.index("--model")
            assert cmd[model_idx + 1] == model


class TestRunClaudeSuccess:
    """Tests for successful run_claude() execution."""

    @pytest.mark.bypass_conftest_patch
    @patch('zen_mode.claude.subprocess.Popen')
    @patch('zen_mode.claude._init_claude', return_value='/usr/bin/claude')
    def test_returns_result_on_success(self, mock_init, mock_popen, tmp_path, monkeypatch):
        """Should return result field from JSON response."""
        monkeypatch.setenv("ZEN_SKIP_PERMISSIONS", "false")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            '{"result": "The answer is 42", "total_cost_usd": 0.01}',
            ''
        )
        mock_popen.return_value = mock_proc

        from zen_mode.claude import run_claude
        result = run_claude("What is the answer?", "sonnet", project_root=tmp_path)
        assert result == "The answer is 42"

    @pytest.mark.bypass_conftest_patch
    @patch('zen_mode.claude.subprocess.Popen')
    @patch('zen_mode.claude._init_claude', return_value='/usr/bin/claude')
    def test_writes_prompt_to_stdin(self, mock_init, mock_popen, tmp_path, monkeypatch):
        """Should write prompt to process stdin."""
        monkeypatch.setenv("ZEN_SKIP_PERMISSIONS", "false")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ('{"result": "ok"}', '')
        mock_popen.return_value = mock_proc

        from zen_mode.claude import run_claude
        run_claude("Test prompt here", "sonnet", project_root=tmp_path)

        mock_proc.stdin.write.assert_called_once_with("Test prompt here")
        mock_proc.stdin.close.assert_called_once()

    @pytest.mark.bypass_conftest_patch
    @patch('zen_mode.claude.subprocess.Popen')
    @patch('zen_mode.claude._init_claude', return_value='/usr/bin/claude')
    def test_uses_project_root_as_cwd(self, mock_init, mock_popen, tmp_path, monkeypatch):
        """Should use project_root as working directory."""
        monkeypatch.setenv("ZEN_SKIP_PERMISSIONS", "false")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ('{"result": "ok"}', '')
        mock_popen.return_value = mock_proc

        from zen_mode.claude import run_claude
        run_claude("test", "sonnet", project_root=tmp_path)

        call_kwargs = mock_popen.call_args[1]
        assert call_kwargs['cwd'] == tmp_path

    @pytest.mark.bypass_conftest_patch
    @patch('zen_mode.claude.subprocess.Popen')
    @patch('zen_mode.claude._init_claude', return_value='/usr/bin/claude')
    def test_calls_cost_callback(self, mock_init, mock_popen, tmp_path, monkeypatch):
        """Should call cost_callback with phase, cost, and tokens."""
        monkeypatch.setenv("ZEN_SKIP_PERMISSIONS", "false")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            json.dumps({
                "result": "ok",
                "total_cost_usd": 0.05,
                "usage": {"input_tokens": 100, "output_tokens": 200, "cache_read_input_tokens": 50}
            }),
            ''
        )
        mock_popen.return_value = mock_proc

        callback_calls = []

        def cost_callback(phase, cost, tokens):
            callback_calls.append((phase, cost, tokens))

        from zen_mode.claude import run_claude
        run_claude(
            "test", "sonnet",
            phase="scout",
            project_root=tmp_path,
            cost_callback=cost_callback
        )

        assert len(callback_calls) == 1
        phase, cost, tokens = callback_calls[0]
        assert phase == "scout"
        assert cost == 0.05
        assert tokens == {"in": 100, "out": 200, "cache_read": 50}


class TestRunClaudeErrors:
    """Tests for error handling in run_claude()."""

    @pytest.mark.bypass_conftest_patch
    @patch('zen_mode.claude.subprocess.Popen')
    @patch('zen_mode.claude._init_claude', return_value='/usr/bin/claude')
    def test_returns_none_on_nonzero_exit(self, mock_init, mock_popen, tmp_path, monkeypatch):
        """Should return None when subprocess exits with error."""
        monkeypatch.setenv("ZEN_SKIP_PERMISSIONS", "false")

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate.return_value = ('', 'Error: something failed')
        mock_popen.return_value = mock_proc

        from zen_mode.claude import run_claude
        result = run_claude("test", "sonnet", project_root=tmp_path)
        assert result is None

    @pytest.mark.bypass_conftest_patch
    @patch('zen_mode.claude.subprocess.Popen')
    @patch('zen_mode.claude._init_claude', return_value='/usr/bin/claude')
    def test_returns_none_on_invalid_json(self, mock_init, mock_popen, tmp_path, monkeypatch):
        """Should return None when response is not valid JSON."""
        monkeypatch.setenv("ZEN_SKIP_PERMISSIONS", "false")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ('Not JSON at all', '')
        mock_popen.return_value = mock_proc

        from zen_mode.claude import run_claude
        result = run_claude("test", "sonnet", project_root=tmp_path)
        assert result is None

    @pytest.mark.bypass_conftest_patch
    @patch('zen_mode.claude.subprocess.Popen')
    @patch('zen_mode.claude._init_claude', return_value='/usr/bin/claude')
    def test_returns_none_when_result_not_string(self, mock_init, mock_popen, tmp_path, monkeypatch):
        """Should return None when result field is not a string."""
        monkeypatch.setenv("ZEN_SKIP_PERMISSIONS", "false")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ('{"result": 123}', '')
        mock_popen.return_value = mock_proc

        from zen_mode.claude import run_claude
        result = run_claude("test", "sonnet", project_root=tmp_path)
        assert result is None

    @pytest.mark.bypass_conftest_patch
    @patch('zen_mode.claude.subprocess.Popen')
    @patch('zen_mode.claude._init_claude', return_value='/usr/bin/claude')
    def test_logs_error_on_failure(self, mock_init, mock_popen, tmp_path, monkeypatch, caplog):
        """Should log error message on failure."""
        import logging
        monkeypatch.setenv("ZEN_SKIP_PERMISSIONS", "false")

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate.return_value = ('', 'API Error: rate limited')
        mock_popen.return_value = mock_proc

        from zen_mode.claude import run_claude
        with caplog.at_level(logging.INFO, logger="zen_mode"):
            run_claude("test", "sonnet", project_root=tmp_path)

        assert any("ERROR" in record.message and "rate limited" in record.message
                  for record in caplog.records)

    @pytest.mark.bypass_conftest_patch
    @patch('zen_mode.claude.subprocess.Popen')
    @patch('zen_mode.claude._init_claude', return_value='/usr/bin/claude')
    def test_handles_broken_pipe(self, mock_init, mock_popen, tmp_path, monkeypatch):
        """Should handle BrokenPipeError on stdin."""
        monkeypatch.setenv("ZEN_SKIP_PERMISSIONS", "false")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdin.write.side_effect = BrokenPipeError("pipe broken")
        mock_proc.communicate.return_value = ('{"result": "ok"}', '')
        mock_popen.return_value = mock_proc

        from zen_mode.claude import run_claude
        # Should not raise, should continue and return result
        result = run_claude("test", "sonnet", project_root=tmp_path)
        assert result == "ok"


class TestRunClaudeTimeout:
    """Tests for timeout handling in run_claude()."""

    @pytest.mark.bypass_conftest_patch
    @patch('zen_mode.claude.subprocess.Popen')
    @patch('zen_mode.claude._init_claude', return_value='/usr/bin/claude')
    def test_returns_none_on_timeout(self, mock_init, mock_popen, tmp_path, monkeypatch):
        """Should return None when subprocess times out."""
        monkeypatch.setenv("ZEN_SKIP_PERMISSIONS", "false")

        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = subprocess.TimeoutExpired("claude", 600)
        mock_popen.return_value = mock_proc

        from zen_mode.claude import run_claude
        result = run_claude("test", "sonnet", project_root=tmp_path, timeout=600)
        assert result is None

    @pytest.mark.bypass_conftest_patch
    @patch('zen_mode.claude.subprocess.Popen')
    @patch('zen_mode.claude._init_claude', return_value='/usr/bin/claude')
    def test_terminates_process_on_timeout(self, mock_init, mock_popen, tmp_path, monkeypatch):
        """Should terminate process on timeout."""
        monkeypatch.setenv("ZEN_SKIP_PERMISSIONS", "false")

        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = [
            subprocess.TimeoutExpired("claude", 600),
            ('partial output', '')  # Second call after terminate
        ]
        mock_popen.return_value = mock_proc

        from zen_mode.claude import run_claude
        run_claude("test", "sonnet", project_root=tmp_path, timeout=600)

        mock_proc.terminate.assert_called_once()

    @pytest.mark.bypass_conftest_patch
    @patch('zen_mode.claude.subprocess.Popen')
    @patch('zen_mode.claude._init_claude', return_value='/usr/bin/claude')
    def test_kills_process_if_terminate_hangs(self, mock_init, mock_popen, tmp_path, monkeypatch):
        """Should kill process if terminate does not work."""
        monkeypatch.setenv("ZEN_SKIP_PERMISSIONS", "false")

        mock_proc = MagicMock()
        # First communicate times out, second also times out (terminate failed)
        mock_proc.communicate.side_effect = [
            subprocess.TimeoutExpired("claude", 600),
            subprocess.TimeoutExpired("claude", 5)
        ]
        mock_popen.return_value = mock_proc

        from zen_mode.claude import run_claude
        run_claude("test", "sonnet", project_root=tmp_path, timeout=600)

        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()
        mock_proc.wait.assert_called_once()

    @pytest.mark.bypass_conftest_patch
    @patch('zen_mode.claude.subprocess.Popen')
    @patch('zen_mode.claude._init_claude', return_value='/usr/bin/claude')
    def test_uses_custom_timeout(self, mock_init, mock_popen, tmp_path, monkeypatch):
        """Should use provided timeout value."""
        monkeypatch.setenv("ZEN_SKIP_PERMISSIONS", "false")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = ('{"result": "ok"}', '')
        mock_popen.return_value = mock_proc

        from zen_mode.claude import run_claude
        run_claude("test", "sonnet", project_root=tmp_path, timeout=120)

        mock_proc.communicate.assert_called_once_with(timeout=120)


class TestRunClaudeOSErrors:
    """Tests for OS error handling in run_claude()."""

    @pytest.mark.bypass_conftest_patch
    @patch('zen_mode.claude.subprocess.Popen')
    @patch('zen_mode.claude._init_claude', return_value='/usr/bin/claude')
    def test_handles_file_not_found(self, mock_init, mock_popen, tmp_path, monkeypatch):
        """Should handle FileNotFoundError gracefully."""
        monkeypatch.setenv("ZEN_SKIP_PERMISSIONS", "false")

        mock_popen.side_effect = FileNotFoundError("claude not found")

        from zen_mode.claude import run_claude
        result = run_claude("test", "sonnet", project_root=tmp_path)
        assert result is None

    @pytest.mark.bypass_conftest_patch
    @patch('zen_mode.claude.subprocess.Popen')
    @patch('zen_mode.claude._init_claude', return_value='/usr/bin/claude')
    def test_handles_permission_denied(self, mock_init, mock_popen, tmp_path, monkeypatch):
        """Should handle PermissionError gracefully."""
        monkeypatch.setenv("ZEN_SKIP_PERMISSIONS", "false")

        mock_popen.side_effect = PermissionError("Permission denied")

        from zen_mode.claude import run_claude
        result = run_claude("test", "sonnet", project_root=tmp_path)
        assert result is None

    @pytest.mark.bypass_conftest_patch
    @patch('zen_mode.claude.subprocess.Popen')
    @patch('zen_mode.claude._init_claude', return_value='/usr/bin/claude')
    def test_handles_subprocess_error(self, mock_init, mock_popen, tmp_path, monkeypatch):
        """Should handle generic SubprocessError gracefully."""
        monkeypatch.setenv("ZEN_SKIP_PERMISSIONS", "false")

        mock_popen.side_effect = subprocess.SubprocessError("Some subprocess error")

        from zen_mode.claude import run_claude
        result = run_claude("test", "sonnet", project_root=tmp_path)
        assert result is None


class TestRunClaudeLogging:
    """Tests for logging behavior in run_claude()."""

    @pytest.mark.bypass_conftest_patch
    @patch('zen_mode.claude.subprocess.Popen')
    @patch('zen_mode.claude._init_claude', return_value='/usr/bin/claude')
    def test_custom_log_function(self, mock_init, mock_popen, tmp_path, monkeypatch):
        """Should use custom log function when provided."""
        monkeypatch.setenv("ZEN_SKIP_PERMISSIONS", "false")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            '{"result": "ok", "total_cost_usd": 0.01, "usage": {"input_tokens": 10, "output_tokens": 5}}',
            ''
        )
        mock_popen.return_value = mock_proc

        log_messages = []

        def custom_log(msg):
            log_messages.append(msg)

        from zen_mode.claude import run_claude
        run_claude(
            "test", "sonnet",
            project_root=tmp_path,
            log_fn=custom_log,
            show_costs=True
        )

        # Should have logged cost info
        assert any("[COST]" in msg for msg in log_messages)

    @pytest.mark.bypass_conftest_patch
    @patch('zen_mode.claude.subprocess.Popen')
    @patch('zen_mode.claude._init_claude', return_value='/usr/bin/claude')
    def test_show_costs_false_suppresses_cost_log(self, mock_init, mock_popen, tmp_path, monkeypatch):
        """Should not log costs when show_costs=False."""
        monkeypatch.setenv("ZEN_SKIP_PERMISSIONS", "false")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            '{"result": "ok", "total_cost_usd": 0.01, "usage": {"input_tokens": 10, "output_tokens": 5}}',
            ''
        )
        mock_popen.return_value = mock_proc

        log_messages = []

        def custom_log(msg):
            log_messages.append(msg)

        from zen_mode.claude import run_claude
        run_claude(
            "test", "sonnet",
            project_root=tmp_path,
            log_fn=custom_log,
            show_costs=False
        )

        # Should NOT have logged cost info
        assert not any("[COST]" in msg for msg in log_messages)

    @pytest.mark.bypass_conftest_patch
    @patch('zen_mode.claude.subprocess.Popen')
    @patch('zen_mode.claude._init_claude', return_value='/usr/bin/claude')
    def test_logs_timeout_with_phase_debug(self, mock_init, mock_popen, tmp_path, monkeypatch):
        """Should log debug info for verify phase timeout."""
        monkeypatch.setenv("ZEN_SKIP_PERMISSIONS", "false")

        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = [
            subprocess.TimeoutExpired("claude", 600),
            ('partial', '')
        ]
        mock_popen.return_value = mock_proc

        log_messages = []

        def custom_log(msg):
            log_messages.append(msg)

        from zen_mode.claude import run_claude
        run_claude(
            "test", "sonnet",
            phase="verify",
            project_root=tmp_path,
            log_fn=custom_log,
            timeout=600
        )

        # Should log timeout error and partial output debug for verify phase
        assert any("timed out" in msg for msg in log_messages)
        assert any("DEBUG" in msg and "Timeout partial" in msg for msg in log_messages)


class TestIsTrustedDirectory:
    """Tests for is_trusted_directory() (imported from config)."""

    def test_trusted_when_skip_permissions_default(self, tmp_path, monkeypatch):
        """Should be trusted by default (ZEN_SKIP_PERMISSIONS defaults to true)."""
        monkeypatch.delenv("ZEN_TRUST_ROOTS", raising=False)
        monkeypatch.delenv("ZEN_SKIP_PERMISSIONS", raising=False)

        from zen_mode.config import is_trusted_directory
        assert is_trusted_directory(tmp_path) is True

    def test_not_trusted_when_skip_permissions_false(self, tmp_path, monkeypatch):
        """Should not be trusted when ZEN_SKIP_PERMISSIONS=false."""
        monkeypatch.delenv("ZEN_TRUST_ROOTS", raising=False)
        monkeypatch.setenv("ZEN_SKIP_PERMISSIONS", "false")

        from zen_mode.config import is_trusted_directory
        assert is_trusted_directory(tmp_path) is False

    def test_trust_roots_exact_match(self, tmp_path, monkeypatch):
        """Should trust exact match of trust root."""
        monkeypatch.setenv("ZEN_TRUST_ROOTS", str(tmp_path))

        from zen_mode.config import is_trusted_directory
        assert is_trusted_directory(tmp_path) is True

    def test_trust_roots_subdirectory(self, tmp_path, monkeypatch):
        """Should trust subdirectory of trust root."""
        subdir = tmp_path / "project"
        subdir.mkdir()
        monkeypatch.setenv("ZEN_TRUST_ROOTS", str(tmp_path))

        from zen_mode.config import is_trusted_directory
        assert is_trusted_directory(subdir) is True

    def test_trust_roots_rejects_outside(self, tmp_path, monkeypatch):
        """Should reject directory outside trust roots."""
        trusted = tmp_path / "trusted"
        trusted.mkdir()
        untrusted = tmp_path / "untrusted"
        untrusted.mkdir()
        monkeypatch.setenv("ZEN_TRUST_ROOTS", str(trusted))

        from zen_mode.config import is_trusted_directory
        assert is_trusted_directory(untrusted) is False


class TestRunClaudeIntegration:
    """Integration tests for run_claude() with realistic scenarios."""

    @pytest.mark.bypass_conftest_patch
    @patch('zen_mode.claude.subprocess.Popen')
    @patch('zen_mode.claude._init_claude', return_value='/usr/bin/claude')
    def test_full_successful_flow(self, mock_init, mock_popen, tmp_path, monkeypatch):
        """Test complete successful execution flow."""
        monkeypatch.setenv("ZEN_SKIP_PERMISSIONS", "true")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            json.dumps({
                "result": "Here is the implementation:\n```python\nprint('hello')\n```",
                "total_cost_usd": 0.0234,
                "usage": {
                    "input_tokens": 500,
                    "output_tokens": 150,
                    "cache_read_input_tokens": 100
                }
            }),
            ''
        )
        mock_popen.return_value = mock_proc

        cost_data = []

        def track_cost(phase, cost, tokens):
            cost_data.append({"phase": phase, "cost": cost, "tokens": tokens})

        from zen_mode.claude import run_claude
        result = run_claude(
            "Implement a hello world function",
            "opus",
            phase="implement",
            project_root=tmp_path,
            cost_callback=track_cost,
            timeout=300
        )

        # Verify result
        assert "implementation" in result
        assert "python" in result

        # Verify cost tracking
        assert len(cost_data) == 1
        assert cost_data[0]["phase"] == "implement"
        assert cost_data[0]["cost"] == 0.0234
        assert cost_data[0]["tokens"]["in"] == 500

        # Verify command
        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        assert "--dangerously-skip-permissions" in cmd
        assert "opus" in cmd

    @pytest.mark.bypass_conftest_patch
    @patch('zen_mode.claude.subprocess.Popen')
    @patch('zen_mode.claude._init_claude', return_value='/usr/bin/claude')
    def test_response_with_warnings(self, mock_init, mock_popen, tmp_path, monkeypatch):
        """Should handle response with warning prefixes."""
        monkeypatch.setenv("ZEN_SKIP_PERMISSIONS", "false")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        # Response with warning prefix before JSON
        mock_proc.communicate.return_value = (
            'Warning: Model approaching token limit\n{"result": "answer", "total_cost_usd": 0.01}',
            ''
        )
        mock_popen.return_value = mock_proc

        from zen_mode.claude import run_claude
        result = run_claude("test", "sonnet", project_root=tmp_path)

        assert result == "answer"

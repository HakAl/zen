"""
Tests for cost tracking functionality.
"""
import sys
from pathlib import Path

import pytest

# Import from package - cost tracking functions are in claude module
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from zen_mode.claude import _extract_cost, _parse_json_response


class TestExtractCost:
    """Tests for _extract_cost() function."""

    def test_valid_full_response(self):
        """Extract cost and tokens from complete response."""
        sample = {
            "total_cost_usd": 0.00123,
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_read_input_tokens": 500,
            },
        }
        cost, tok = _extract_cost(sample)
        assert cost == 0.00123
        assert tok == {"in": 100, "out": 50, "cache_read": 500}

    def test_empty_dict(self):
        """Empty dict returns zeros."""
        cost, tok = _extract_cost({})
        assert cost == 0
        assert tok == {"in": 0, "out": 0, "cache_read": 0}

    def test_none_usage(self):
        """None usage field returns zeros."""
        cost, tok = _extract_cost({"usage": None})
        assert cost == 0
        assert tok == {"in": 0, "out": 0, "cache_read": 0}

    def test_missing_cost_field(self):
        """Missing total_cost_usd returns zero cost."""
        sample = {"usage": {"input_tokens": 100, "output_tokens": 50}}
        cost, tok = _extract_cost(sample)
        assert cost == 0
        assert tok["in"] == 100
        assert tok["out"] == 50

    def test_partial_usage(self):
        """Partial usage fields return zeros for missing."""
        sample = {"total_cost_usd": 0.001, "usage": {"input_tokens": 100}}
        cost, tok = _extract_cost(sample)
        assert cost == 0.001
        assert tok == {"in": 100, "out": 0, "cache_read": 0}

    def test_string_cost_coerced(self):
        """String cost value is coerced to float."""
        sample = {"total_cost_usd": "0.005"}
        cost, _ = _extract_cost(sample)
        assert cost == 0.005


class TestParseJsonResponse:
    """Tests for _parse_json_response() function."""

    def test_clean_json(self):
        """Parse clean JSON string."""
        json_str = '{"result": "hello", "total_cost_usd": 0.001}'
        data = _parse_json_response(json_str)
        assert data == {"result": "hello", "total_cost_usd": 0.001}

    def test_json_with_warning_prefix(self):
        """Strip warning text before JSON."""
        json_str = 'Warning: something happened\n{"result": "hello"}'
        data = _parse_json_response(json_str)
        assert data == {"result": "hello"}

    def test_json_with_multiline_prefix(self):
        """Strip multiple lines before JSON."""
        json_str = 'Line 1\nLine 2\nLine 3\n{"key": "value"}'
        data = _parse_json_response(json_str)
        assert data == {"key": "value"}

    def test_no_json(self):
        """Return None when no JSON found."""
        data = _parse_json_response("not json at all")
        assert data is None

    def test_malformed_json(self):
        """Return None for malformed JSON."""
        data = _parse_json_response("{invalid json}")
        assert data is None

    def test_empty_string(self):
        """Return None for empty string."""
        data = _parse_json_response("")
        assert data is None

    def test_json_array(self):
        """Array JSON returns None (only objects supported)."""
        data = _parse_json_response("[1, 2, 3]")
        # Parser looks for '{' so arrays return None - this is correct behavior
        assert data is None

    def test_nested_json(self):
        """Nested JSON objects parse correctly."""
        json_str = '{"outer": {"inner": "value"}, "cost": 0.01}'
        data = _parse_json_response(json_str)
        assert data["outer"]["inner"] == "value"
        assert data["cost"] == 0.01


class TestCostTrackingIntegration:
    """Integration tests for cost tracking flow."""

    def test_full_flow_valid_response(self):
        """Simulate full flow with valid Claude response."""
        # Simulated Claude CLI JSON output
        stdout = '{"result": "Code written successfully", "total_cost_usd": 0.0234, "usage": {"input_tokens": 1500, "output_tokens": 800, "cache_read_input_tokens": 5000}}'

        data = _parse_json_response(stdout)
        assert isinstance(data, dict)

        cost, tokens = _extract_cost(data)

        assert cost == 0.0234
        assert tokens["in"] == 1500
        assert tokens["out"] == 800
        assert tokens["cache_read"] == 5000
        assert data.get("result") == "Code written successfully"

    def test_full_flow_with_prefix(self):
        """Simulate flow with warning prefix in output."""
        stdout = 'Notice: Using cached context\n{"result": "Done", "total_cost_usd": 0.001, "usage": {"input_tokens": 50, "output_tokens": 20}}'

        data = _parse_json_response(stdout)
        assert isinstance(data, dict)
        assert data.get("result") == "Done"

    def test_graceful_degradation_invalid_json(self):
        """Invalid JSON returns None, doesn't crash."""
        stdout = "Error: Something went wrong"
        data = _parse_json_response(stdout)
        assert data is None

    def test_graceful_degradation_non_dict(self):
        """Non-dict JSON detected by isinstance check."""
        stdout = '["array", "response"]'
        data = _parse_json_response(stdout)
        assert not isinstance(data, dict)

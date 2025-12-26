"""
Tests for constitution loading from CLAUDE.md.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from zen_mode.files import load_constitution, get_full_constitution


class TestLoadConstitution:
    """Tests for load_constitution() function."""

    def test_loads_single_section(self):
        """Load a single section by name."""
        result = load_constitution("GOLDEN RULES")
        assert "## GOLDEN RULES" in result
        assert "Verify, then Delete" in result

    def test_loads_multiple_sections(self):
        """Load multiple sections, joined by double newlines."""
        result = load_constitution("GOLDEN RULES", "ARCHITECTURE")
        assert "## GOLDEN RULES" in result
        assert "## ARCHITECTURE" in result
        assert "Interface First" in result

    def test_section_order_matches_request_order(self):
        """Sections appear in requested order, not file order."""
        result = load_constitution("ARCHITECTURE", "GOLDEN RULES")
        arch_pos = result.find("## ARCHITECTURE")
        golden_pos = result.find("## GOLDEN RULES")
        assert arch_pos < golden_pos, "Sections should match request order"

    def test_case_insensitive_matching(self):
        """Section names match case-insensitively."""
        result = load_constitution("golden rules")
        assert "## GOLDEN RULES" in result

    def test_nonexistent_section_returns_empty(self):
        """Missing section is silently skipped."""
        result = load_constitution("NONEXISTENT SECTION")
        assert result == ""

    def test_partial_match_skips(self):
        """Only exact section headers match."""
        result = load_constitution("GOLDEN")  # Should not match "GOLDEN RULES"
        assert result == ""

    def test_no_sections_returns_empty(self):
        """No arguments returns empty string."""
        result = load_constitution()
        assert result == ""

    def test_section_content_complete(self):
        """Section includes all content until next header."""
        result = load_constitution("TESTING")
        assert "## TESTING" in result
        assert "Mock Externals" in result
        assert "Assert Behavior" in result
        assert "Self-Contained" in result
        # Should NOT include next section
        assert "## PROCESS" not in result

    def test_all_known_sections_loadable(self):
        """All expected sections can be loaded."""
        sections = ["GOLDEN RULES", "ARCHITECTURE", "CODE STYLE", "TESTING", "PROCESS"]
        for section in sections:
            result = load_constitution(section)
            assert f"## {section}" in result, f"Failed to load {section}"


class TestGetFullConstitution:
    """Tests for get_full_constitution() - merges zen defaults + project rules."""

    def test_returns_zen_defaults_when_no_project_file(self, tmp_path):
        """Without CLAUDE.md or AGENTS.md, returns zen defaults only."""
        result = get_full_constitution(tmp_path, "GOLDEN RULES")
        assert "## GOLDEN RULES" in result
        assert "## Project Rules" not in result

    def test_includes_project_claude_md(self, tmp_path):
        """Project CLAUDE.md is appended under '## Project Rules'."""
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# My Project Rules\n- Always test")

        result = get_full_constitution(tmp_path, "GOLDEN RULES")
        assert "## GOLDEN RULES" in result
        assert "## Project Rules" in result
        assert "Always test" in result

    def test_prefers_claude_md_over_agents_md(self, tmp_path):
        """CLAUDE.md takes precedence over AGENTS.md."""
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("From CLAUDE.md")
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("From AGENTS.md")

        result = get_full_constitution(tmp_path, "GOLDEN RULES")
        assert "From CLAUDE.md" in result
        assert "From AGENTS.md" not in result

    def test_falls_back_to_agents_md(self, tmp_path):
        """Uses AGENTS.md when CLAUDE.md doesn't exist."""
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("From AGENTS.md")

        result = get_full_constitution(tmp_path, "GOLDEN RULES")
        assert "## Project Rules" in result
        assert "From AGENTS.md" in result

    def test_multiple_sections_with_project_rules(self, tmp_path):
        """Multiple zen sections + project rules all present."""
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("Project specific rule")

        result = get_full_constitution(tmp_path, "GOLDEN RULES", "ARCHITECTURE")
        assert "## GOLDEN RULES" in result
        assert "## ARCHITECTURE" in result
        assert "## Project Rules" in result
        assert "Project specific rule" in result

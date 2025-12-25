"""
Tests for Scout phase helper functions.

Tests grep_impact functionality for Golden Rule enforcement.
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from zen_mode.scout import (
    parse_targeted_files,
    grep_impact,
    expand_dependencies,
    append_grep_impact_to_scout,
)


class TestParseTargetedFiles:
    """Tests for parse_targeted_files() function."""

    def test_basic_targeted_files(self):
        """Parse standard targeted files section."""
        content = """## Targeted Files (Must Change)
- `src/core.py`: main logic
- `src/utils.py`: helper functions

## Context Files (Read-Only)
- `src/config.py`: configuration
"""
        result = parse_targeted_files(content)
        assert result == ["src/core.py", "src/utils.py"]

    def test_no_targeted_files_section(self):
        """Return empty list when no targeted files section."""
        content = """## Context Files
- `src/config.py`: configuration
"""
        result = parse_targeted_files(content)
        assert result == []

    def test_empty_targeted_files_section(self):
        """Return empty list when section exists but is empty."""
        content = """## Targeted Files (Must Change)

## Context Files
- `src/config.py`: configuration
"""
        result = parse_targeted_files(content)
        assert result == []

    def test_targeted_files_with_various_extensions(self):
        """Parse files with different extensions."""
        content = """## Targeted Files
- `app.py`: python
- `index.js`: javascript
- `styles.css`: styles
- `config.yaml`: config
"""
        result = parse_targeted_files(content)
        assert result == ["app.py", "index.js", "styles.css", "config.yaml"]

    def test_ignores_non_backtick_lines(self):
        """Only parse lines with backtick format."""
        content = """## Targeted Files
- `valid.py`: this is valid
- invalid.py: this is not valid
Some random text
- `another.py`: also valid
"""
        result = parse_targeted_files(content)
        assert result == ["valid.py", "another.py"]

    def test_stops_at_next_section(self):
        """Stop parsing when next ## section is reached."""
        content = """## Targeted Files
- `first.py`: first
## Other Section
- `not_targeted.py`: should not include
"""
        result = parse_targeted_files(content)
        assert result == ["first.py"]


class TestGrepImpact:
    """Tests for grep_impact() function."""

    def test_finds_references_via_git_grep(self, tmp_path):
        """Find files referencing targets using git grep."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "caller1.py\ncaller2.py\n"

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = grep_impact(["src/utils.py"], tmp_path)

            mock_run.assert_called_once()
            assert "git" in mock_run.call_args[0][0]
            assert "utils" in mock_run.call_args[0][0]
            assert result == {"src/utils.py": ["caller1.py", "caller2.py"]}

    def test_excludes_target_file_from_results(self, tmp_path):
        """Target file itself should not be in results."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "src/utils.py\ncaller.py\n"

        with patch("subprocess.run", return_value=mock_result):
            result = grep_impact(["src/utils.py"], tmp_path)
            assert "src/utils.py" not in result["src/utils.py"]
            assert result == {"src/utils.py": ["caller.py"]}

    def test_no_matches_returns_empty_list(self, tmp_path):
        """Return empty list when no matches found."""
        mock_result = MagicMock()
        mock_result.returncode = 1  # No matches
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result):
            result = grep_impact(["src/orphan.py"], tmp_path)
            assert result == {"src/orphan.py": []}

    def test_multiple_targets(self, tmp_path):
        """Handle multiple targeted files."""
        def mock_run(cmd, **kwargs):
            mock = MagicMock()
            if "core" in cmd:
                mock.returncode = 0
                mock.stdout = "main.py\n"
            elif "utils" in cmd:
                mock.returncode = 0
                mock.stdout = "core.py\nmain.py\n"
            else:
                mock.returncode = 1
                mock.stdout = ""
            return mock

        with patch("subprocess.run", side_effect=mock_run):
            result = grep_impact(["src/core.py", "src/utils.py"], tmp_path)
            assert "src/core.py" in result
            assert "src/utils.py" in result


class TestExpandDependencies:
    """Tests for expand_dependencies() function."""

    def test_aggregates_all_dependencies(self, tmp_path):
        """Aggregate dependencies from all targeted files."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "caller1.py\ncaller2.py\n"

        with patch("subprocess.run", return_value=mock_result):
            result = expand_dependencies(["src/utils.py"], tmp_path)
            assert set(result) == {"caller1.py", "caller2.py"}

    def test_removes_targeted_files_from_results(self, tmp_path):
        """Don't include targeted files in dependency list."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "src/utils.py\ncaller.py\n"

        with patch("subprocess.run", return_value=mock_result):
            result = expand_dependencies(["src/utils.py"], tmp_path)
            assert "src/utils.py" not in result
            assert "caller.py" in result

    def test_deduplicates_across_targets(self, tmp_path):
        """Same dependency from multiple targets appears once."""
        call_count = [0]
        def mock_run(cmd, **kwargs):
            mock = MagicMock()
            mock.returncode = 0
            # Both targets are referenced by main.py
            mock.stdout = "main.py\n"
            call_count[0] += 1
            return mock

        with patch("subprocess.run", side_effect=mock_run):
            result = expand_dependencies(["a.py", "b.py"], tmp_path)
            assert result.count("main.py") == 1


class TestAppendGrepImpactToScout:
    """Tests for append_grep_impact_to_scout() function."""

    def test_appends_section_to_scout_file(self, tmp_path):
        """Append grep impact section when dependencies found."""
        scout_file = tmp_path / "scout.md"
        scout_file.write_text("## Targeted Files\n- `utils.py`: target\n")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "caller.py\n"

        with patch("subprocess.run", return_value=mock_result):
            append_grep_impact_to_scout(scout_file, ["utils.py"], tmp_path)

        content = scout_file.read_text()
        assert "## Grep Impact" in content
        assert "caller.py" in content

    def test_does_nothing_when_no_dependencies(self, tmp_path):
        """Don't modify file when no dependencies found."""
        scout_file = tmp_path / "scout.md"
        original = "## Targeted Files\n- `orphan.py`: target\n"
        scout_file.write_text(original)

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result):
            append_grep_impact_to_scout(scout_file, ["orphan.py"], tmp_path)

        assert scout_file.read_text() == original

    def test_does_nothing_when_no_targeted_files(self, tmp_path):
        """Early return when targeted_files is empty."""
        scout_file = tmp_path / "scout.md"
        original = "## Targeted Files\n"
        scout_file.write_text(original)

        append_grep_impact_to_scout(scout_file, [], tmp_path)

        assert scout_file.read_text() == original

    def test_logs_when_dependencies_found(self, tmp_path):
        """Call log function when dependencies found."""
        scout_file = tmp_path / "scout.md"
        scout_file.write_text("## Targeted Files\n- `utils.py`: target\n")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "a.py\nb.py\n"

        log_messages = []

        with patch("subprocess.run", return_value=mock_result):
            append_grep_impact_to_scout(
                scout_file, ["utils.py"], tmp_path,
                log_fn=lambda msg: log_messages.append(msg)
            )

        assert any("2 files" in msg for msg in log_messages)

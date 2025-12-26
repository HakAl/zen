"""
Tests for file size annotation in scout output.
"""
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from zen_mode.scout import (
    count_lines_safe,
    file_size_tag,
    annotate_file_sizes,
    FILE_SIZE_LARGE,
    FILE_SIZE_MASSIVE,
)


class TestCountLinesSafe:
    """Tests for count_lines_safe() function."""

    def test_counts_lines_in_normal_file(self, tmp_path):
        """Count lines in a regular file."""
        f = tmp_path / "test.py"
        f.write_text("line1\nline2\nline3\n")
        assert count_lines_safe(f) == 3

    def test_returns_none_for_missing_file(self, tmp_path):
        """Return None for non-existent file."""
        f = tmp_path / "missing.py"
        assert count_lines_safe(f) is None

    def test_returns_none_for_directory(self, tmp_path):
        """Return None for directory path."""
        assert count_lines_safe(tmp_path) is None

    def test_handles_empty_file(self, tmp_path):
        """Empty file has 0 lines."""
        f = tmp_path / "empty.py"
        f.write_text("")
        assert count_lines_safe(f) == 0

    def test_handles_binary_content_gracefully(self, tmp_path):
        """Binary content doesn't crash, uses errors='ignore'."""
        f = tmp_path / "binary.bin"
        f.write_bytes(b"\x00\x01\x02\xff\xfe\n\x00\n")
        result = count_lines_safe(f)
        assert result is not None  # Should return some count, not crash

    def test_returns_9999_for_huge_file(self, tmp_path):
        """Files over max_bytes return 9999."""
        f = tmp_path / "huge.py"
        f.write_text("x" * 100)  # Small file
        # Use a tiny max_bytes to trigger the limit
        assert count_lines_safe(f, max_bytes=50) == 9999


class TestFileSizeTag:
    """Tests for file_size_tag() function."""

    def test_none_returns_empty(self):
        """None line count returns empty string."""
        assert file_size_tag(None) == ""

    def test_small_file_no_tag(self):
        """Small files get no tag."""
        assert file_size_tag(100) == ""
        assert file_size_tag(FILE_SIZE_LARGE - 1) == ""

    def test_large_file_gets_tag(self):
        """Files at or above LARGE threshold get [LARGE]."""
        assert file_size_tag(FILE_SIZE_LARGE) == " [LARGE]"
        assert file_size_tag(FILE_SIZE_LARGE + 100) == " [LARGE]"

    def test_massive_file_gets_tag(self):
        """Files at or above MASSIVE threshold get [MASSIVE]."""
        assert file_size_tag(FILE_SIZE_MASSIVE) == " [MASSIVE]"
        assert file_size_tag(FILE_SIZE_MASSIVE + 1000) == " [MASSIVE]"
        assert file_size_tag(9999) == " [MASSIVE]"


class TestAnnotateFileSizes:
    """Tests for annotate_file_sizes() function."""

    def test_annotates_large_file_in_targeted_section(self, tmp_path):
        """Large file in Targeted Files gets annotated."""
        # Create a large file
        large_file = tmp_path / "src" / "big.py"
        large_file.parent.mkdir(parents=True)
        large_file.write_text("\n".join(["# line"] * 600))

        # Create scout.md
        scout_file = tmp_path / "scout.md"
        scout_file.write_text("""## Targeted Files (Must Change)
- `src/big.py`: needs update
- `src/small.py`: also needs update

## Context Files
- `src/other.py`: for reference
""")

        annotate_file_sizes(scout_file, tmp_path)

        content = scout_file.read_text()
        assert "- `src/big.py` [LARGE]: needs update" in content

    def test_skips_deletion_candidates(self, tmp_path):
        """Files in Deletion Candidates section are not annotated."""
        # Create a large file
        large_file = tmp_path / "old.py"
        large_file.write_text("\n".join(["# line"] * 600))

        scout_file = tmp_path / "scout.md"
        scout_file.write_text("""## Targeted Files (Must Change)
- `small.py`: keep this

## Deletion Candidates
- `old.py`: remove this large file
""")

        annotate_file_sizes(scout_file, tmp_path)

        content = scout_file.read_text()
        # Should NOT have [LARGE] in Deletion Candidates
        assert "[LARGE]" not in content.split("## Deletion Candidates")[1]

    def test_skips_already_annotated(self, tmp_path):
        """Files already annotated are not double-annotated."""
        large_file = tmp_path / "big.py"
        large_file.write_text("\n".join(["# line"] * 600))

        scout_file = tmp_path / "scout.md"
        scout_file.write_text("""## Targeted Files (Must Change)
- `big.py` [LARGE]: already tagged
""")

        annotate_file_sizes(scout_file, tmp_path)

        content = scout_file.read_text()
        # Should still have exactly one [LARGE], not [LARGE] [LARGE]
        assert content.count("[LARGE]") == 1

    def test_handles_missing_file_gracefully(self, tmp_path):
        """Missing files are skipped without error."""
        scout_file = tmp_path / "scout.md"
        scout_file.write_text("""## Targeted Files (Must Change)
- `missing.py`: this file doesn't exist
""")

        # Should not raise
        annotate_file_sizes(scout_file, tmp_path)

        content = scout_file.read_text()
        assert "[LARGE]" not in content
        assert "[MASSIVE]" not in content

    def test_annotates_context_files_section(self, tmp_path):
        """Context Files section also gets annotated."""
        large_file = tmp_path / "context.py"
        large_file.write_text("\n".join(["# line"] * 2500))

        scout_file = tmp_path / "scout.md"
        scout_file.write_text("""## Targeted Files (Must Change)
- `small.py`: modify this

## Context Files (Read-Only)
- `context.py`: reference only
""")

        annotate_file_sizes(scout_file, tmp_path)

        content = scout_file.read_text()
        assert "- `context.py` [MASSIVE]: reference only" in content

    def test_no_modification_when_no_large_files(self, tmp_path):
        """File is not rewritten if no annotations needed."""
        small_file = tmp_path / "small.py"
        small_file.write_text("# small file\n")

        scout_file = tmp_path / "scout.md"
        original = """## Targeted Files (Must Change)
- `small.py`: tiny file
"""
        scout_file.write_text(original)
        original_mtime = scout_file.stat().st_mtime

        annotate_file_sizes(scout_file, tmp_path)

        # Content should be unchanged
        assert scout_file.read_text() == original

    def test_logs_annotation_count(self, tmp_path):
        """Log function is called with annotation count."""
        large_file = tmp_path / "big.py"
        large_file.write_text("\n".join(["# line"] * 600))

        scout_file = tmp_path / "scout.md"
        scout_file.write_text("""## Targeted Files (Must Change)
- `big.py`: large file
""")

        logged = []
        annotate_file_sizes(scout_file, tmp_path, log_fn=logged.append)

        assert len(logged) == 1
        assert "1 large files" in logged[0]

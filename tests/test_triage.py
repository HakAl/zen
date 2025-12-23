"""Tests for triage module."""
import pytest
from zen_mode.triage import (
    TriageResult,
    parse_triage,
    should_fast_track,
    generate_synthetic_plan,
    TRIAGE_PROMPT_SECTION,
)


class TestParseTriageBasic:
    """Basic parsing tests."""

    def test_empty_input_returns_default(self):
        result = parse_triage("")
        assert result.fast_track is False
        assert result.confidence == 0.0
        assert result.micro_spec is None
        assert result.target_file is None

    def test_no_triage_block_returns_default(self):
        result = parse_triage("Some scout output without triage")
        assert result.fast_track is False

    def test_fast_track_no_with_spec_returns_false(self):
        scout_output = """
        <TRIAGE>
        COMPLEXITY: HIGH
        CONFIDENCE: 0.8
        FAST_TRACK: NO
        </TRIAGE>
        """
        result = parse_triage(scout_output)
        assert result.fast_track is False


class TestParseTriageFastTrack:
    """Fast track parsing tests."""

    def test_fast_track_yes_with_valid_spec(self):
        scout_output = """
        ## Targeted Files
        - src/core.py: main file

        <TRIAGE>
        COMPLEXITY: LOW
        CONFIDENCE: 0.95
        FAST_TRACK: YES
        </TRIAGE>

        <MICRO_SPEC>
        TARGET_FILE: src/core.py
        LINE_HINT: ~42
        OPERATION: UPDATE
        INSTRUCTION: Add comment "# TODO: refactor" at line 42
        </MICRO_SPEC>
        """
        result = parse_triage(scout_output)
        assert result.fast_track is True
        assert result.confidence == 0.95
        assert result.target_file == "src/core.py"
        assert "TODO: refactor" in result.micro_spec

    def test_fast_track_yes_without_space(self):
        """Handle FAST_TRACK:YES without space."""
        scout_output = """
        <TRIAGE>
        COMPLEXITY: LOW
        CONFIDENCE: 0.9
        FAST_TRACK:YES
        </TRIAGE>

        <MICRO_SPEC>
        TARGET_FILE: src/file.py
        OPERATION: UPDATE
        INSTRUCTION: Add a comment at the top of the file
        </MICRO_SPEC>
        """
        result = parse_triage(scout_output)
        assert result.fast_track is True

    def test_extracts_confidence(self):
        scout_output = """
        <TRIAGE>
        CONFIDENCE: 0.87
        FAST_TRACK: YES
        </TRIAGE>
        <MICRO_SPEC>
        TARGET_FILE: x.py
        OPERATION: UPDATE
        INSTRUCTION: some instruction here
        </MICRO_SPEC>
        """
        result = parse_triage(scout_output)
        assert result.confidence == 0.87


class TestParseTriageSafetyGuards:
    """Safety guard tests - these should reject fast track."""

    def test_rejects_empty_micro_spec(self):
        scout_output = """
        <TRIAGE>
        FAST_TRACK: YES
        CONFIDENCE: 0.95
        </TRIAGE>
        """
        result = parse_triage(scout_output)
        assert result.fast_track is False  # No micro_spec

    def test_rejects_missing_required_fields(self):
        """Micro-spec must have TARGET_FILE, OPERATION, and INSTRUCTION."""
        scout_output = """
        <TRIAGE>
        FAST_TRACK: YES
        CONFIDENCE: 0.95
        </TRIAGE>
        <MICRO_SPEC>
        Just some text without required fields
        </MICRO_SPEC>
        """
        result = parse_triage(scout_output)
        assert result.fast_track is False

    def test_rejects_missing_operation(self):
        scout_output = """
        <TRIAGE>
        FAST_TRACK: YES
        CONFIDENCE: 0.95
        </TRIAGE>
        <MICRO_SPEC>
        TARGET_FILE: x.py
        INSTRUCTION: Do something
        </MICRO_SPEC>
        """
        result = parse_triage(scout_output)
        assert result.fast_track is False  # Missing OPERATION

    def test_rejects_invalid_operation(self):
        scout_output = """
        <TRIAGE>
        FAST_TRACK: YES
        CONFIDENCE: 0.95
        </TRIAGE>
        <MICRO_SPEC>
        TARGET_FILE: x.py
        OPERATION: MODIFY
        INSTRUCTION: Do something
        </MICRO_SPEC>
        """
        result = parse_triage(scout_output)
        assert result.fast_track is False  # MODIFY not valid

    def test_accepts_valid_spec_with_all_fields(self):
        scout_output = """
        <TRIAGE>
        FAST_TRACK: YES
        CONFIDENCE: 0.95
        </TRIAGE>
        <MICRO_SPEC>
        TARGET_FILE: x.py
        OPERATION: UPDATE
        INSTRUCTION: Add comment
        </MICRO_SPEC>
        """
        result = parse_triage(scout_output)
        assert result.fast_track is True

    def test_accepts_insert_operation(self):
        scout_output = """
        <TRIAGE>
        FAST_TRACK: YES
        CONFIDENCE: 0.95
        </TRIAGE>
        <MICRO_SPEC>
        TARGET_FILE: x.py
        OPERATION: INSERT
        INSTRUCTION: Add new function
        </MICRO_SPEC>
        """
        result = parse_triage(scout_output)
        assert result.fast_track is True

    def test_accepts_delete_operation(self):
        scout_output = """
        <TRIAGE>
        FAST_TRACK: YES
        CONFIDENCE: 0.95
        </TRIAGE>
        <MICRO_SPEC>
        TARGET_FILE: x.py
        OPERATION: DELETE
        INSTRUCTION: Remove unused import
        </MICRO_SPEC>
        """
        result = parse_triage(scout_output)
        assert result.fast_track is True

    def test_rejects_whitespace_only_micro_spec(self):
        scout_output = """
        <TRIAGE>
        FAST_TRACK: YES
        CONFIDENCE: 0.95
        </TRIAGE>
        <MICRO_SPEC>

        </MICRO_SPEC>
        """
        result = parse_triage(scout_output)
        assert result.fast_track is False


class TestShouldFastTrack:
    """Tests for should_fast_track decision function."""

    def test_returns_true_when_above_threshold(self):
        triage = TriageResult(fast_track=True, confidence=0.95)
        assert should_fast_track(triage) is True

    def test_returns_false_when_below_threshold(self):
        triage = TriageResult(fast_track=True, confidence=0.85)
        assert should_fast_track(triage) is False

    def test_returns_false_when_fast_track_false(self):
        triage = TriageResult(fast_track=False, confidence=0.99)
        assert should_fast_track(triage) is False

    def test_custom_threshold(self):
        triage = TriageResult(fast_track=True, confidence=0.7)
        assert should_fast_track(triage, threshold=0.6) is True
        assert should_fast_track(triage, threshold=0.8) is False

    def test_exactly_at_threshold(self):
        triage = TriageResult(fast_track=True, confidence=0.9)
        assert should_fast_track(triage, threshold=0.9) is True


class TestGenerateSyntheticPlan:
    """Tests for synthetic plan generation."""

    def test_generates_valid_step_format(self):
        triage = TriageResult(
            micro_spec="Add comment # TODO at line 42",
            target_file="src/core.py"
        )
        plan = generate_synthetic_plan(triage)

        # Must match parse_steps() regex: ## Step N:
        assert "## Step 1:" in plan
        assert "src/core.py" in plan
        assert "TODO" in plan

    def test_truncates_long_description(self):
        long_spec = "A" * 100
        triage = TriageResult(micro_spec=long_spec, target_file="x.py")
        plan = generate_synthetic_plan(triage)

        # Step line should be truncated
        lines = plan.split("\n")
        step_line = [l for l in lines if l.startswith("## Step 1:")][0]
        # 60 chars + "## Step 1: " prefix
        assert len(step_line) < 80

    def test_handles_missing_target_file(self):
        triage = TriageResult(micro_spec="Do something important")
        plan = generate_synthetic_plan(triage)

        assert "see instructions" in plan

    def test_handles_none_micro_spec(self):
        triage = TriageResult()
        plan = generate_synthetic_plan(triage)

        assert "## Step 1:" in plan
        assert "Apply changes" in plan


class TestTriagePromptSection:
    """Tests for the prompt section constant."""

    def test_contains_triage_block_template(self):
        assert "<TRIAGE>" in TRIAGE_PROMPT_SECTION
        assert "</TRIAGE>" in TRIAGE_PROMPT_SECTION

    def test_contains_micro_spec_template(self):
        assert "<MICRO_SPEC>" in TRIAGE_PROMPT_SECTION
        assert "</MICRO_SPEC>" in TRIAGE_PROMPT_SECTION

    def test_contains_fast_track_criteria(self):
        assert "1-2 files" in TRIAGE_PROMPT_SECTION
        assert "FAST_TRACK" in TRIAGE_PROMPT_SECTION

    def test_contains_uncertainty_guidance(self):
        assert "If unsure" in TRIAGE_PROMPT_SECTION
        assert "FAST_TRACK=NO" in TRIAGE_PROMPT_SECTION


class TestEdgeCases:
    """Edge case tests."""

    def test_malformed_confidence_value(self):
        scout_output = """
        <TRIAGE>
        CONFIDENCE: not_a_number
        FAST_TRACK: YES
        </TRIAGE>
        <MICRO_SPEC>
        TARGET_FILE: x.py
        OPERATION: UPDATE
        INSTRUCTION: some valid instruction
        </MICRO_SPEC>
        """
        result = parse_triage(scout_output)
        assert result.confidence == 0.0  # Should fallback to 0.0

    def test_multiline_micro_spec(self):
        scout_output = """
        <TRIAGE>
        FAST_TRACK: YES
        CONFIDENCE: 0.92
        </TRIAGE>
        <MICRO_SPEC>
        TARGET_FILE: src/utils.py
        LINE_HINT: ~15-20
        OPERATION: UPDATE
        INSTRUCTION: Replace the function body with:
        ```python
        def helper():
            return True
        ```
        </MICRO_SPEC>
        """
        result = parse_triage(scout_output)
        assert result.fast_track is True
        assert "def helper" in result.micro_spec
        assert result.target_file == "src/utils.py"

    def test_nested_xml_like_content(self):
        scout_output = """
        <TRIAGE>
        FAST_TRACK: YES
        CONFIDENCE: 0.9
        </TRIAGE>
        <MICRO_SPEC>
        TARGET_FILE: template.html
        OPERATION: UPDATE
        INSTRUCTION: Add <div class="container"> wrapper
        </MICRO_SPEC>
        """
        result = parse_triage(scout_output)
        assert result.fast_track is True
        assert "<div" in result.micro_spec

    def test_windows_path_in_target_file(self):
        scout_output = """
        <TRIAGE>
        FAST_TRACK: YES
        CONFIDENCE: 0.95
        </TRIAGE>
        <MICRO_SPEC>
        TARGET_FILE: src\\utils\\helper.py
        OPERATION: UPDATE
        INSTRUCTION: Add import statement at top
        </MICRO_SPEC>
        """
        result = parse_triage(scout_output)
        assert result.target_file == "src\\utils\\helper.py"


class TestCaseInsensitivity:
    """LLMs sometimes shout (YES) and sometimes whisper (Yes)."""

    def test_lowercase_yes(self):
        scout_output = """
        <TRIAGE>
        FAST_TRACK: yes
        CONFIDENCE: 0.95
        </TRIAGE>
        <MICRO_SPEC>
        TARGET_FILE: x.py
        OPERATION: UPDATE
        INSTRUCTION: some instruction here
        </MICRO_SPEC>
        """
        result = parse_triage(scout_output)
        assert result.fast_track is True

    def test_mixed_case_yes(self):
        scout_output = """
        <TRIAGE>
        FAST_TRACK: Yes
        CONFIDENCE: 0.95
        </TRIAGE>
        <MICRO_SPEC>
        TARGET_FILE: x.py
        OPERATION: UPDATE
        INSTRUCTION: some instruction here
        </MICRO_SPEC>
        """
        result = parse_triage(scout_output)
        assert result.fast_track is True

    def test_lowercase_triage_tags(self):
        scout_output = """
        <triage>
        FAST_TRACK: YES
        CONFIDENCE: 0.95
        </triage>
        <micro_spec>
        TARGET_FILE: x.py
        OPERATION: UPDATE
        INSTRUCTION: some instruction here
        </micro_spec>
        """
        result = parse_triage(scout_output)
        assert result.fast_track is True
        assert result.target_file == "x.py"

    def test_lowercase_target_file_key(self):
        scout_output = """
        <TRIAGE>
        FAST_TRACK: YES
        confidence: 0.9
        </TRIAGE>
        <MICRO_SPEC>
        target_file: src/main.py
        operation: update
        instruction: do something
        </MICRO_SPEC>
        """
        result = parse_triage(scout_output)
        assert result.target_file == "src/main.py"
        assert result.confidence == 0.9


class TestTargetFileWhitespace:
    """TARGET_FILE might have trailing content we don't want."""

    def test_strips_trailing_comment(self):
        scout_output = """
        <TRIAGE>
        FAST_TRACK: YES
        CONFIDENCE: 0.95
        </TRIAGE>
        <MICRO_SPEC>
        TARGET_FILE: src/main.py (I think)
        OPERATION: UPDATE
        INSTRUCTION: Add import at top
        </MICRO_SPEC>
        """
        result = parse_triage(scout_output)
        assert result.target_file == "src/main.py"

    def test_strips_hash_comment(self):
        scout_output = """
        <TRIAGE>
        FAST_TRACK: YES
        CONFIDENCE: 0.95
        </TRIAGE>
        <MICRO_SPEC>
        TARGET_FILE: src/main.py # main entry point
        OPERATION: UPDATE
        INSTRUCTION: Add import at top
        </MICRO_SPEC>
        """
        result = parse_triage(scout_output)
        assert result.target_file == "src/main.py"

    def test_handles_quoted_path(self):
        scout_output = """
        <TRIAGE>
        FAST_TRACK: YES
        CONFIDENCE: 0.95
        </TRIAGE>
        <MICRO_SPEC>
        TARGET_FILE: "src/main.py"
        OPERATION: UPDATE
        INSTRUCTION: Add import at top
        </MICRO_SPEC>
        """
        result = parse_triage(scout_output)
        # Gets the quoted string as-is (quotes included)
        assert "src/main.py" in result.target_file


class TestMarkdownFormat:
    """Tests for markdown-formatted triage output (vs XML format)."""

    def test_markdown_triage_section(self):
        """Scout outputs ## Triage instead of <TRIAGE> tags."""
        scout_output = """
# Scout Report: task_api.md

## Targeted Files (Must Change)
- `api/Main.java`: Add comment at top

## Triage

**COMPLEXITY:** LOW

**CONFIDENCE:** 0.95

**FAST_TRACK:** YES

---

## Micro Spec

**TARGET_FILE:** `api/Main.java`

**LINE_HINT:** 1

**OPERATION:** INSERT

**INSTRUCTION:** Add comment at top of file
"""
        result = parse_triage(scout_output)
        assert result.fast_track is True
        assert result.confidence == 0.95
        assert result.target_file == "api/Main.java"

    def test_markdown_bold_fields(self):
        """Handle **FIELD:** format with bold markers."""
        scout_output = """
## Triage
**FAST_TRACK:** YES
**CONFIDENCE:** 0.92

## Micro Spec
**TARGET_FILE:** src/main.py
**OPERATION:** UPDATE
**INSTRUCTION:** Add import statement
"""
        result = parse_triage(scout_output)
        assert result.fast_track is True
        assert result.confidence == 0.92

    def test_markdown_backtick_path(self):
        """Handle `path/to/file` format with backticks."""
        scout_output = """
## Triage
**FAST_TRACK:** YES
**CONFIDENCE:** 0.90

## Micro Spec
**TARGET_FILE:** `src/utils/helper.py`
**OPERATION:** UPDATE
**INSTRUCTION:** Add docstring
"""
        result = parse_triage(scout_output)
        assert result.target_file == "src/utils/helper.py"

    def test_mixed_xml_and_markdown(self):
        """Handle case where triage is XML but content uses markdown formatting."""
        scout_output = """
<TRIAGE>
**COMPLEXITY:** LOW
**CONFIDENCE:** 0.95
**FAST_TRACK:** YES
</TRIAGE>

<MICRO_SPEC>
**TARGET_FILE:** `src/core.py`
**OPERATION:** UPDATE
**INSTRUCTION:** Fix the bug
</MICRO_SPEC>
"""
        result = parse_triage(scout_output)
        assert result.fast_track is True
        assert result.target_file == "src/core.py"

    def test_markdown_with_horizontal_rules(self):
        """Handle --- separators in markdown output."""
        scout_output = """
## Triage

**COMPLEXITY:** LOW
**CONFIDENCE:** 0.91
**FAST_TRACK:** YES

---

## Micro Spec

**TARGET_FILE:** `test.py`
**OPERATION:** DELETE
**INSTRUCTION:** Remove unused import

---
"""
        result = parse_triage(scout_output)
        assert result.fast_track is True
        assert result.confidence == 0.91

    def test_simple_format_no_bold(self):
        """Handle simple key: value format without bold markers."""
        scout_output = """
## Targeted Files (Must Change)
- `api/Main.java`: Add comment

## Triage
COMPLEXITY: LOW
CONFIDENCE: 0.95
FAST_TRACK: YES

TARGET_FILE: api/Main.java
OPERATION: INSERT
INSTRUCTION: Add comment at top of file
"""
        result = parse_triage(scout_output)
        assert result.fast_track is True
        assert result.confidence == 0.95
        assert result.target_file == "api/Main.java"


class TestHeaderSanitization:
    """Micro-spec might start with newlines or special chars."""

    def test_handles_leading_newline(self):
        triage = TriageResult(
            micro_spec="\n\nAdd comment at line 42",
            target_file="x.py"
        )
        plan = generate_synthetic_plan(triage)
        # Should not have newline in step header
        lines = plan.split('\n')
        step_line = [l for l in lines if l.startswith("## Step 1:")][0]
        assert "\n" not in step_line
        assert "Add comment" in step_line

    def test_handles_markdown_chars(self):
        triage = TriageResult(
            micro_spec="Add `code` and [link] and # header",
            target_file="x.py"
        )
        plan = generate_synthetic_plan(triage)
        lines = plan.split('\n')
        step_line = [l for l in lines if l.startswith("## Step 1:")][0]
        # Should remove #, [], `
        assert "#" not in step_line.replace("## Step 1:", "")
        assert "[" not in step_line
        assert "`" not in step_line

    def test_collapses_multiple_spaces(self):
        triage = TriageResult(
            micro_spec="Add    multiple   spaces   here",
            target_file="x.py"
        )
        plan = generate_synthetic_plan(triage)
        assert "   " not in plan.split('\n')[2]  # Step line

    def test_smart_truncation_at_word_boundary(self):
        triage = TriageResult(
            micro_spec="A " * 50,  # 100 chars of "A A A..."
            target_file="x.py"
        )
        plan = generate_synthetic_plan(triage)
        lines = plan.split('\n')
        step_line = [l for l in lines if l.startswith("## Step 1:")][0]
        # Should truncate at word boundary and add ...
        assert step_line.endswith("...")
        assert len(step_line) < 80

    def test_truncation_no_spaces(self):
        """Long string with no spaces should still truncate cleanly."""
        triage = TriageResult(
            micro_spec="X" * 100,  # 100 chars with no spaces
            target_file="x.py"
        )
        plan = generate_synthetic_plan(triage)
        lines = plan.split('\n')
        step_line = [l for l in lines if l.startswith("## Step 1:")][0]
        # Should truncate and add ... even without word boundary
        assert step_line.endswith("...")
        assert len(step_line) <= 72  # "## Step 1: " (11) + 57 + "..." (3)

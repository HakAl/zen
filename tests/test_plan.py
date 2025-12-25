"""
Tests for Plan phase helper functions.

Tests interface-first validation and plan parsing.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from zen_mode.plan import validate_plan_has_interfaces, parse_steps


class TestValidatePlanHasInterfaces:
    """Tests for validate_plan_has_interfaces() function."""

    def test_valid_plan_with_interfaces_before_steps(self):
        """Accept plan with Interfaces section before Steps."""
        plan = """## Interfaces
- `User.validate() -> bool`: Validate user data

## Steps

## Step 1: Add validation method
Files: `user.py`
"""
        valid, msg = validate_plan_has_interfaces(plan)
        assert valid is True
        assert msg == ""

    def test_rejects_plan_without_interfaces(self):
        """Reject plan missing Interfaces section entirely."""
        plan = """## Steps

## Step 1: Add validation method
## Step 2: Update callers
"""
        valid, msg = validate_plan_has_interfaces(plan)
        assert valid is False
        assert "Interfaces" in msg

    def test_rejects_interfaces_after_steps(self):
        """Reject plan where Interfaces comes after Steps."""
        plan = """## Steps

## Step 1: Add method

## Interfaces
- `User.validate() -> bool`: purpose
"""
        valid, msg = validate_plan_has_interfaces(plan)
        assert valid is False
        assert "BEFORE" in msg

    def test_normalizes_single_hash_headers(self):
        """Normalize # to ## for consistent parsing."""
        plan = """# Interfaces
- `func() -> None`: purpose

# Steps
# Step 1: Do something
"""
        valid, msg = validate_plan_has_interfaces(plan)
        assert valid is True

    def test_empty_plan_passes(self):
        """Empty plan handled elsewhere, passes here."""
        valid, msg = validate_plan_has_interfaces("")
        assert valid is True

    def test_whitespace_only_passes(self):
        """Whitespace-only plan passes validation."""
        valid, msg = validate_plan_has_interfaces("   \n\n  ")
        assert valid is True

    def test_no_sections_passes(self):
        """Plan without any sections passes (handled elsewhere)."""
        plan = """This is just some text
without any markdown headers
"""
        valid, msg = validate_plan_has_interfaces(plan)
        assert valid is True

    def test_interface_variations(self):
        """Accept various interface section header formats."""
        variations = [
            "## Interfaces",
            "## Interfaces (REQUIRED)",
            "## Interface Definitions",
            "# Interfaces",
        ]
        for header in variations:
            plan = f"""{header}
- `func() -> None`: purpose

## Steps
## Step 1: Do it
"""
            valid, msg = validate_plan_has_interfaces(plan)
            assert valid is True, f"Failed for header: {header}"

    def test_steps_section_variations(self):
        """Recognize various step section formats."""
        plan = """## Interfaces
- `func() -> None`: purpose

## Implementation Steps
## Step 1: Do it
"""
        # "Implementation Steps" doesn't contain just "step", this is the actual sections
        # Let me check the logic - it looks for "step" in section name
        valid, msg = validate_plan_has_interfaces(plan)
        # "implementation steps" contains "step"
        assert valid is True


class TestParseSteps:
    """Tests for parse_steps() function."""

    def test_strict_format(self):
        """Parse strict ## Step N: format."""
        plan = """## Step 1: Add function
## Step 2: Update tests
## Step 3: Verify
"""
        steps = parse_steps(plan)
        assert len(steps) == 3
        assert steps[0] == (1, "Add function")
        assert steps[1] == (2, "Update tests")
        assert steps[2] == (3, "Verify")

    def test_deduplicates_step_numbers(self):
        """Don't repeat step numbers."""
        plan = """## Step 1: First
## Step 1: Duplicate (should be ignored)
## Step 2: Second
"""
        steps = parse_steps(plan)
        assert len(steps) == 2
        assert steps[0] == (1, "First")
        assert steps[1] == (2, "Second")

    def test_flexible_format(self):
        """Parse Step N: without ##."""
        plan = """Step 1: Do this
Step 2: Do that
"""
        steps = parse_steps(plan)
        assert len(steps) == 2

    def test_numbered_list_format(self):
        """Parse 1. format."""
        plan = """1. First step
2. Second step
"""
        steps = parse_steps(plan)
        assert len(steps) == 2

    def test_bullet_fallback(self):
        """Fall back to bullets if no numbered steps."""
        plan = """- Do this first
- Then do this
- Finally this
"""
        steps = parse_steps(plan)
        assert len(steps) == 3

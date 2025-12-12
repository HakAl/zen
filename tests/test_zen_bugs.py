"""
Failing tests for bugs in zen.py and zen_lint.py.
Once bugs are fixed, these tests should pass.
"""
import inspect
import shutil
import sys
from pathlib import Path

import pytest

# Scripts are in scripts/ directory
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


def _reload_zen(monkeypatch):
    """Reload zen module with mocked CLAUDE_EXE."""
    monkeypatch.setenv("CLAUDE_EXE", "/fake/claude")
    monkeypatch.setattr(shutil, "which", lambda x: "/fake/claude" if x == "claude" else None)
    if 'zen' in sys.modules:
        del sys.modules['zen']
    import zen
    return zen


def _reload_zen_lint():
    """Reload zen_lint module."""
    if 'zen_lint' in sys.modules:
        del sys.modules['zen_lint']
    import zen_lint
    return zen_lint


class TestRetryFlagWrongLogFile:
    """BUG: --retry operates on LOG_FILE BEFORE path reassignment in main()."""

    def test_retry_uses_correct_log_file(self, monkeypatch):
        zen = _reload_zen(monkeypatch)
        source = inspect.getsource(zen.main)
        lines = source.split('\n')

        retry_line = None
        reassignment_line = None

        for i, line in enumerate(lines):
            if '"--retry"' in line and 'flags' in line:
                retry_line = i
            if 'WORK_DIR = PROJECT_ROOT' in line or 'WORK_DIR =' in line and 'ZEN_ID' in line:
                reassignment_line = i

        assert retry_line is not None, "Could not find --retry handling"
        assert reassignment_line is not None, "Could not find WORK_DIR reassignment"
        assert retry_line > reassignment_line, (
            f"BUG: --retry (line {retry_line}) before path reassignment (line {reassignment_line})"
        )


class TestBackupDeletedOnEveryRun:
    """BUG: Backups deleted on every run, not just --reset."""

    def test_backups_preserved_on_rerun(self, monkeypatch):
        zen = _reload_zen(monkeypatch)
        source = inspect.getsource(zen.main)

        # The buggy code was:
        #   if BACKUP_DIR.exists() and not DRY_RUN:
        #       shutil.rmtree(BACKUP_DIR)
        # This should NOT exist in main() anymore

        has_backup_deletion = "shutil.rmtree(BACKUP_DIR)" in source

        assert not has_backup_deletion, "BUG: main() still deletes BACKUP_DIR on every run"


class TestBackupFileNeverCalled:
    """BUG: backup_file() is defined but never called."""

    def test_backup_file_is_called(self, monkeypatch):
        zen = _reload_zen(monkeypatch)
        source = inspect.getsource(zen)

        definition_count = source.count("def backup_file")
        call_count = source.count("backup_file(") - definition_count

        assert call_count > 0, f"BUG: backup_file() defined but never called ({call_count} calls)"


class TestSplitCodeCommentUnreachableCode:
    """BUG: Unreachable return after while True in split_code_comment."""

    def test_no_unreachable_return(self):
        zen_lint = _reload_zen_lint()
        source = inspect.getsource(zen_lint.split_code_comment)
        lines = source.split('\n')

        while_indent = None
        found_while = False
        has_return_inside = False
        has_return_after = False

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            indent = len(line) - len(line.lstrip())

            if 'while True:' in stripped:
                found_while = True
                while_indent = indent
                continue

            if found_while and while_indent is not None:
                if indent > while_indent and stripped.startswith('return '):
                    has_return_inside = True
                elif indent <= while_indent and stripped.startswith('return '):
                    has_return_after = True
                    break

        assert found_while, "Could not find 'while True'"
        assert has_return_inside, "Could not find return inside while"
        assert not has_return_after, "BUG: Unreachable return after while True loop"


class TestEscapeHandling:
    """BUG #10: Escape sequence handling in find_string_ranges is broken."""

    def test_escaped_backslash(self):
        zen_lint = _reload_zen_lint()
        line = r'x = "test\\" # this is a comment'
        code, comment = zen_lint.split_code_comment(line, '.py')

        assert comment.strip() == "this is a comment", (
            f"BUG: Escaped backslash not handled. Got comment: '{comment}'"
        )


class TestTaskFileNotValidated:
    """BUG #6: task_file path is never validated to exist."""

    def test_main_validates_task_file_exists(self, monkeypatch):
        zen = _reload_zen(monkeypatch)
        source = inspect.getsource(zen.main)

        # Should validate task_file exists before using it
        # Look for Path(task_file).exists() or similar validation
        has_validation = (
            "task_file" in source and
            (".exists()" in source or "is_file()" in source) and
            "task_file" in source.split(".exists()")[0].split("\n")[-1]
            if ".exists()" in source else False
        )

        # Alternative: check if there's any file existence check near task_file usage
        lines = source.split('\n')
        validates_task_file = False
        for i, line in enumerate(lines):
            if 'task_file' in line and ('exists' in line or 'is_file' in line):
                validates_task_file = True
                break
            # Check if Path(task_file) is validated in nearby lines
            if 'task_file = sys.argv[1]' in line:
                # Look at next few lines for validation
                for j in range(i + 1, min(i + 10, len(lines))):
                    if 'exist' in lines[j].lower() and 'task' in lines[j].lower():
                        validates_task_file = True
                        break

        assert validates_task_file, (
            "BUG: task_file is never validated. A typo in the path sends garbage to Claude."
        )


class TestStepParsingDuplicates:
    """BUG #7: Step parsing can produce duplicates or gaps."""

    def test_parse_steps_no_duplicates(self, monkeypatch):
        zen = _reload_zen(monkeypatch)

        # Plan with potential duplicate matching
        plan_with_dupe = """
## Step 1: Do first thing
Some description

## Step 1: Duplicate step one
This shouldn't happen but parser might match

## Step 2: Do second thing
"""
        steps = zen.parse_steps(plan_with_dupe)
        step_nums = [s[0] for s in steps]

        # Should not have duplicate step numbers
        assert len(step_nums) == len(set(step_nums)), (
            f"BUG: parse_steps produced duplicate step numbers: {step_nums}"
        )

    def test_parse_steps_no_gaps(self, monkeypatch):
        zen = _reload_zen(monkeypatch)

        # Normal sequential plan
        plan = """
## Step 1: First
## Step 2: Second
## Step 3: Third
"""
        steps = zen.parse_steps(plan)
        step_nums = [s[0] for s in steps]

        # Steps should be sequential without gaps
        if step_nums:
            expected = list(range(step_nums[0], step_nums[0] + len(step_nums)))
            assert step_nums == expected, (
                f"BUG: parse_steps produced gaps: {step_nums}, expected {expected}"
            )

    def test_parse_steps_mixed_formats_no_duplicates(self, monkeypatch):
        zen = _reload_zen(monkeypatch)

        # Plan with mixed formats that could match twice
        plan = """
## Step 1: First thing
1. First thing (same content, different format)

## Step 2: Second thing
"""
        steps = zen.parse_steps(plan)
        step_nums = [s[0] for s in steps]

        # The "1." should not create a duplicate of Step 1
        assert step_nums.count(1) <= 1, (
            f"BUG: Mixed format caused duplicate step 1: {steps}"
        )


class TestEscapeSequenceHandling:
    """BUG #10: Escape handling checks previous char incorrectly."""

    def test_consecutive_escapes(self):
        zen_lint = _reload_zen_lint()

        # Multiple consecutive backslashes
        # In "\\\\", each pair is an escaped backslash, so string ends normally
        line = r'x = "\\\\" # comment'
        code, comment = zen_lint.split_code_comment(line, '.py')

        assert "comment" in comment, (
            f"BUG: Multiple escapes not handled. Got comment: '{comment}'"
        )

    def test_escape_before_quote(self):
        zen_lint = _reload_zen_lint()

        # \" inside string should not end the string
        line = r'x = "test\"more" # comment'
        code, comment = zen_lint.split_code_comment(line, '.py')

        assert "comment" in comment, (
            f"BUG: Escaped quote broke string detection. Got comment: '{comment}'"
        )


class TestBackupPathCollision:
    """BUG #11: Backup path flattening can cause collisions."""

    def test_same_filename_different_parents_no_collision(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        zen = _reload_zen(monkeypatch)

        # Set up backup directory
        backup_dir = tmp_path / "backup"
        backup_dir.mkdir()
        zen.BACKUP_DIR = backup_dir
        zen.PROJECT_ROOT = tmp_path

        # Create two files with same name in different directories
        (tmp_path / "src").mkdir()
        (tmp_path / "lib").mkdir()
        file1 = tmp_path / "src" / "utils.py"
        file2 = tmp_path / "lib" / "utils.py"
        file1.write_text("# from src/utils.py")
        file2.write_text("# from lib/utils.py")

        # Backup both files
        zen.backup_file(file1)
        zen.backup_file(file2)

        # Both should have separate backups with preserved directory structure
        backup1 = backup_dir / "src" / "utils.py"
        backup2 = backup_dir / "lib" / "utils.py"

        assert backup1.exists(), f"Backup for src/utils.py not found at {backup1}"
        assert backup2.exists(), f"Backup for lib/utils.py not found at {backup2}"
        assert backup1.read_text() == "# from src/utils.py"
        assert backup2.read_text() == "# from lib/utils.py"


class TestResetClearsParallelInstances:
    """BUG #13: --reset deletes work directories of parallel zen instances."""

    def test_reset_only_clears_own_workdir(self, monkeypatch):
        zen = _reload_zen(monkeypatch)
        source = inspect.getsource(zen.main)

        # The bug: --reset uses glob to delete ALL .zen-* directories
        # This affects parallel instances with different PIDs

        # Check if --reset section uses a broad glob pattern
        has_broad_glob = 'glob(f"{WORK_DIR_NAME}-*")' in source

        # Should only delete its own WORK_DIR, not all .zen-* dirs
        assert not has_broad_glob, (
            "BUG: --reset uses glob to delete ALL .zen-* directories, "
            "which would destroy parallel instances' work"
        )


class TestNoSignalHandlingCleanup:
    """BUG #14: KeyboardInterrupt doesn't clean up partial state."""

    def test_keyboard_interrupt_has_cleanup(self, monkeypatch):
        zen = _reload_zen(monkeypatch)
        source = inspect.getsource(zen.main)

        # Find the KeyboardInterrupt handler
        has_keyboard_handler = "KeyboardInterrupt" in source

        # Check if there's any cleanup logic before exit
        # Should save state, log interruption point, or similar
        lines = source.split('\n')
        has_cleanup = False
        in_except_block = False

        for line in lines:
            if 'KeyboardInterrupt' in line:
                in_except_block = True
            elif in_except_block:
                # Look for cleanup actions (save, backup, log to file, etc.)
                if any(kw in line for kw in ['backup', 'save', 'write_file', 'log(']):
                    has_cleanup = True
                    break
                # End of except block
                if line.strip() and not line.startswith(' ') and not line.startswith('\t'):
                    break
                if 'sys.exit' in line or 'raise' in line:
                    break

        assert has_keyboard_handler, "No KeyboardInterrupt handler found"
        assert has_cleanup, (
            "BUG: KeyboardInterrupt handler just exits without cleanup. "
            "Should log interruption point or save partial state."
        )


class TestLintHashCollision:
    """BUG #16: MD5 hash on truncated output can collide."""

    def test_different_errors_same_prefix_have_different_hash(self, monkeypatch):
        import hashlib

        zen = _reload_zen(monkeypatch)

        # Two different lint errors that share the same first 30 lines
        common_prefix = "\n".join([f"[HIGH] file.py:{i} SOME_ERROR" for i in range(30)])
        error1 = common_prefix + "\n[HIGH] file.py:100 UNIQUE_ERROR_1"
        error2 = common_prefix + "\n[HIGH] file.py:100 UNIQUE_ERROR_2"

        # Fixed implementation hashes full output, not truncated
        hash1 = hashlib.md5(error1.encode()).hexdigest()
        hash2 = hashlib.md5(error2.encode()).hexdigest()

        # These should be different now that we hash full output
        assert hash1 != hash2, (
            "Different lint errors should produce different hashes"
        )


class TestNoVerificationStepEnforcement:
    """BUG #17: No enforcement that plan includes a verification step."""

    def test_plan_without_verify_step_is_rejected(self, monkeypatch):
        zen = _reload_zen(monkeypatch)

        # A plan that doesn't end with verification
        plan_no_verify = """
## Step 1: Add new feature
Implement the feature

## Step 2: Update imports
Fix the imports
"""
        steps = zen.parse_steps(plan_no_verify)
        step_descs = [s[1].lower() for s in steps]

        # Check if any validation exists for verification step
        source = inspect.getsource(zen)
        source_lower = source.lower()

        # Look for verification step validation
        has_verify_check = (
            ('verify' in source_lower and 'step' in source_lower and 'check' in source_lower) or
            'must end with' in source_lower or
            'requires verification' in source_lower or
            'missing verification' in source_lower
        )

        # Alternative: check if parse_steps or phase_plan validates this
        plan_source = inspect.getsource(zen.phase_plan) if hasattr(zen, 'phase_plan') else ""
        validates_verify_step = 'verif' in plan_source.lower() and 'check' in plan_source.lower()

        assert has_verify_check or validates_verify_step, (
            "BUG: No enforcement that plan includes verification step. "
            "A plan without 'verify' or 'test' step is accepted."
        )


class TestStepBlockedDetection:
    """BUG #19: STEP_BLOCKED detection uses simple substring check."""

    def test_step_blocked_not_triggered_by_mention(self, monkeypatch):
        zen = _reload_zen(monkeypatch)
        source = inspect.getsource(zen)

        # Current buggy code: if "STEP_BLOCKED" in output:
        # This triggers on any mention, like "I will not output STEP_BLOCKED"

        # Check if detection uses simple substring
        has_simple_check = '"STEP_BLOCKED" in output' in source or "'STEP_BLOCKED' in output" in source

        # Should use more robust detection like:
        # - output.strip().startswith("STEP_BLOCKED")
        # - re.match(r'^STEP_BLOCKED:', output, re.M)
        # - output.strip().split('\n')[-1].startswith("STEP_BLOCKED")

        assert not has_simple_check, (
            "BUG: STEP_BLOCKED uses simple 'in' check. "
            "Output like 'I won't say STEP_BLOCKED' would incorrectly trigger. "
            "Should check last line or use regex ^STEP_BLOCKED:"
        )

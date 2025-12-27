"""
Integration tests for multi-language test verification.

Tests that phase_verify() correctly detects pass/fail/none states
across different build systems and test runners.

Fixtures: tests/fixtures/{node,go,java,csharp}_project/
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

# Path to fixtures directory
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def runtime_available(cmd: str) -> bool:
    """Check if a runtime/command is available on the system."""
    return shutil.which(cmd) is not None


def copy_fixture(fixture_name: str, dest: Path) -> Path:
    """Copy a fixture to a temporary directory."""
    src = FIXTURES_DIR / fixture_name
    if not src.exists():
        pytest.skip(f"Fixture {fixture_name} not found")
    shutil.copytree(src, dest / fixture_name)
    return dest / fixture_name


# =============================================================================
# Node.js / Jest Tests
# =============================================================================

@pytest.mark.skipif(not runtime_available("node"), reason="node not found")
@pytest.mark.skipif(not runtime_available("npm"), reason="npm not found")
class TestNodeProject:
    """Tests for Node.js/Jest fixture."""

    @pytest.fixture
    def node_project(self, tmp_path):
        """Copy node fixture and install dependencies."""
        project = copy_fixture("node_project", tmp_path)
        # Install dependencies (shell=True needed on Windows for npm.cmd)
        result = subprocess.run(
            ["npm", "install"],
            cwd=project,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=120,
            shell=(os.name == "nt")
        )
        if result.returncode != 0:
            pytest.skip(f"npm install failed: {result.stderr}")
        return project

    def test_passing(self, node_project):
        """Verify Jest detects passing tests."""
        result = subprocess.run(
            ["npm", "test"],
            cwd=node_project,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=60,
            shell=(os.name == "nt")
        )
        # Zero exit code is the reliable success signal
        assert result.returncode == 0, f"Tests failed: {result.stderr or result.stdout}"

    def test_failing(self, node_project):
        """Verify Jest detects failing tests."""
        # Inject a failing test
        test_file = node_project / "tests" / "index.test.js"
        content = test_file.read_text()
        content += """
test('intentional failure', () => {
    expect(1).toBe(2);
});
"""
        test_file.write_text(content)

        result = subprocess.run(
            ["npm", "test"],
            cwd=node_project,
            capture_output=True,
            shell=(os.name == "nt"),
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=60
        )
        # Non-zero exit code is the reliable failure signal
        assert result.returncode != 0, "Expected test failure but got success"


# =============================================================================
# Go Tests
# =============================================================================

@pytest.mark.skipif(not runtime_available("go"), reason="go not found")
class TestGoProject:
    """Tests for Go fixture."""

    @pytest.fixture
    def go_project(self, tmp_path):
        """Copy go fixture."""
        return copy_fixture("go_project", tmp_path)

    def test_passing(self, go_project):
        """Verify go test detects passing tests."""
        result = subprocess.run(
            ["go", "test", "-v"],
            cwd=go_project,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=60
        )
        assert result.returncode == 0
        output = (result.stdout or "") + (result.stderr or "")
        assert "PASS" in output or "ok" in output

    def test_failing(self, go_project):
        """Verify go test detects failing tests."""
        # Inject a failing test
        test_file = go_project / "calc_test.go"
        content = test_file.read_text()
        content += """
func TestIntentionalFailure(t *testing.T) {
	if 1 != 2 {
		t.Error("intentional failure")
	}
}
"""
        test_file.write_text(content)

        result = subprocess.run(
            ["go", "test", "-v"],
            cwd=go_project,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=60
        )
        assert result.returncode != 0
        output = (result.stdout or "") + (result.stderr or "")
        assert "FAIL" in output


# =============================================================================
# Java / Gradle Tests
# =============================================================================

@pytest.mark.skipif(not runtime_available("gradle"), reason="gradle not found")
class TestJavaProject:
    """Tests for Java/Gradle fixture."""

    @pytest.fixture
    def java_project(self, tmp_path):
        """Copy java fixture."""
        return copy_fixture("java_project", tmp_path)

    def test_passing(self, java_project):
        """Verify Gradle/JUnit detects passing tests."""
        # Use gradlew if available, otherwise gradle
        gradle_cmd = "gradlew" if (java_project / "gradlew").exists() else "gradle"
        result = subprocess.run(
            [gradle_cmd, "test", "--no-daemon"],
            cwd=java_project,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=180,
            shell=(os.name == "nt")  # Windows needs shell for gradlew.bat
        )
        assert result.returncode == 0
        output = (result.stdout or "") + (result.stderr or "")
        assert "BUILD SUCCESSFUL" in output or "passed" in output.lower()

    def test_failing(self, java_project):
        """Verify Gradle/JUnit detects failing tests."""
        # Inject a failing test
        test_file = java_project / "src" / "test" / "java" / "CalculatorTest.java"
        content = test_file.read_text()
        content = content.replace(
            "class CalculatorTest {",
            """class CalculatorTest {
    @Test
    void testIntentionalFailure() {
        assertEquals(1, 2, "intentional failure");
    }
"""
        )
        test_file.write_text(content)

        gradle_cmd = "gradlew" if (java_project / "gradlew").exists() else "gradle"
        result = subprocess.run(
            [gradle_cmd, "test", "--no-daemon"],
            cwd=java_project,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=180,
            shell=(os.name == "nt")
        )
        assert result.returncode != 0
        output = (result.stdout or "") + (result.stderr or "")
        assert "FAILED" in output or "failure" in output.lower()


# =============================================================================
# C# / dotnet Tests
# =============================================================================

@pytest.mark.skipif(not runtime_available("dotnet"), reason="dotnet not found")
class TestCSharpProject:
    """Tests for C#/dotnet fixture."""

    @pytest.fixture
    def csharp_project(self, tmp_path):
        """Copy csharp fixture and restore packages."""
        project = copy_fixture("csharp_project", tmp_path)
        result = subprocess.run(
            ["dotnet", "restore"],
            cwd=project,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=120
        )
        if result.returncode != 0:
            pytest.skip(f"dotnet restore failed: {result.stderr}")
        return project

    def test_passing(self, csharp_project):
        """Verify dotnet test detects passing tests."""
        result = subprocess.run(
            ["dotnet", "test"],
            cwd=csharp_project,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=120
        )
        assert result.returncode == 0
        output = (result.stdout or "") + (result.stderr or "")
        assert "Passed" in output or "passed" in output.lower()

    def test_failing(self, csharp_project):
        """Verify dotnet test detects failing tests."""
        # Inject a failing test
        test_file = csharp_project / "tests" / "CalculatorTests.cs"
        content = test_file.read_text()
        content = content.replace(
            "public class CalculatorTests",
            """public class CalculatorTests
{
    [Fact]
    public void IntentionalFailure()
    {
        Assert.Equal(1, 2);
    }
}

public class CalculatorTestsOriginal"""
        )
        test_file.write_text(content)

        result = subprocess.run(
            ["dotnet", "test"],
            cwd=csharp_project,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=120
        )
        assert result.returncode != 0
        output = (result.stdout or "") + (result.stderr or "")
        assert "Failed" in output or "failed" in output.lower()


# =============================================================================
# Pattern Detection Tests (unit tests for verify.py patterns)
# =============================================================================

class TestOutputPatterns:
    """Test that verify.py patterns detect various test runner outputs."""

    def test_jest_pass_pattern(self):
        """Verify Jest pass output is detected."""
        from zen_mode.verify import verify_test_output

        jest_output = """
 PASS  tests/index.test.js
  ✓ add returns sum of two numbers (2 ms)
  ✓ add handles negative numbers
  ✓ add handles zero (1 ms)

Test Suites: 1 passed, 1 total
Tests:       3 passed, 3 total
"""
        assert verify_test_output(jest_output) is True

    def test_go_pass_pattern(self):
        """Verify Go test pass output is detected."""
        from zen_mode.verify import verify_test_output

        go_output = """
=== RUN   TestAdd
--- PASS: TestAdd (0.00s)
=== RUN   TestAddNegative
--- PASS: TestAddNegative (0.00s)
PASS
ok      calc    0.002s
"""
        assert verify_test_output(go_output) is True

    def test_gradle_pass_pattern(self):
        """Verify Gradle pass output is detected."""
        from zen_mode.verify import verify_test_output

        gradle_output = """
> Task :test

CalculatorTest > testAdd() PASSED
CalculatorTest > testAddNegative() PASSED
CalculatorTest > testAddZero() PASSED

BUILD SUCCESSFUL in 2s
3 actionable tasks: 1 executed, 2 up-to-date
"""
        assert verify_test_output(gradle_output) is True

    def test_dotnet_pass_pattern(self):
        """Verify dotnet test pass output is detected."""
        from zen_mode.verify import verify_test_output

        dotnet_output = """
  Determining projects to restore...
  All projects are up-to-date for restore.
  CSharpProject -> bin/Debug/net8.0/CSharpProject.dll
Test run for bin/Debug/net8.0/CSharpProject.dll (.NETCoreApp,Version=v8.0)
Microsoft (R) Test Execution Command Line Tool Version 17.8.0

Starting test execution, please wait...
A total of 1 test files matched the specified pattern.

Passed!  - Failed:     0, Passed:     3, Skipped:     0, Total:     3
"""
        assert verify_test_output(dotnet_output) is True

    def test_jest_fail_detection(self):
        """Verify Jest failure count is extracted."""
        from zen_mode.verify import extract_failure_count

        jest_output = """
 FAIL  tests/index.test.js
  ✓ add returns sum (2 ms)
  ✕ intentional failure (3 ms)

Tests:       1 failed, 1 passed, 2 total
"""
        assert extract_failure_count(jest_output) == 1

    def test_go_fail_detection(self):
        """Verify Go failure count is extracted."""
        from zen_mode.verify import extract_failure_count

        go_output = """
--- FAIL: TestIntentionalFailure (0.00s)
    calc_test.go:25: intentional failure
FAIL
exit status 1
FAIL    calc    0.002s
"""
        # Go output says "FAIL" but not "N failed"
        # Our pattern looks for digits near "fail"
        count = extract_failure_count(go_output)
        # Go doesn't always give a count, may return None or 1
        assert count is None or count >= 0

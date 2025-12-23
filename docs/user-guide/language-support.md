# Multi-Language Test Support

Currently tested and working: node + jest tests, python + pytest, java + gradle + junit, csharp dotnet + xunit

## Goal
Create minimal test fixtures for all major languages to verify `phase_verify()` works across different build systems and test runners.

## Supported Languages (17 total)

| Language | Test Runner | Build System | Fixture Dir |
|----------|-------------|--------------|-------------|
| Python | pytest | pip/pyproject.toml | `python_project/` |
| Node/JS | Jest | npm/package.json | `node_project/` |
| Go | go test | go modules | `go_project/` |
| Rust | cargo test | Cargo.toml | `rust_project/` |
| Java | JUnit | Gradle | `java_project/` |
| C# | xUnit/NUnit | dotnet SDK | `csharp_project/` |
| Ruby | RSpec | Bundler/Gemfile | `ruby_project/` |
| PHP | PHPUnit | Composer | `php_project/` |
| Kotlin | JUnit | Gradle Kotlin DSL | `kotlin_project/` |
| Swift | XCTest | Swift Package Manager | `swift_project/` |
| C | CTest | CMake | `c_project/` |
| C++ | CTest/GTest | CMake + vcpkg | `cpp_project/` |
| Zig | zig test | build.zig | `zig_project/` |
| Scala | ScalaTest | sbt | `scala_project/` |
| Dart | dart test | pubspec.yaml | `dart_project/` |
| Elixir | ExUnit | mix | `elixir_project/` |
| Haskell | HSpec | cabal/stack | `haskell_project/` |

## Fixture Structure (each project)

```
<lang>_project/
├── src/           # Source code (1 file, ~5 lines)
├── tests/         # Test file (1 file, ~10 lines)
└── <config>       # Build/test config
```

Each fixture has:
1. A simple `add(a, b)` function
2. One passing test: `assert add(1, 2) == 3`
3. Minimal config file for the build system

## Implementation Plan

### Phase 1: Core 4 (different paradigms)
First pass - prove it works across fundamentally different ecosystems:

| Language | Build | Test Runner | Validates |
|----------|-------|-------------|-----------|
| Node/JS | npm | Jest | Interpreted, npm ecosystem |
| Go | go modules | go test | Compiled, no build tool |
| Java | Gradle | JUnit 5 | JVM, complex build system |
| C# | dotnet SDK | xUnit | CLR, different runtime |

Deliverables:
- `tests/fixtures/{node,go,java,csharp}_project/`
- `tests/test_verify_languages.py` with skip logic
- Each fixture: passing test, failing variant, no-tests variant

### Phase 2: More scripting languages
- Ruby (RSpec + Bundler)
- PHP (PHPUnit + Composer)
- Python (pytest) - last since already works
- Elixir (ExUnit + mix)

### Phase 3: More compiled languages
- Rust (cargo test)
- Zig (zig test)
- Swift (SPM + XCTest)
- Dart (dart test)

### Phase 4: JVM variants
- Kotlin (Gradle Kotlin DSL)
- Scala (sbt + ScalaTest)
- Java Maven (alternative to Gradle)

### Phase 5: Systems languages
- C (CMake + CTest)
- C++ (CMake + GTest/Catch2)
- Haskell (cabal + HSpec)

### Phase 6: Advanced fixtures (optional)
- `node_yarn_pnp/` - Yarn PnP zero-install
- `python_poetry/` - Poetry lockfile
- `rust_workspace/` - Cargo workspace
- `java_multi_module/` - Multi-module Maven

## Integration Tests

**File**: `tests/test_verify_languages.py`

```python
import pytest
import shutil

def runtime_available(cmd):
    return shutil.which(cmd) is not None

@pytest.mark.skipif(not runtime_available("python"), reason="python not found")
def test_python_passing():
    ...

@pytest.mark.skipif(not runtime_available("node"), reason="node not found")
def test_node_passing():
    ...

@pytest.mark.skipif(not runtime_available("go"), reason="go not found")
def test_go_passing():
    ...
```

Each language gets:
- `test_<lang>_passing()` - verify TESTS_PASS detected
- `test_<lang>_failing()` - verify TESTS_FAIL detected (inject failure)
- `test_<lang>_no_tests()` - verify TESTS_NONE detected (empty project)

## Runtime Detection & UX Improvements

### Current Implementation ✅
- Gracefully skips verification when runtime not installed
- Clear messaging: `[VERIFY] Runtime 'gradle' not installed, skipping tests.`
- No hangs or timeouts waiting for non-existent runtimes
- Fast Track can still complete successfully

### Future Considerations

**1. Installation Suggestions**
- Should we add warnings/suggestions to install missing runtimes?
- Example output:
  ```
  [VERIFY] Runtime 'gradle' not installed, skipping tests.
  [HINT] Install gradle with: choco install gradle -y
  ```
- Benefits: Helps users quickly resolve missing dependencies
- Considerations: Platform-specific (Windows/macOS/Linux install commands differ)

**2. Runtime Availability Tracking**
- Track which runtimes are checked but missing for better UX
- Could maintain a session-level cache of runtime checks
- Benefits:
  - Avoid redundant runtime checks in same session
  - Could provide summary at end: "Note: Skipped tests in 3 projects due to missing runtimes: gradle, cargo, go"
  - Could suggest batch install command
- Use cases:
  - Multi-file changes across different language projects
  - First-time setup experience

## Success Criteria

- [ ] All 17 fixtures created
- [ ] Integration tests pass on CI (with available runtimes)
- [ ] `phase_verify()` correctly detects pass/fail/none for each
- [ ] Tests skip gracefully when runtime not installed

---

## Notes (from brainstorming)

### Step 5: Create multi-language test fixtures

**Directory**: `tests/fixtures/`

Create minimal test projects:

```
tests/fixtures/
├── python_simple/
│   ├── app.py          # def add(a, b): return a + b
│   ├── test_app.py     # def test_add(): assert add(1, 2) == 3
│   └── pyproject.toml
│
├── node_simple/
│   ├── index.js        # module.exports = { add: (a, b) => a + b }
│   ├── index.test.js   # test('add', () => expect(add(1, 2)).toBe(3))
│   └── package.json
│
├── java_simple/
│   ├── src/main/java/Calculator.java
│   ├── src/test/java/CalculatorTest.java
│   └── build.gradle
│
└── go_simple/
    ├── calc.go         # func Add(a, b int) int { return a + b }
    └── calc_test.go    # func TestAdd(t *testing.T) { ... }
```

### Step 6: Create integration tests for verify phase

**File**: `tests/test_verify_integration.py`

Tests that actually run test suites:
- `test_verify_python_passing()`
- `test_verify_python_failing()`
- `test_verify_node_passing()` (if node available)
- `test_verify_java_passing()` (if gradle available)
- `test_verify_detects_no_tests()`
  Multi-Language Test Fixtures

  Need a tests/fixtures/ directory with minimal projects:

  tests/fixtures/
  ├── python_project/
  │   ├── src/app.py
  │   ├── tests/test_app.py
  │   └── pyproject.toml
  ├── node_project/
  │   ├── src/index.js
  │   ├── tests/index.test.js
  │   └── package.json
  ├── java_project/
  │   ├── src/main/java/App.java
  │   ├── src/test/java/AppTest.java
  │   └── build.gradle
  ├── rust_project/
  │   ├── src/lib.rs
  │   └── Cargo.toml
  └── go_project/
      ├── main.go
      └── main_test.go

  Each fixture needs:
  1. A passing test (baseline)
  2. A way to inject a failing test (for fix verification)


1. C# / .NET  
   tests/fixtures/csharp_project/  
   ├── src/Program.cs  
   ├── tests/UnitTest1.cs  
   └── project.csproj (SDK-style, net8.0)

2. Ruby  
   tests/fixtures/ruby_project/  
   ├── lib/app.rb  
   ├── spec/app_spec.rb  
   └── Gemfile (+ Gemfile.lock if you want a lockfile fixture)

3. PHP / Composer  
   tests/fixtures/php_project/  
   ├── src/App.php  
   ├── tests/AppTest.php  
   ├── composer.json  
   └── composer.lock

4. Kotlin (JVM)  
   tests/fixtures/kotlin_project/  
   ├── src/main/kotlin/App.kt  
   ├── src/test/kotlin/AppTest.kt  
   └── build.gradle.kts (Gradle Kotlin DSL)

5. Swift (server-side)  
   tests/fixtures/swift_project/  
   ├── Sources/App.swift  
   ├── Tests/AppTests/AppTests.swift  
   └── Package.swift

6. C / CMake  
   tests/fixtures/c_project/  
   ├── src/main.c  
   ├── tests/test_main.c  
   └── CMakeLists.txt

7. C++ / vcpkg  
   tests/fixtures/cpp_project/  
   ├── src/app.cpp  
   ├── tests/app_test.cpp  
   ├── CMakeLists.txt  
   └── vcpkg.json (manifest mode)

8. Zig  
   tests/fixtures/zig_project/  
   ├── src/main.zig  
   ├── src/main_test.zig  
   └── build.zig

9. Scala (sbt)  
   tests/fixtures/scala_project/  
   ├── src/main/scala/App.scala  
   ├── src/test/scala/AppTest.scala  
   └── build.sbt

10. Dart / Flutter (optional)  
    tests/fixtures/dart_project/  
    ├── lib/main.dart  
    ├── test/widget_test.dart  
    └── pubspec.yaml

Nice-to-have extras
- Multi-module Maven: java_multi_module/ (parent pom + two sub-modules).  
- Yarn PnP: node_yarn_pnp/ (.yarnrc.yml, zero-install cache).  
- Poetry lock: python_poetry/ (poetry.lock alongside pyproject.toml).  
- Cargo workspace: rust_workspace/ (top-level Cargo.toml + two member crates).

Keep each fixture “hello-world” sized; the goal is fast CI bootstrapping, not real code.
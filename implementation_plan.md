# Zen.py Refinements - Implementation Plan

Changes to `scripts/zen.py` and `src/zen_mode/` organized by priority.

---

## P1: High Priority (Bugs & Security)

### 1.1 Linter: Skip Binary & Large Files

**Problem:** Linter may crash or hang on binary/large files.

**Location:** `src/zen_mode/linter.py` - file scanning logic

**Implementation:**
```python
def is_text_file(filepath: Path) -> bool:
    """Check if file is text (not binary)."""
    try:
        with open(filepath, 'rb') as f:
            chunk = f.read(1024)
            return b'\x00' not in chunk  # Binary files contain null bytes
    except Exception:
        return False

# In scan loop:
if filepath.stat().st_size > 1_000_000:  # Skip files > 1MB
    continue
if not is_text_file(filepath):
    continue
```

**Effort:** ~20 LOC | **Risk:** Low

---

### 1.2 Security: Input Path Sanitization

**Problem:** Task file path used directly; potential path traversal.

**Location:** `run()` function in both files

**Implementation:**
```python
# Current
task_path = Path(task_file)

# Fixed
task_path = Path(task_file).resolve()
if not task_path.is_relative_to(PROJECT_ROOT):
    print(f"ERROR: Task file must be within project: {PROJECT_ROOT}")
    sys.exit(1)
```

**Effort:** ~10 LOC | **Risk:** Low

---

### 1.3 Linter: Fix HARDCODED_IP False Positives

**Problem:** Regex negative lookahead only matches first octet. Private IPs like `192.168.1.1` may still trigger.

**Location:** `src/zen_mode/linter.py` - HARDCODED_IP rule

**Implementation:**
```python
import ipaddress

def is_private_or_special_ip(ip_str: str) -> bool:
    """Check if IP is private, loopback, or link-local."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        return False

# Replace regex-only approach:
IP_PATTERN = re.compile(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b')

def check_hardcoded_ip(line: str, line_num: int) -> list:
    issues = []
    for match in IP_PATTERN.finditer(line):
        ip = match.group(1)
        if not is_private_or_special_ip(ip):
            issues.append(Issue("HARDCODED_IP", line_num, f"Public IP: {ip}"))
    return issues
```

**Effort:** ~15 LOC | **Risk:** Low

---

## P2: Medium Priority (Cost & Quality)

### 2.1 Haiku-First Test Execution

**Problem:** Test runs use Sonnet ($0.30+) even when tests pass first try.

**Location:** `phase_verify()` in both files

**Implementation:**
```python
def phase_verify() -> bool:
    # First attempt: Haiku just runs tests (no fixing)
    haiku_prompt = f"""<task>
Run the test suite and report results.
</task>

<actions>
1. Run: pytest -q --tb=short (or project's test command)
2. Write output to: {TEST_OUTPUT_PATH}
</actions>

<output>
End with: TESTS_PASS or TESTS_FAIL
</output>"""

    output = run_claude(haiku_prompt, model=MODEL_EYES, phase="verify_check")

    if "TESTS_PASS" in output and verify_test_output(read_file(TEST_OUTPUT_FILE)):
        log("[VERIFY] Passed (Haiku).")
        return True

    # Tests failed or unclear - escalate to Sonnet for fixing
    log("[VERIFY] Escalating to Sonnet for fixes...")
    # ... existing Sonnet retry logic ...
```

**Savings:** ~$0.27 per run when tests pass first try

**Effort:** ~30 LOC | **Risk:** Medium (adds complexity)

---

### 2.2 Linter: Per-Line Disable Comments

**Problem:** No way to suppress false positives inline.

**Location:** `src/zen_mode/linter.py` - main check loop

**Syntax:**
```python
secret = "not-a-secret"  # zenlint: ignore POSSIBLE_SECRET
```

**Implementation:**
```python
IGNORE_PATTERN = re.compile(r'#\s*zenlint:\s*ignore\s+(\w+)')

def get_ignored_rules(line: str) -> set[str]:
    """Extract rule names to ignore from line comment."""
    match = IGNORE_PATTERN.search(line)
    return {match.group(1)} if match else set()

# In check loop:
ignored = get_ignored_rules(line)
if rule_name in ignored:
    continue
```

**Effort:** ~20 LOC | **Risk:** Low

---

### 2.3 Linter: Language-Specific Rule Scoping

**Problem:** Rules like `INLINE_IMPORT` trigger on non-applicable languages.

**Location:** `src/zen_mode/linter.py` - rule definitions

**Implementation:**
```python
RULE_EXTENSIONS = {
    "INLINE_IMPORT": {"py", "js", "ts", "tsx", "jsx"},
    "POSSIBLE_SECRET": {"*"},  # All files
    "HARDCODED_IP": {"*"},
    "TODO_FIXME": {"*"},
    # ... map each rule
}

def rule_applies_to_file(rule_name: str, filepath: Path) -> bool:
    extensions = RULE_EXTENSIONS.get(rule_name, {"*"})
    if "*" in extensions:
        return True
    return filepath.suffix.lstrip(".").lower() in extensions
```

**Effort:** ~40 LOC | **Risk:** Low

---

## P3: Low Priority (Nice to Have)

### 3.1 File Size Annotations in Scout

**Problem:** Model may waste tokens reading massive files.

**Implementation:** Add `[LARGE]` / `[MASSIVE]` tags to file tree in scout prompt.

**Effort:** ~25 LOC | **Defer until:** P1-P2 complete

---

### 3.2 Dry Run Mode Enhancement

**Problem:** `--dry-run` output is minimal.

**Improvements:**
- Print prompts that would be sent
- Show which files would be created
- Add `--verbose` flag

**Effort:** ~30 LOC | **Defer until:** User requests

---

### 3.3 Documentation & --help

**Problem:** No built-in help or examples.

**Improvements:**
- Add `--help` with usage examples
- Sample task file in repo
- Link to CLAUDE.md

**Effort:** ~20 LOC | **Defer until:** Public release

---

### 3.4 Break Up God Class

**Problem:** `zen.py` is 1000+ LOC single file.

**Target Structure:**
```
zen/
├── __main__.py          # CLI entrypoint
├── core/state.py        # WorkDir, TaskState
├── planning/planner.py  # Scout, Plan phases
├── execution/runner.py  # Implement phase
├── judge/judge.py       # Judge phase
└── utils/files.py       # File helpers
```

**Effort:** ~200+ LOC refactor | **Defer until:** Pain point or major feature

---

## Implementation Order

| Step | Item | Effort | Gate |
|------|------|--------|------|
| 1 | 1.1 Skip binary/large files | ~20 LOC | Linter doesn't crash on test repo |
| 2 | 1.2 Path sanitization | ~10 LOC | Rejects `../../../etc/passwd` |
| 3 | 1.3 HARDCODED_IP fix | ~15 LOC | `192.168.x.x` no longer flagged |
| 4 | 2.1 Haiku-first tests | ~30 LOC | Cost drops when tests pass |
| 5 | 2.2 `# zenlint: ignore` | ~20 LOC | Inline suppression works |
| 6 | 2.3 Language scoping | ~40 LOC | JS rules don't fire on .md |

---

## Completed

- [x] XML Prompt Structuring (all 6 prompts refactored)
- [x] Scout uses Haiku instead of Sonnet
- [x] Cost tracking with per-phase breakdown

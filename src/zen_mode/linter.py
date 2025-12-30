"""
Zen Lint: Universal "Lazy Coder" Detector.
Scans for forbidden patterns (TODO, FIXME, SHIM).
"""
import fnmatch
import ipaddress
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Import shared utilities
from zen_mode.files import IGNORE_DIRS, IGNORE_FILES, BINARY_EXTS

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

# Scope Constants
ALL = "ALL"
CODE = "CODE"
COMMENT = "COMMENT"
RAW = "RAW"  # Check original line with whitespace preserved

# Severity levels
SEVERITIES = ["HIGH", "MEDIUM", "LOW"]


@dataclass
class Rule:
    name: str
    pattern: str
    scope: str = ALL
    severity: str = "LOW"
    ignore_case: bool = True  # Most rules are case-insensitive; secrets opt out
    _compiled: re.Pattern = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        flags = re.IGNORECASE if self.ignore_case else 0
        self._compiled = re.compile(self.pattern, flags)

    def search(self, text: str) -> bool:
        return bool(self._compiled.search(text))


# -----------------------------------------------------------------------------
# Rules Definition
# -----------------------------------------------------------------------------

QUALITY_RULES = [
    # === HIGH SEVERITY: Security & Breakage ===
    Rule("API_KEY",
         r"['\"].{0,30}(api[_-]?key|secret|token|password|credential).{0,30}['\"]\s*[:=]\s*['\"][a-zA-Z0-9_\-]{8,}['\"]",
         CODE, "HIGH", ignore_case=False),
    Rule("PLACEHOLDER", r"\b[A-Z_]{2,}_HERE\b", CODE, "HIGH"),
    Rule("POSSIBLE_SECRET", r"\b(passwd|password|secret|api_?key)\s*=\s*['\"][^'\"]{8,}['\"]",
         CODE, "HIGH", ignore_case=False),
    Rule("CONFLICT_MARKER", r"^[<>=]{7}", ALL, "HIGH"),
    Rule("TRUNCATION_MARKER", r"\.{3}\s*(rest of|remaining|more|etc|continues|implementation)", ALL, "HIGH"),
    Rule("INCOMPLETE_IMPL", r"#\s*(TODO|FIXME):\s*(implement|finish|complete|add)\b", ALL, "HIGH"),
    Rule("OVERLY_GENERIC_EXCEPT", r"except\s*:\s*$", CODE, "HIGH"),
    Rule("BARE_RETURN_IN_CATCH", r"catch\s*\([^)]*\)\s*\{\s*return\s*;?\s*\}", CODE, "HIGH"),

    # === MEDIUM SEVERITY: Maintenance & Debt ===
    Rule("TODO", r"\bTODO\b", COMMENT, "MEDIUM"),
    Rule("FIXME", r"\bFIXME\b", COMMENT, "MEDIUM"),
    Rule("HACK", r"\bHACK\b", COMMENT, "MEDIUM"),
    Rule("XXX", r"\bXXX\b", COMMENT, "MEDIUM"),
    Rule("STUB_IMPL", r"^\s*(pass|\.{3})\s*$", CODE, "MEDIUM"),
    Rule("NOT_IMPLEMENTED", r"(raise\s+)?NotImplementedError|not\s+implemented", CODE, "MEDIUM"),
    Rule("HARDCODED_IP",
         # Simple pattern to match IP-like strings (validated separately)
         r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b",
         CODE, "MEDIUM"),
    Rule("AI_COMMENT_BOILERPLATE",
         r"^\s*#\s*(This (function|method|class|module)|The following)\s+(is used to|responsible for|will|provides|represents)\b",
         COMMENT, "MEDIUM"),
    Rule("INLINE_IMPORT",
         r"^\s+(?:import\s+\w|from\s+\w+\s+import|require\s*\(|using\s+\w)",
         RAW, "MEDIUM"),

    # === LOW SEVERITY: Smells & Cleanup ===
    Rule("DEBUG_PRINT", r"\b(console\.log|print|System\.out\.print|fmt\.Print(ln)?|puts|dd|var_dump)\s*\(", CODE,
         "LOW"),
    Rule("DEAD_COMMENT", r"\b(unused|dead code|commented.?out|remove.?this|delete.?this)\b", COMMENT, "LOW"),
    Rule("TEMP_FIX", r"\b(temp|temporary|workaround|band.?aid)\b", COMMENT, "LOW"),
    Rule("LINT_DISABLE", r"(eslint-disable|pylint:\s*disable|noqa|@ts-ignore|@ts-expect-error|rubocop:disable)",
         COMMENT, "LOW"),
    Rule("EXAMPLE_DATA", r"['\"](example|test[@.]|foo|bar|john[._]?doe|jane[._]?doe|lorem ipsum|acme)['\"]", CODE,
         "LOW"),
    Rule("CATCH_ALL_EXCEPTION", r"except\s+Exception\s*:|catch\s*\(\s*(Exception|Error|Throwable)\s+\w+\s*\)", CODE,
         "LOW"),
    Rule("MAGIC_NUMBER", r"(?<![0-9a-zA-Z_.])(86400|3600|31536000|604800|1440|525600)(?![0-9])", CODE, "LOW"),
    Rule("EMPTY_CATCH", r"(except.*:\s*pass|catch\s*\([^)]*\)\s*\{\s*\})", CODE, "LOW"),
    Rule("COPY_PASTE_COMMENT", r"(copied from|copy.?pasted?|stolen from|borrowed from)", COMMENT, "LOW"),
    Rule("EMPTY_DOCSTRING", r'("""|\'\'\')\s*\1', CODE, "LOW"),
]

# Extension-specific rule scoping (None = all extensions)
# Rules not listed here apply to all file types
RULE_EXTENSIONS: Dict[str, Optional[Set[str]]] = {
    # Python-specific patterns
    "OVERLY_GENERIC_EXCEPT": {".py", ".pyi"},
    "STUB_IMPL": {".py", ".pyi"},
    "NOT_IMPLEMENTED": {".py", ".pyi"},
    "EMPTY_DOCSTRING": {".py", ".pyi"},
    # JS/TS-specific patterns
    "BARE_RETURN_IN_CATCH": {".js", ".mjs", ".cjs", ".ts", ".jsx", ".tsx"},
    # Import statement rules apply to languages with imports
    "INLINE_IMPORT": {".py", ".pyi", ".js", ".mjs", ".cjs", ".ts", ".jsx", ".tsx", ".java", ".kt", ".scala", ".cs"},
}

# Language syntax definitions: (line_comment, block_start, block_end)
LANG_SYNTAX = {
    '.py': ('#', '"""', '"""'),
    '.pyi': ('#', '"""', '"""'),
    '.js': ('//', '/*', '*/'),
    '.mjs': ('//', '/*', '*/'),
    '.cjs': ('//', '/*', '*/'),
    '.ts': ('//', '/*', '*/'),
    '.jsx': ('//', '/*', '*/'),
    '.tsx': ('//', '/*', '*/'),
    '.java': ('//', '/*', '*/'),
    '.kt': ('//', '/*', '*/'),
    '.scala': ('//', '/*', '*/'),
    '.c': ('//', '/*', '*/'),
    '.h': ('//', '/*', '*/'),
    '.cpp': ('//', '/*', '*/'),
    '.hpp': ('//', '/*', '*/'),
    '.cc': ('//', '/*', '*/'),
    '.cs': ('//', '/*', '*/'),
    '.go': ('//', '/*', '*/'),
    '.rs': ('//', '/*', '*/'),
    '.swift': ('//', '/*', '*/'),
    '.php': ('//', '/*', '*/'),
    '.rb': ('#', '=begin', '=end'),
    '.sh': ('#', None, None),
    '.bash': ('#', None, None),
    '.zsh': ('#', None, None),
    '.fish': ('#', None, None),
    '.yaml': ('#', None, None),
    '.yml': ('#', None, None),
    '.toml': ('#', None, None),
    '.ini': (';', None, None),
    '.sql': ('--', '/*', '*/'),
    '.lua': ('--', '--[[', ']]'),
    '.r': ('#', None, None),
    '.jl': ('#', '#=', '=#'),
}

# Text file extensions to skip during linting (but not filtered from git)
# These are text files that could have secrets/TODOs but have too many false positives
LINT_SKIP_EXTS: Set[str] = {
    # Documentation (text) - too many false positives for TODOs
    ".md", ".markdown", ".rst", ".txt", ".adoc", ".textile",
    # Generated/minified code
    ".min.js", ".min.css", ".map", ".bundle.js",
    # Data files (could have secrets in templates, but too noisy to lint)
    ".csv", ".tsv",
    # Lock files already in IGNORE_FILES, but also by extension
    ".lock",
}

# Suppression patterns for different comment styles
# Supports both "zenlint: ignore RULE" and legacy "lint:ignore RULE"
SUPPRESS_PATTERNS = {
    '#': re.compile(r"#\s*(?:zen)?lint:\s*(ignore|disable)(?:\s+([A-Z_]+))?\b", re.IGNORECASE),
    '//': re.compile(r"//\s*(?:zen)?lint:\s*(ignore|disable)(?:\s+([A-Z_]+))?\b", re.IGNORECASE),
    '--': re.compile(r"--\s*(?:zen)?lint:\s*(ignore|disable)(?:\s+([A-Z_]+))?\b", re.IGNORECASE),
    ';': re.compile(r";\s*(?:zen)?lint:\s*(ignore|disable)(?:\s+([A-Z_]+))?\b", re.IGNORECASE),
}

def get_suppression_match(line: str, ext: str) -> Optional[re.Match[str]]:
    """Check for lint suppression comment based on language."""
    syntax = LANG_SYNTAX.get(ext)
    if syntax and syntax[0]:
        pattern = SUPPRESS_PATTERNS.get(syntax[0])
        if pattern:
            return pattern.search(line)
    # Fallback: try all patterns
    for pattern in SUPPRESS_PATTERNS.values():
        match = pattern.search(line)
        if match:
            return match
    return None

# Rules that should be skipped in test files (mock secrets are common)
TEST_EXEMPT_RULES: Set[str] = {"API_KEY", "POSSIBLE_SECRET", "EXAMPLE_DATA"}

# Patterns that indicate a test file (checked against full path)
# Matches: test_*.py, *_test.py, *.test.js, *.spec.ts, tests/, __tests__/
TEST_FILE_PATTERNS = re.compile(
    r"([\\/]|^)(tests?|spec|__tests__)[\\/]|"  # test directories
    r"[\\/]test_[^\\/]*$|"                      # /test_*.ext
    r"_test\.[^\\/]+$|"                         # *_test.ext
    r"\.test\.[^\\/]+$|"                        # *.test.ext
    r"\.spec\.[^\\/]+$",                        # *.spec.ext
    re.IGNORECASE
)


# -----------------------------------------------------------------------------
# Core Logic
# -----------------------------------------------------------------------------

def is_binary(path: Path, sample_size: int = 8192, threshold: float = 0.10, min_size: int = 1024) -> bool:
    """Check if file is binary using null byte ratio heuristic."""
    try:
        file_size = path.stat().st_size
        # Small files (< 1KB) are assumed to be text to avoid favicon/icon misdetection
        if file_size < min_size:
            return False
        blob = path.read_bytes()[:sample_size]
        if not blob:
            return False
        return blob.count(b'\0') / len(blob) > threshold
    except OSError as e:  # Includes PermissionError, FileNotFoundError
        logger.debug(f"Cannot read {path} for binary check: {e}")
        return True  # Conservative: treat as binary


def find_string_ranges(line: str) -> List[Tuple[int, int]]:
    """
    Find ranges of string literals in a line to avoid false comment detection.
    Returns list of (start, end) indices.
    Handles both single/double quotes and triple-quoted strings.
    """
    ranges = []
    i = 0
    length = len(line)

    while i < length:
        c = line[i]

        if c in ('"', "'", '`'):
            # Check for triple-quoted string
            if i + 2 < length and line[i:i+3] in ('"""', "'''"):
                triple = line[i:i+3]
                start = i
                i += 3
                # Look for closing triple quote
                while i + 2 < length:
                    if line[i] == '\\':
                        i += 2  # Skip escaped character
                        continue
                    if line[i:i+3] == triple:
                        ranges.append((start, i + 3))
                        i += 3
                        break
                    i += 1
                else:
                    # Unclosed triple quote - don't add to ranges (spans multiple lines)
                    i = length
            else:
                # Single-quoted string
                quote_char = c
                start = i
                i += 1
                while i < length:
                    if line[i] == '\\' and i + 1 < length:
                        i += 2  # Skip escaped character
                        continue
                    if line[i] == quote_char:
                        ranges.append((start, i + 1))
                        i += 1
                        break
                    i += 1
                else:
                    # Unclosed string - don't add to ranges
                    pass
        else:
            i += 1

    return ranges


def is_in_string(pos: int, ranges: List[Tuple[int, int]]) -> bool:
    """Check if a position falls within any string literal range."""
    return any(start <= pos < end for start, end in ranges)


def split_code_comment(line: str, ext: str) -> Tuple[str, str]:
    """
    Splits a line into (code, comment) with string-awareness.
    """
    syntax = LANG_SYNTAX.get(ext)

    if not syntax or not syntax[0]:
        return line, ""

    comment_char = syntax[0]
    string_ranges = find_string_ranges(line)

    # Find comment start that's not inside a string
    idx = 0
    while True:
        pos = line.find(comment_char, idx)
        if pos == -1:
            return line, ""

        if not is_in_string(pos, string_ranges):
            return line[:pos], line[pos + len(comment_char):]

        idx = pos + 1


@dataclass
class MultilineState:
    """Track multi-line comment state across lines."""
    in_block: bool = False
    block_end: Optional[str] = None


# Patterns that indicate a stub is legitimate (abstract methods, protocols)
ABSTRACT_PATTERNS = re.compile(
    r"@(abc\.)?(abstractmethod|abstractproperty)|"
    r"class\s+\w+\s*\([^)]*\b(ABC|Protocol|Interface)\b|"
    r"virtual|abstract\s+(class|void|int|string|bool)",
    re.IGNORECASE
)


def is_private_or_special_ip(ip_str: str) -> bool:
    """Check if IP is private, loopback, link-local, or otherwise special/reserved."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return (
            ip.is_private or
            ip.is_loopback or
            ip.is_link_local or
            ip.is_reserved or
            ip.is_multicast
        )
    except ValueError:
        # Not a valid IP address
        return False


def _rule_applies_to_ext(rule_name: str, ext: str) -> bool:
    """Check if a rule applies to the given file extension."""
    allowed = RULE_EXTENSIONS.get(rule_name)
    if allowed is None:
        return True  # No restriction, applies to all
    return ext in allowed


def check_file(path: str, min_severity: str = "LOW", config: Optional[Dict] = None) -> List[Dict]:
    """Scan a file for violations."""
    p = Path(path)

    if p.name == Path(__file__).name:
        return []

    # Pre-checks
    if not p.exists() or not p.is_file():
        return []
    if p.name in IGNORE_FILES:
        return []
    # Skip files in ignored directories (e.g., node_modules, .git, venv)
    if any(part in IGNORE_DIRS for part in p.parts):
        return []
    # Skip binary files (never lint)
    if p.suffix.lower() in BINARY_EXTS:
        return []
    # Skip text files with too many false positives
    if p.suffix.lower() in LINT_SKIP_EXTS:
        return []
    # Skip large files (> 1MB) to avoid performance issues
    if p.stat().st_size > 1_000_000:
        return []
    if is_binary(p):
        return []

    violations = []
    severity_threshold = SEVERITIES.index(min_severity)

    # Check if this is a test file (exempt from secret detection rules)
    is_test_file = bool(TEST_FILE_PATTERNS.search(str(p)))

    # Get rules (with config overrides if provided)
    rules = QUALITY_RULES
    if config:
        disabled = set(config.get("disabled_rules", []))
        rules = [r for r in rules if r.name not in disabled]

    # Skip secret detection rules in test files
    if is_test_file:
        rules = [r for r in rules if r.name not in TEST_EXEMPT_RULES]

    try:
        try:
            content = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            logger.debug(f"File {p} contains non-UTF-8 bytes, using latin-1 fallback")
            content = p.read_text(encoding="latin-1")
        lines = content.splitlines()
        ext = p.suffix.lower()
        syntax = LANG_SYNTAX.get(ext)

        # Filter rules by extension scope
        rules = [r for r in rules if _rule_applies_to_ext(r.name, ext)]

        # Multi-line comment tracking
        ml_state = MultilineState()

        for i, line in enumerate(lines):
            line_num = i + 1
            original_line = line
            stripped = line.strip()

            if not stripped:
                continue

            # Check for inline suppression
            suppression_match = get_suppression_match(line, ext)
            if suppression_match:
                specific_rule = suppression_match.group(2)
                if not specific_rule:
                    # Suppress all rules for this line
                    continue

            # Handle multi-line comment state
            is_comment_line = False
            string_ranges = find_string_ranges(stripped)

            if syntax and syntax[1] and syntax[2]:
                block_start, block_end = syntax[1], syntax[2]

                if ml_state.in_block:
                    is_comment_line = True
                    if block_end in stripped:
                        ml_state.in_block = False
                else:
                    # Check for block comment start, but not inside strings
                    start_pos = stripped.find(block_start)
                    if start_pos != -1 and not is_in_string(start_pos, string_ranges):
                        end_pos = stripped.find(block_end, start_pos + len(block_start))
                        if end_pos == -1:
                            ml_state.in_block = True
                            ml_state.block_end = block_end

            # Split code and comment
            if is_comment_line:
                code_part, comment_part = "", stripped
            else:
                code_part, comment_part = split_code_comment(stripped, ext)

            for rule in rules:
                # Check severity threshold
                if SEVERITIES.index(rule.severity) > severity_threshold:
                    continue

                if suppression_match and suppression_match.group(2):
                    if rule.name.upper() == suppression_match.group(2).upper():
                        continue

                # Determine target text based on scope
                if rule.scope == ALL:
                    target = stripped
                elif rule.scope == RAW:
                    target = original_line
                elif rule.scope == CODE:
                    target = code_part
                elif rule.scope == COMMENT:
                    target = comment_part
                else:
                    target = stripped

                if not target:
                    continue

                match = rule._compiled.search(target)
                if match:
                    # Skip STUB_IMPL for abstract methods/protocols
                    if rule.name == "STUB_IMPL":
                        # Check previous lines for abstract/protocol context
                        context_start = max(0, i - 5)
                        context = "\n".join(lines[context_start:i + 1])
                        if ABSTRACT_PATTERNS.search(context):
                            continue

                    # Skip HARDCODED_IP for private/special IPs
                    if rule.name == "HARDCODED_IP":
                        ip_str = match.group(1)  # Extract IP from capturing group
                        if is_private_or_special_ip(ip_str):
                            continue

                    violations.append({
                        'rule': rule.name,
                        'severity': rule.severity,
                        'file': str(p),
                        'line': line_num,
                        'content': stripped[:80]  # Shorter preview
                    })

    except OSError as e:
        logger.error(f"Error scanning {path}: {e}")
        return []  # Explicit return, file skipped due to I/O error

    return violations


def load_config(config_path: Optional[str]) -> Optional[Dict]:
    """Load configuration from JSON file."""
    if not config_path:
        # Look for default config files
        for name in [".lintrc.json", ".lintrc", "lint.config.json"]:
            if Path(name).exists():
                config_path = name
                break

    if config_path and Path(config_path).exists():
        try:
            with open(config_path) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning(f"Could not load config {config_path}: {e}")

    return None


# -----------------------------------------------------------------------------
# Reporting
# -----------------------------------------------------------------------------

def format_report(violations: List[Dict], output_format: str = "text") -> Tuple[str, int]:
    """Format violations report. Returns (output_string, exit_code)."""
    output = StringIO()

    if output_format == "json":
        output.write(json.dumps({"violations": violations, "count": len(violations)}, indent=2))
        high_count = sum(1 for v in violations if v['severity'] == "HIGH")
        return output.getvalue(), 1 if high_count > 0 else 0

    # SARIF format for CI integration
    if output_format == "sarif":
        sarif = {
            "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "version": "2.1.0",
            "runs": [{
                "tool": {
                    "driver": {
                        "name": "zen-lint",
                        "version": "1.0.0",
                        "rules": [{"id": r.name, "shortDescription": {"text": r.name}} for r in QUALITY_RULES]
                    }
                },
                "results": [
                    {
                        "ruleId": v['rule'],
                        "level": "error" if v['severity'] == "HIGH" else (
                            "warning" if v['severity'] == "MEDIUM" else "note"),
                        "message": {"text": v['content']},
                        "locations": [{
                            "physicalLocation": {
                                "artifactLocation": {"uri": v['file']},
                                "region": {"startLine": v['line']}
                            }
                        }]
                    } for v in violations
                ]
            }]
        }
        output.write(json.dumps(sarif, indent=2))
        high_count = sum(1 for v in violations if v['severity'] == "HIGH")
        return output.getvalue(), 1 if high_count > 0 else 0

    # Text format — compact for agents
    if not violations:
        output.write("[PASS] No issues.")
        return output.getvalue(), 0

    severity_order = {s: i for i, s in enumerate(SEVERITIES)}
    violations.sort(key=lambda x: (severity_order.get(x['severity'], 99), x['file'], x['line']))

    output.write(f"Found {len(violations)} issue(s):\n\n")

    for v in violations:
        output.write(f"[{v['severity']}] {v['file']}:{v['line']} {v['rule']}\n")

    # Summary
    counts = {s: sum(1 for v in violations if v['severity'] == s) for s in SEVERITIES}
    summary = ", ".join(f"{counts[s]} {s.lower()}" for s in SEVERITIES if counts[s])
    output.write(f"\nSummary: {summary}\n")

    if counts["HIGH"] > 0:
        output.write("[FAIL] High severity issues found.\n")
        return output.getvalue(), 1
    return output.getvalue(), 0


def print_report(violations: List[Dict], output_format: str = "text") -> int:
    """Print violations report and return exit code."""
    output, exit_code = format_report(violations, output_format)
    print(output)
    return exit_code


def print_rules():
    """Print all available rules."""
    print("\nAvailable Rules:\n")
    for sev in SEVERITIES:
        rules = [r for r in QUALITY_RULES if r.severity == sev]
        if rules:
            print(f"[{sev}]")
            for r in rules:
                print(f"  {r.name}: {r.pattern[:60]}{'...' if len(r.pattern) > 60 else ''}")
            print()


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------

def run_lint(paths: Optional[List[str]] = None, min_severity: str = "LOW",
             config_path: Optional[str] = None) -> Tuple[bool, str]:
    """
    Run the linter and return results.

    Args:
        paths: Files or directories to scan (defaults to git changes or cwd)
        min_severity: Minimum severity level to report
        config_path: Path to config file

    Returns:
        Tuple of (passed: bool, output: str)
    """
    config = load_config(config_path)

    # Determine paths to scan (caller provides paths, defaults to cwd)
    if not paths:
        paths = ["."]

    all_violations = []

    for root_arg in paths:
        path = Path(root_arg)
        if path.is_file():
            all_violations.extend(check_file(str(path), min_severity, config))
        elif path.is_dir():
            # Walk directory tree, pruning ignored dirs early for efficiency
            for root, dirs, files in os.walk(path):
                # Prune ignored directories IN-PLACE (prevents descending into them)
                # This is the standard Python pattern for efficient directory filtering
                def should_keep_dir(d):
                    # Check exact match
                    if d in IGNORE_DIRS:
                        return False
                    # Check glob patterns (e.g., *.egg-info)
                    if any(fnmatch.fnmatch(d, pattern) for pattern in IGNORE_DIRS if '*' in pattern):
                        return False
                    # Check hidden directories
                    if d.startswith('.'):
                        return False
                    return True
                dirs[:] = [d for d in dirs if should_keep_dir(d)]

                # Check files in this directory
                for file in files:
                    # Skip ignored files
                    if file in IGNORE_FILES:
                        continue
                    # Skip binary extensions (never lint)
                    if any(file.endswith(ext) for ext in BINARY_EXTS):
                        continue
                    # Skip text files with too many false positives
                    if any(file.endswith(ext) for ext in LINT_SKIP_EXTS):
                        continue

                    file_path = Path(root) / file
                    all_violations.extend(check_file(str(file_path), min_severity, config))

    output, exit_code = format_report(all_violations, "text")
    return exit_code == 0, output

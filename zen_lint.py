#!/usr/bin/env python3
"""
The Zen Linter.
Enforces "Clean Code" policies that LLMs love to ignore.
"""
import sys
import re
from pathlib import Path

# Pair the Error Name with the Regex
FORBIDDEN_RULES = [
    ("DEPRECATED", re.compile(r"\bdeprecated\b", re.I)),
    ("LEGACY", re.compile(r"\blegacy\b", re.I)),
    ("SHIM", re.compile(r"\bshim\b", re.I)),
    ("BACK-COMPAT", re.compile(r"\bbackward_compatibility\b", re.I)),
    ("TYPE-IGNORE", re.compile(r"#\s*type:\s*ignore", re.I)),
    ("TODO", re.compile(r"\bTODO\b")),
    ("FIXME", re.compile(r"\bFIXME\b")),
]


def check_file(path: str) -> list[str]:
    p = Path(path)
    if not p.exists():
        return []

    # Exclude tests, hidden files, and the work directory
    if "test" in p.name.lower() or p.name.startswith(".") or ".zen" in str(p):
        return []

    # Skip non-python files (optional, adjust as needed)
    # if p.suffix != ".py":
    #     return []

    content = p.read_text(encoding="utf-8")
    errors = []

    for i, line in enumerate(content.splitlines(), 1):
        for name, regex in FORBIDDEN_RULES:
            if regex.search(line):
                # We found a violation
                errors.append(f"Line {i}: Found {name} ('{line.strip()[:40]}...'). DELETE IT.")
                break  # Report one error per line max to reduce noise

    return errors


if __name__ == "__main__":
    # Default to scanning current directory if no args
    paths = sys.argv[1:] if len(sys.argv) > 1 else ["."]

    all_errors = []

    for root_arg in paths:
        root_path = Path(root_arg)
        if root_path.is_file():
            all_errors.extend(check_file(str(root_path)))
        else:
            for p in root_path.rglob("*.py"):
                all_errors.extend(check_file(str(p)))

    if all_errors:
        print(f"\n[LINT] Found {len(all_errors)} Clean Code violations:")
        for e in all_errors:
            print(f"  {e}")
        print("\nRULE: Clean Breaks Over Shims. Fix these violations.")
        sys.exit(1)
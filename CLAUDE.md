# CODING GUIDELINES

## 1. THE GOLDEN RULES
1. **NO SHIMS:** Delete old code. Do not deprecate.
2. **NO LEGACY:** If it's replaced, remove it.
3. **ATOMIC:** Definition change + Caller update = One Step.

## 2. ARCHITECTURE
1. **PROTOCOL-FIRST:** No concrete classes without `Protocol`.
2. **INJECTION ONLY:** No `MyClass()` inside another class. Pass it in `__init__`.
3. **NO I/O:** No database/network calls in `__init__`.

## 3. TESTING
1. **NO MOCK CHAINS:** Mock boundaries (I/O), not internals.
2. **BEHAVIOR:** Test results, not implementation details.
3. **NO REAL I/O:** Tests must run offline.

## 4. PROCESS
1. **LINT:** Your code must pass `python zen_lint.py <file>`.
2. **VERIFY:** Run `pytest` after every implementation step.
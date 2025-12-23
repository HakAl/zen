# Complexity Triage Implementation Plan

## Current Architecture (from code research)

### Models
```
MODEL_BRAIN = opus    → plan, judge, implement(escalation)
MODEL_HANDS = sonnet  → implement, verify
MODEL_EYES  = haiku   → scout, parse_tests, summary
```

### Current Flow (`core.py:1349-1389`)
```
run_lifecycle():
  1. phase_scout()   → haiku   → writes .zen/scout.md
  2. phase_plan()    → opus    → writes .zen/plan.md
  3. phase_implement() → sonnet → reads plan.md, executes steps
  4. phase_verify()  → sonnet  → runs tests, can skip with --skip-verify
  5. phase_judge()   → opus    → critiques result, can skip with --skip-judge
```

### Swarm Flow (`swarm.py:300-365`)
```
swarm_run():
  1. swarm_scout()     → haiku (once, shared)
  2. for each task:
     subprocess: zen <task> --scout-context <shared_scout>
     → runs full run_lifecycle() per task
```

### Key Files & Functions
| File | Function | Lines | Purpose |
|------|----------|-------|---------|
| `core.py` | `build_scout_prompt()` | 613-650 | Scout prompt template |
| `core.py` | `phase_scout()` | 656-675 | Runs scout phase |
| `core.py` | `phase_plan()` | 676-750 | Runs plan phase |
| `core.py` | `phase_implement()` | 879-1010 | Executes plan steps |
| `core.py` | `parse_steps()` | 764-795 | Parses `## Step N:` from plan |
| `core.py` | `run_lifecycle()` | 1349-1389 | Main orchestration |
| `swarm.py` | `execute_worker_task()` | 300-390 | Spawns `zen` subprocess |

---

## Architecture Decision: Separate `triage.py`

`core.py` is 1000+ LOC. Keep triage logic isolated in new file.

### New File: `src/zen_mode/triage.py`
```
triage.py
├── TriageResult (dataclass)
├── TRIAGE_PROMPT_SECTION (constant)
├── parse_triage(scout_output) -> TriageResult
├── generate_synthetic_plan(triage_result) -> str
└── should_fast_track(triage_result) -> bool
```

### Changes to `core.py` (minimal)
```python
# Add import
from zen_mode.triage import parse_triage, generate_synthetic_plan, TRIAGE_PROMPT_SECTION

# build_scout_prompt(): append triage section
def build_scout_prompt(...):
    return f"""..existing prompt...
{TRIAGE_PROMPT_SECTION}"""

# run_lifecycle(): add triage branch (see Phase 3 below)
```

---

## Implementation Gaps

### Gap 1: Create `triage.py` module
**New file:** `src/zen_mode/triage.py`
- `TriageResult` dataclass
- `TRIAGE_PROMPT_SECTION` constant
- `parse_triage()` parser
- `generate_synthetic_plan()` helper
- `should_fast_track()` decision function

### Gap 2: Scout prompt lacks triage output
**File:** `core.py:613-650` (`build_scout_prompt`)
**Change:** Append `TRIAGE_PROMPT_SECTION` from triage.py

### Gap 3: run_lifecycle has no fast-track branch
**File:** `core.py:1349-1389` (`run_lifecycle`)
**Change:** Add triage check after scout, branch to fast-track or standard flow

### Gap 4: Swarm auto-inherits
**No changes needed** - swarm spawns subprocess that runs `run_lifecycle`

---

## Proposed Implementation

### Phase 1: Create `src/zen_mode/triage.py`

```python
"""
Triage module for fast-track detection.
Keeps complexity logic separate from core.py.
"""
from dataclasses import dataclass
from typing import Optional
import re


@dataclass
class TriageResult:
    """Result of triage analysis."""
    fast_track: bool = False
    confidence: float = 0.0
    micro_spec: Optional[str] = None
    target_file: Optional[str] = None


# Prompt section to append to scout prompt
TRIAGE_PROMPT_SECTION = """
## Triage
After investigation, assess complexity:

<TRIAGE>
COMPLEXITY: [LOW|HIGH]
CONFIDENCE: [0.0-1.0]
FAST_TRACK: [YES|NO]
</TRIAGE>

IF FAST_TRACK=YES, provide:
<MICRO_SPEC>
TARGET_FILE: path/to/file
LINE_HINT: ~42
OPERATION: [UPDATE|INSERT|DELETE]
INSTRUCTION: Exact change (e.g., "Add // TODO at line 42")
</MICRO_SPEC>

FAST_TRACK criteria:
- 1-2 files only
- No new imports/dependencies
- Obvious solution (can describe in 2 sentences)
- Not auth/payments/infra

IMPORTANT: If unsure, output FAST_TRACK=NO.
If cannot provide precise MICRO_SPEC, set FAST_TRACK=NO.
"""


def parse_triage(scout_output: str) -> TriageResult:
    """Extract triage from scout output."""
    result = TriageResult()

    triage = re.search(r'<TRIAGE>(.*?)</TRIAGE>', scout_output, re.DOTALL)
    spec = re.search(r'<MICRO_SPEC>(.*?)</MICRO_SPEC>', scout_output, re.DOTALL)

    if triage:
        content = triage.group(1)
        if "FAST_TRACK: YES" in content:
            result.fast_track = True
            conf = re.search(r'CONFIDENCE:\s*([\d.]+)', content)
            if conf:
                result.confidence = float(conf.group(1))

    if spec:
        spec_content = spec.group(1).strip()
        result.micro_spec = spec_content
        target = re.search(r'TARGET_FILE:\s*(.+)', spec_content)
        if target:
            result.target_file = target.group(1).strip()

    # Safety guards
    if result.fast_track:
        if not result.micro_spec or len(result.micro_spec) < 10:
            result.fast_track = False

    return result


def should_fast_track(triage: TriageResult, threshold: float = 0.9) -> bool:
    """Determine if task should use fast-track path."""
    return triage.fast_track and triage.confidence >= threshold


def generate_synthetic_plan(triage: TriageResult) -> str:
    """Generate plan.md content from micro-spec."""
    # Format must match parse_steps() regex: ## Step N: description
    description = triage.micro_spec[:60] if triage.micro_spec else "Apply changes"
    return (
        "# Fast Track Plan\n"
        f"## Step 1: {description}\n"
        f"Target: {triage.target_file or 'see instructions'}\n"
        f"Instructions: {triage.micro_spec}"
    )
```

### Phase 2: Update `core.py` (minimal changes)

```python
# At top of file, add import
from zen_mode.triage import (
    parse_triage, should_fast_track, generate_synthetic_plan,
    TRIAGE_PROMPT_SECTION
)

# In build_scout_prompt(), append triage section:
def build_scout_prompt(task_file: str, output_file: str) -> str:
    return f"""<task>
Scout codebase for: {task_file}
</task>
...existing prompt...
</output>
{TRIAGE_PROMPT_SECTION}"""
```

### Phase 3: Update `run_lifecycle()` in `core.py`

```python
def run_lifecycle(task_file, ...):
    phase_scout(task_file)

    # --- TRIAGE CHECK (new) ---
    scout_output = SCOUT_FILE.read_text()
    triage = parse_triage(scout_output)

    if should_fast_track(triage):
        log(f"[TRIAGE] FAST_TRACK (confidence={triage.confidence})")

        # Generate synthetic plan
        write_file(PLAN_FILE, generate_synthetic_plan(triage))

        phase_implement()

        if not skip_verify:
            if phase_verify():
                log("[TRIAGE] Fast Track verified. Skipping Judge.")
                return  # SUCCESS
            else:
                log("[TRIAGE] Fast Track failed. Escalating to Planner...")
                # Fall through to standard path
        else:
            return  # Verify skipped
    # --- END TRIAGE ---

    # Standard path (fallback or default)
    phase_plan(task_file)
    phase_implement()
    if not skip_verify and not phase_verify():
        sys.exit(1)
    if not skip_judge:
        phase_judge()
```

### Phase 4: Swarm Integration
No changes needed - swarm spawns subprocess that runs `run_lifecycle`

---

## Cost Analysis

| Flow | Models Used | Est. Cost |
|------|-------------|-----------|
| HIGH (current) | haiku + opus + sonnet + sonnet + opus | $0.80-1.20 |
| LOW (fast-track) | haiku + sonnet + sonnet | $0.10-0.25 |
| Savings per trivial task | - | ~$0.70 |

---

## Test Plan
1. Unit test `parse_triage()` with various inputs
   - FAST_TRACK: YES with valid spec → returns fast_track=True
   - FAST_TRACK: YES with empty spec → returns fast_track=False (safety)
   - FAST_TRACK: YES with short spec (<10 chars) → returns fast_track=False
   - FAST_TRACK: NO → returns fast_track=False
   - No TRIAGE block → returns fast_track=False
2. Test fast-track flow with trivial task (add comment)
   - Run: `zen "Add a comment # TODO: Refactor to line 1 of core.py"`
   - Expected: Scout→Triage=YES→Implement→Verify→Done (no Plan, no Judge)
3. Test fallback when MICRO_SPEC missing
4. Test escalation when verify fails → should run phase_plan(), not phase_judge()
5. Integration: swarm with mixed complexity tasks

---

## Implementation Order
1. [x] Create `src/zen_mode/triage.py` (new file)
   - TriageResult dataclass
   - TRIAGE_PROMPT_SECTION constant
   - parse_triage() function
   - should_fast_track() function
   - generate_synthetic_plan() function
2. [x] Add `tests/test_triage.py` (unit tests for parser) - 43 tests passing
3. [x] Update `core.py`:
   - Add import from triage (line 24-29)
   - Append TRIAGE_PROMPT_SECTION to build_scout_prompt() (line 658)
   - Add triage branch in run() (lines 1370-1392)
4. [ ] Integration test with trivial task
5. [ ] Test swarm with mixed complexity

---
---

# RESEARCH NOTES (below)


Phase 3 (Flow Control): If phase_verify() fails during a Fast Track run, you should escalate to phase_plan(), not phase_judge().
If the low-complexity fix fails to compile/lint, the code is broken. The Judge (Opus) will simply reject it, wasting expensive tokens to tell you what the Linter already told you. The correct response to a failed Fast Track is to assume the task was actually High Complexity and needs a proper Plan.
Here is the refined implementation strategy.
1. Refined Flow Control (The Escalation Ladder)
Modify run_lifecycle to handle the failure case by falling back to the standard path.
code
Python
# core.py

def run_lifecycle(task_file, ...):
    phase_scout(task_file)
    
    # 1. READ & TRIAGE
    scout_output = SCOUT_FILE.read_text()
    triage = parse_triage(scout_output)
    
    # 2. FAST TRACK PATH
    if triage["fast_track"] and triage["confidence"] >= 0.9: # High bar for auto-pilot
        log(f"⚡ FAST_TRACK ACTIVATED: {triage['micro_spec'][:50]}...")
        
        # A. Create Synthetic Plan
        # We trick phase_implement into thinking it has a plan
        synthetic_plan = (
            "# Fast Track Implementation Plan\n"
            "## Step 1: Execute Micro-Spec\n"
            f"Target: {triage['target_file']}\n"
            f"Instruction: {triage['micro_spec']}"
        )
        write_file(PLAN_FILE, synthetic_plan)
        
        # B. Implement (Sonnet)
        phase_implement() 
        
        # C. Verify (The Gatekeeper)
        if not skip_verify:
            success = phase_verify()
            if success:
                log(" Fast Track Verified. Skipping Judge.")
                return # SUCCESS - EXIT EARLY
            else:
                log(" Fast Track Verification Failed. Escalating to Planner...")
                # DO NOT RETURN - Fall through to High Path
        else:
             # If verify skipped, we must trust the Fast Track
             return 

    # 3. HIGH COMPLEXITY PATH (Fallback or Default)
    log(" Entering Standard Planning Phase...")
    phase_plan(task_file)     # Opus generates real plan
    phase_implement()         # Sonnet implements real plan
    
    if not skip_verify:
        phase_verify()        # Verify again
        
    if not skip_judge:
        phase_judge()         # Opus judges
2. The Synthetic Plan Format
Ensure your "Synthetic Plan" matches the regex used in parse_steps() (core.py:764).
If parse_steps looks for ## Step \d+: (.*), your synthetic string must be:
code
Python
synthetic_plan = f"""
# Implementation Plan
## Step 1: Apply Micro-Spec Changes
**Context**: The user requested a simple fix that was triaged as low complexity.
**Instructions**: {triage['micro_spec']}
"""
3. Swarm Verification
Since swarm.py spawns a subprocess zen <task>, and that subprocess runs run_lifecycle, the logic above automatically works for the swarm.
Worker 1 picks up a hard task -> Scout says HIGH -> Runs full loop.
Worker 2 picks up a typo fix -> Scout says LOW -> Zips through in 10 seconds.
4. Implementation Checklist
Modify build_scout_prompt (core.py:613):
Add the <TRIAGE> and <MICRO_SPEC> definitions.
Tip: Explicitly tell Haiku: "If you are unsure, output FAST_TRACK: NO."
Add parse_triage (core.py):
Implement the regex logic.
Add a safeguard: if "FAST_TRACK: YES" in content and len(micro_spec) < 10: return False (Prevent empty specs).
Update run_lifecycle (core.py:1349):
Insert the if triage["fast_track"]: block immediately after phase_scout.
Test Case:
Run zen "Add a comment # TODO: Refactor to line 1 of core.py"
Expected: Scout finds core.py, Triage=YES, Implement adds comment, Verify passes, Process exits without "Planning" or "Judging".
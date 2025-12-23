# Zen Architecture Overview

Zen is an AI-powered autonomous development system that implements features, fixes bugs, and maintains code quality without human intervention.

## High-Level Design

```
User Task (task.md)
       ↓
┌──────────────┐
│    Scout     │ ← Haiku (fast, cheap)
│  (Analyze)   │   Maps codebase, assesses complexity
└──────┬───────┘
       ↓
┌──────────────┐
│     Plan     │ ← Sonnet (balanced)
│  (Design)    │   Creates step-by-step implementation
└──────┬───────┘
       ↓
┌──────────────┐
│  Implement   │ ← Sonnet (code generation)
│  (Execute)   │   Writes code, follows plan
└──────┬───────┘
       ↓
┌──────────────┐
│    Verify    │ ← Sonnet (test execution)
│   (Test)     │   Runs tests, validates changes
└──────┬───────┘
       ↓
┌──────────────┐
│    Judge     │ ← Opus (quality review)
│  (Review)    │   Senior architect review
└──────┬───────┘   *Skipped on Fast Track*
       ↓
    Results
```

## Core Components

### 1. Scout Phase
**Model**: Claude Haiku (fast, low-cost)
**Purpose**: Understand the task and codebase

**Outputs**:
- Codebase structure map
- Relevant files identified
- Complexity assessment (LOW/MEDIUM/HIGH)
- Fast Track recommendation

**Key Files**: `src/zen_mode/core.py::phase_scout()`

### 2. Plan Phase
**Model**: Claude Sonnet (balanced cost/quality)
**Purpose**: Design the implementation strategy

**Outputs**:
- Step-by-step implementation plan
- Files to modify
- Test strategy
- Risk assessment

**Key Files**: `src/zen_mode/core.py::phase_plan()`

### 3. Implement Phase
**Model**: Claude Sonnet
**Purpose**: Execute the plan and write code

**Features**:
- Step-by-step execution
- Context tracking
- Error recovery
- Quality checks via linter

**Key Files**: `src/zen_mode/core.py::phase_implement()`

### 4. Verify Phase
**Model**: Claude Sonnet
**Purpose**: Run tests and validate changes

**Features**:
- Multi-language test runner detection
- Intelligent test selection
- Failure analysis
- Iterative fixing (up to 5 attempts)

**Key Files**: `src/zen_mode/verify.py::phase_verify()`

### 5. Judge Phase
**Model**: Claude Opus (highest quality)
**Purpose**: Senior architect code review

**Skipped when**:
- Fast Track mode (simple changes)
- User provides `--skip-judge` flag
- No changes detected

**Review Criteria**:
- Code quality and patterns
- Security concerns
- Performance implications
- Alignment with requirements

**Key Files**: `src/zen_mode/core.py::phase_judge()`

## Quality Assurance

### Linter Integration
**File**: `src/zen_mode/linter.py`

Catches common issues:
- TODO/FIXME comments
- Debug print statements
- Hardcoded secrets
- Magic numbers
- Code smells

Runs automatically during Implement phase.

### Test Verification
**File**: `src/zen_mode/verify.py`

Supports multiple test frameworks:
- Python: pytest
- Node.js: Jest, npm test
- Java: Gradle, Maven
- C#: dotnet test
- Go: go test

### Git Integration
**File**: `src/zen_mode/utils.py`

- Tracks changed files
- Filters ignored directories (node_modules, build, etc.)
- Detects git repository state
- Handles fresh repos without HEAD

## File Organization

```
src/zen_mode/
├── core.py          # Main orchestration & phases
├── verify.py        # Test execution & verification
├── linter.py        # Code quality checks
├── utils.py         # Shared utilities (git, filtering)
├── config.py        # Configuration management
└── swarm.py         # Parallel task execution

.zen/                # Working directory (created per-run)
├── scout.md         # Scout analysis output
├── plan.md          # Implementation plan
├── log.md           # Execution log
├── test_output.txt  # Test results
├── judge_feedback.md # Judge review (if applicable)
└── backup/          # File backups
```

## Model Selection Strategy

| Phase      | Model   | Why                          |
|------------|---------|------------------------------|
| Scout      | Haiku   | Fast analysis, low cost      |
| Plan       | Sonnet  | Balanced design quality      |
| Implement  | Sonnet  | Reliable code generation     |
| Verify     | Sonnet  | Test execution & debugging   |
| Judge      | Opus    | Highest quality review       |

**Cost Optimization**: Fast Track skips Opus (most expensive) for simple changes.

## State Management

Zen maintains state in `.zen/`:
- **scout.md** - Persistent codebase analysis
- **plan.md** - Implementation steps with completion tracking
- **backup/** - File snapshots for rollback
- **log.md** - Detailed execution trace

## Error Handling

### Retry Strategy
- Max 5 attempts per phase
- Exponential backoff on API errors
- Different error messages each attempt
- Detects "stuck" state (same error 3x)

### Graceful Degradation
- Missing test runner → Skip verification with warning
- Git not available → Fall back to backup directory
- Linter errors → Non-blocking warnings

### Rollback Capability
Files are backed up before modification:
```bash
.zen/backup/src/main.py  # Original version preserved
```

## Swarm Mode

**File**: `src/zen_mode/swarm.py`

Parallel execution of multiple tasks:
- Shared Scout phase (single codebase analysis)
- Parallel Implement phases
- Conflict detection
- Status monitoring

See [swarm.md](swarm.md) for details.

## Extension Points

### Custom Linter Rules
Add rules to `src/zen_mode/linter.py::QUALITY_RULES`

### Language Support
Add test detection in `src/zen_mode/verify.py::project_has_tests()`

### Model Configuration
Override in `.zen/config.json`:
```json
{
  "model_scout": "claude-haiku-3-5",
  "model_brain": "claude-sonnet-4-5",
  "model_judge": "claude-opus-4-5"
}
```

## Performance

Typical execution times:
- **Fast Track**: 30-45 seconds
- **Normal Flow**: 60-90 seconds
- **Complex + Review**: 90-120 seconds

Costs per task:
- **Fast Track**: $0.05-0.10
- **Normal Flow**: $0.15-0.25
- **Complex + Review**: $0.25-0.40

## Security Considerations

- API keys via environment variables
- No credentials in logs
- File backups prevent data loss
- Git-ignored directories filtered
- Binary files excluded from processing

# Getting Started with Zen

Zen is an AI-powered development assistant that autonomously implements features and fixes bugs while maintaining high code quality.

## Installation

```bash
pip install zen-mode
```

## Quick Start

### 1. Create a Task File

Create a markdown file describing what you want to build:

```markdown
# feature.md

Add user authentication to the app with:
- Login form with email/password
- JWT token management
- Protected routes
```

### 2. Run Zen

```bash
zen feature.md
```

Zen will:
1. **Scout** - Understand your codebase
2. **Plan** - Create implementation steps
3. **Implement** - Write the code
4. **Verify** - Run tests
5. **Judge** - Quality review (for complex changes)

### 3. Review Results

Zen creates a `.zen/` directory with:
- `plan.md` - Implementation plan
- `log.md` - Execution log
- `test_output.txt` - Test results

## Example Workflow

```bash
# Simple feature
echo "Add a logout button to the navbar" > logout.md
zen logout.md

# Bug fix
echo "Fix the crash when user clicks submit without entering email" > fix-bug.md
zen fix-bug.md

# Multiple related changes
zen --swarm tasks.md  # Parallel execution
```

## Fast Track for Simple Changes

Zen automatically uses "Fast Track" mode for simple changes that:
- Modify ≤50 lines of code
- Don't require architectural decisions
- Have clear, unambiguous requirements

Fast Track skips the Judge phase for faster iterations.

## Configuration

Create `.env` (optional):

```
# Models for each phase
ZEN_MODEL_BRAIN=haiku      # Planning (expensive, smart)
ZEN_MODEL_HANDS=haiku      # Implementation (balanced)
ZEN_MODEL_EYES=haiku       # Summarization (cheap, fast)
```

## Next Steps

- Learn about [Linter Rules](linter-rules.md) to understand quality checks
- See [Language Support](language-support.md) for multi-language testing
- Check [Troubleshooting](troubleshooting.md) if you hit issues

## Common Use Cases

### Adding a Feature
```bash
zen feature.md
```

### Fixing a Bug
```bash
zen bugfix.md
```

### Refactoring
```bash
zen refactor.md
```

### Writing Tests
```bash
zen add-tests.md
```

## Getting Help

- See [Troubleshooting](troubleshooting.md) for common issues
- Check `.zen/log.md` for execution details
- Review test output in `.zen/test_output.txt`

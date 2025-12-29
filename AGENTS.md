# Agent Instructions

This project uses **bd** (beads) for issue tracking. Run `bd onboard` to get started.

## Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --status in_progress  # Claim work
bd close <id>         # Complete work
bd sync               # Sync with git
```

## Landing the Plane (Session Completion)

**When ending a work session**, complete all steps below.

**WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Commit changes** - All work committed to local branch
5. **Hand off** - Provide context for next session

**BATCHING FOR MANUAL TESTING:**
- Changes are committed locally but NOT pushed automatically
- User will manually test and push when ready
- This prevents broken features from reaching the remote
- Multiple sessions can batch changes before a single push

**WHEN USER REQUESTS PUSH:**
```bash
git pull --rebase
bd sync
git push
git status  # Should show "up to date with origin"
```

**CRITICAL RULES:**
- Always commit your work - uncommitted changes get lost
- Do NOT push unless user explicitly requests it
- Run tests before suggesting push readiness
- If tests fail, fix before declaring work complete


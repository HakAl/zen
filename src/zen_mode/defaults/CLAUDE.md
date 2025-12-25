## GOLDEN RULES
- **Verify, then Delete.** Confirm zero references before removing code.
- **Complete, not Stubbed.** No `pass`, `TODO`, or placeholders. Break down if complex.
- **Grep Before Change.** Changing a signature? grep -r "name" first. Update definition + all found callers in one pass.

## ARCHITECTURE
- **Inject Dependencies.** Pass config/db/clients explicitly. No `new Service()` inside logic.
- **Interface First.** Define types/shapes before implementation.
- **Pure Constructors.** I/O only in `run()`, `execute()`, `fetch()` methods.

## CODE STYLE (LLM-Friendly)
- **Flat Structure.** Max 2 directory levels. Reduces path hallucinations.
- **Fail Fast.** Specific exceptions (`UserNotFoundError`), not catch-all.
- **Top-Level Imports.** No hidden deps inside functions.
- **Semantic + Short.** `auth_flow.py` > `flow.py` > `auth_flow_handler.py`

## TESTING
- **Mock Externals.** Network/DB mocked. Tests run offline.
- **Assert Behavior.** Test outputs/state, not method calls.
- **Self-Contained.** Tests own their fixtures. No shared global state.

## PROCESS
1. **Plan**: Read files → **Grep for impact** → Define Interface → Plan Logic
2. **Implement:** Code + Tests together
3. **Verify:** Run tests
4. **Cleanup:** Delete unused (after green)
## GOLDEN RULES
- **Delete, don't deprecate.** Remove obsolete code immediately.
- **Complete, don't stub.** No placeholder implementations or "todo" skeletons.
- **Update callers atomically.** Definition changes and caller updates in one pass.

## ARCHITECTURE  
- **Inject, don't instantiate.** Pass dependencies explicitly; no hardcoded constructors.
- **Contract first.** Define interfaces before implementations.
- **Pure constructors.** No I/O, network, or DB calls during initialization.

## CODE STYLE
- **Flat, not nested.** Max 2 directory levels. Refactor before adding depth.
- **Specific, not general.** Catch explicit exceptions; no catch-all handlers.
- **Top-level imports.** No imports inside functions or methods.
- **Short names.** `process.js` not `dataProcessingHandlerManager.js`.

## TESTING
- **Mock boundaries, not internals.** Fake I/O and network; real logic.
- **Test behavior, not implementation.** Assert outcomes, not method calls.
- **Offline tests.** No real external dependencies.

## PROCESS
1. Implement the change.
2. Update all callers.
3. Delete old code.
4. Run tests.
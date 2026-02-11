---
description: Standard procedure for fixing failures atomically
---

# Fix

**Every fix follows the same procedure: diagnose, repair, verify, commit.**

## Procedure

1. **Run CI** — `just ci` (format, lint, typecheck, tests)
2. **Handle errors** — Fix all failures until CI passes
3. **Commit atomically** — Stage all changes, single commit

No partial commits. No "fix tests" commits. No multi-step recovery.

## When

- Pre-commit hook fails
- CI pipeline breaks
- Test suite regression
- Type errors surface
- Lint violations accumulate

## Pattern

```bash
just ci                # observe failures
# fix all errors
just ci                # verify clean
git add -A
git commit -m "fix(...): ..."
```

## Anti-patterns

- Committing with known failures
- Splitting fixes across multiple commits
- Skipping CI verification
- Fixing only tests without fixing code
- Fixing only code without verifying tests

## Philosophy

Broken state is transient. Clean state is committed. CI is the gate.

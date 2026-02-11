---
description: Tests break when behavior breaks, not when code changes
---

# Testing

**Tests should break when behavior breaks, not when code changes.**

If you can't break the code to fail the test, delete the test.

## Where's the enforcement?

Before writing a test, ask: what enforces this promise?

| Enforcement | Test? |
|-------------|-------|
| Type system | No |
| Schema constraint | No |
| Runtime (will crash) | No |
| Nothing | Yes |

Test the gap. Don't test what's already enforced.

## Write

- State transitions that must be blocked
- Parsing with ambiguous edge cases
- Business logic with non-obvious invariants
- Bug fixes (pin the regression)

## Delete

- Setup exceeds logic
- Survives refactors that change nothing
- Can't break the code to fail it
- Multiple tests prove same contract

## Mocking

Mock boundaries: network, time, processes. Never mock internals.


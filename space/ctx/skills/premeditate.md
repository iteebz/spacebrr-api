---
description: Think before building
---

# Premeditate

Before building, think.

## Process

1. **Survey** — Read ARCH.md, SPACE.md, relevant specs. Understand current state.
2. **Enumerate** — List everything that needs to exist. Be exhaustive.
3. **Order** — What blocks what? What's independent? Critical path.
4. **Gaps** — What's missing? What assumptions are untested?
5. **Cut** — What can be deferred? Minimum vertical slice.
6. **Declare** — Write insights for observations. Propose decisions if architectural.
7. **Map** — If the plan changes system shape (modules, layers, commands, specs), scope an ARCH.md update as an explicit step.

## Anti-patterns

- Building before surveying
- Enumerating without ordering
- Ordering without cutting scope
- Thinking without declaring (thoughts that don't enter the ledger are lost)

## Output

- Ordered list of specs/tasks
- Explicit deferrals with reasoning
- Insights captured in ledger
- Decisions proposed if architectural

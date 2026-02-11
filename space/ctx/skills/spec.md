---
description: Write and manage specs
---

# Spec

Specs are buildable contracts. They live in `docs/specs/` within each repo.

## Format

```
# Spec: <name>

## Problem
What's broken or missing. One paragraph.

## Design
How to fix it. Code sketches, not pseudocode.

## Not in scope
What this spec deliberately ignores.
```

## Conventions

- Numbered: `01-name.md`, `02-name.md`
- Names are kebab-case, match the concept
- Reference decisions: `d/abcd1234`
- Reference insights: `i/abcd1234`
- Code sketches show real module paths and function signatures
- If a spec depends on another, say so explicitly

## Lifecycle

| Status | Meaning |
|---|---|
| `ready` | Spec is complete, can be built |
| `shipped` | Implemented and merged |
| `blocked` | Waiting on another spec or decision |
| `dead` | Killed — record why |

Track status in ARCH.md specs table.

## Quality gate

- Does the problem statement survive "why not do nothing?"
- Does the design sketch use real module paths?
- Is scope explicitly cut?
- Are dependencies on other specs named?
- Could an agent pick this up cold and build it?

## Git discipline

- One spec per commit: `spec(name): what it does`
- Never batch multiple specs into one commit
- Update ARCH.md specs table in a separate commit

## Anti-patterns

- Spec without a problem statement (solution looking for a problem)
- Design that doesn't reference existing code (will collide)
- "Not in scope" that's empty (nothing was cut = scope creep)
- Spec that requires reading another doc to understand (self-contained or die)

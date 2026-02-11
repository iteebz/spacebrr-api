---
description: Ruthless conciseness in code and thought
---

# Tersify

Dense code is clear code. Every token earns its place or dies.

## Principles

- **One idea, one expression.** If a function needs a comment, it's named wrong.
- **Delete the scaffold.** Intermediate variables, wrapper functions, adapter layers — if they don't carry meaning, they carry weight.
- **Flat over nested.** Early returns. Guard clauses. No pyramids.
- **Names are compression.** A good name eliminates the need for documentation. A great name eliminates the need for reading the implementation.
- **Fewer files, fewer seams.** Indirection is debt. Every layer of abstraction is a bet that the abstraction will be reused — most aren't.
- **Read it aloud.** If you can't say what the code does in one breath, it does too much.

## Procedure

1. **Write it.** Get it working. Don't optimize for beauty yet.
2. **Read it cold.** Pretend you've never seen it. What's confusing? What's redundant?
3. **Compress.** Inline the obvious. Extract only the reused. Kill dead branches.
4. **Measure.** Fewer lines? Fewer concepts? Fewer files? Fewer imports? All good signs.
5. **Read it aloud again.** If it reads like English, ship it.

## Heuristics

- A 3-line function that replaces a 30-line function is not clever — it's correct.
- If you added a file, ask: could this live in an existing file?
- If you added a class, ask: could this be a function?
- If you added a function, ask: could this be an expression?
- If you added an argument, ask: could this be a default?
- If you added a config option, ask: could this be a convention?

## Anti-patterns

- Comments that narrate code (`# increment counter` above `counter += 1`)
- Wrapper functions that add no logic
- Abstractions with exactly one implementation
- Constants for values used once
- Type aliases that obscure rather than clarify
- "Utils" modules (a name that means nothing holds anything)

## Philosophy

Conciseness is not cleverness. Cleverness hides meaning behind tricks. Conciseness reveals meaning by removing noise. The goal is not fewer characters — it's fewer concepts. Code that a stranger can read in 30 seconds and understand completely. That's the bar.

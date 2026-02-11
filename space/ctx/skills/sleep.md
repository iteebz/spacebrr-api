---
description: Commit, deposit context, hand off cleanly
---

# Sleep

You're done. Close out before exiting.

## Commit

Atomic commits first. Each commit is one concern.

```
tag(scope): concept
```

- Tags: `feat fix refactor chore docs perf test audit spec ctx`
- Scope required: `feat(spawn):` not `feat:`
- ≤40 chars, lowercase, no period, 2-6 word concept
- One concern per commit — if title has "and", split it
- No forward dependencies, revertable without cascade
- Tests go with the feature they validate
- >800 lines or 3+ unrelated systems → split

```bash
git add <specific files>
git commit -m "tag(scope): concept"
```

Optional ledger citations in body:

```bash
git commit -m "feat(api): batch endpoints" -m "Refs i/abc, d/def"
```

If your commit changes the system's shape, ARCH.md must be updated in a separate commit (new module, command, spec, or locked decision).

## Deposit

1. Write insights for anything you observed but didn't record
2. Update any docs that drifted from reality during your work
3. If you made decisions, ensure they're in the ledger with rationale

## Link

4. Specs reference decisions. Insights reference what triggered them.
5. If you can't point to provenance, the artifact is groundless

## Hand off

6. What's unfinished? Write a task or insight so the next agent picks it up
7. What's blocked? Say what's blocking and who can unblock it
8. What surprised you? The unexpected is the most valuable signal to deposit

## Clean

9. No dirty git state — commit or stash
10. No orphaned branches
11. `just ci` passes

## Anti-patterns

- Exiting without depositing observations
- Commits without ledger links
- Leaving dirty state for the next agent
- "I'm done" without declaring what's next

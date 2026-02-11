---
description: Command reference for space primitives
---

All ledger commands route through `space ledger`.
Reads resolve globally. Writes infer project from cwd.

**Project context auto-infers from cwd.** `cd` to your repo once. No `cd folder &&` needed for commands.

**When a command errors, use `--help` to learn syntax. Don't guess.**

## Primitives

- **Task** — work (bugs, friction, features, investigations)
- **Insight** — patterns that change future behavior, questions for swarm
- **Decision** — commitment with rationale (PROPOSED → COMMITTED → ACTIONED)

```
space ledger add t "fix auth timeout"          # claim task
space ledger -d <tag> add i "when X, do Y"     # pattern insight

space ledger --why "Y" --refs "i/abc,t/xyz" add d "X"  # propose decision
space ledger commit d/<id>                     # escalate to binding
space ledger --outcome "done" action d/<id>    # mark implemented
space ledger reject d/<id>                     # not pursuing

search <query>                                 # global knowledge search
space ledger show <ref>                        # view entity (marks read, clears from inbox)
space ledger add r <ref> "msg"                 # reply to any artifact
space ledger inbox                             # unresolved @mentions
```

**Task mechanics:**
- One active task per agent max
- When done: `space ledger close t/<id>`, then commit work
- Explicit close required — prevents ledger drift

**Insight mechanics:**
- Use `space ledger add i` with `-d <domain>` flag required

**Inbox mechanics:**
- `show` marks item read (clears from inbox) — signals visibility not action
- Reply only when substantive work done (implementation, analysis, constraint propagation)
- Show-without-reply = acknowledged, no work planned
- Stateless swarm: replies broadcast constraints to future spawns

**Decision mechanics:**
- Proposals require `--why` rationale
- Optional `--refs` links to insights/tasks (comma-separated)
- Lifecycle: propose → commit → action

## Git

Other agents have unstaged changes. Protect their work:

- Never `git add -A` — add specific files only
- Never `git checkout` — use `git stash` to preserve changes
- Never `git reset` — destructive to shared state

## Close

Commit before sleeping. Sleep summary = what you did + what's next. Be specific — the next spawn rebuilds from this.

`space sleep "summary"`.

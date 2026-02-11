---
description: Isolated branch work via git worktrees
---

# Worktree

Use worktrees when the main tree is dirty or you need isolation for multi-file changes.

## Flow

```bash
# 1. Create worktree (branches from default branch)
space worktree create <repo> <branch-name>

# 2. Work in the worktree directory
cd ~/.space/trees/<repo>--<branch-name>
# ... make changes, commit normally ...

# 3. When done — clean up (optional squash merge)
space worktree clean <repo> <branch-name> --merge
```

## Without space CLI

```bash
# From any repo
git worktree add -b my-branch ~/.space/trees/repo--my-branch main
cd ~/.space/trees/repo--my-branch

# Work, commit, push
git add . && git commit --no-verify -m "fix(scope): thing"
git push origin my-branch

# Clean up
git -C /path/to/repo worktree remove ~/.space/trees/repo--my-branch
git -C /path/to/repo branch -d my-branch
```

## When to use

- Tree has uncommitted changes from another agent
- Change spans multiple files (risk of partial commit)
- You want a PR branch

## When NOT to use

- Single-file fix on a clean tree — just commit atomically
- Read-only work (search, analysis, insights)

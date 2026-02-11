---
description: Make a repo workable
---

# Setup

Bring a repo into compliance.

## Detect

- `pyproject.toml` → Python (uv, ruff, pyright, pytest)
- `package.json` → Node (pnpm, eslint, tsc)
- Neither → ask human

## Create

1. `justfile` with `ci`, `lint`, `test` recipes
2. Tooling config if missing (pyproject.toml, eslint.config.js, etc.)

## Verify

`just ci` passes before done.

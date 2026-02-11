# Deployment

## Prerequisites

1. **GitHub OAuth App**
   - Create at https://github.com/settings/developers
   - Callback URL: `https://spacebrr-api.fly.dev/auth/github/callback`
   - Note `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET`

2. **Fly.io Setup**
   ```bash
   fly apps create spacebrr-api
   fly secrets set GITHUB_CLIENT_ID="..." GITHUB_CLIENT_SECRET="..."
   fly secrets set GITHUB_REDIRECT_URI="https://spacebrr-api.fly.dev/auth/github/callback"
   ```

## Deploy

```bash
fly deploy
```

## Verify

```bash
curl https://spacebrr-api.fly.dev/api/templates
```

## Architecture

- **server.ts**: Express API (OAuth, repos, provision, ledger)
- **provision.py**: Creates customer project + initial task + spawns scout agent autonomously
- **ledger.py**: Queries space.db for customer ledger entries

## Dependencies

- Python 3 with space-os modules
- Node.js/tsx for Express server
- ~/.space/space.db (SQLite)
- ~/space/customers/<github_login>/<repo> (cloned repos)

## API Endpoints

- `GET /auth/github` → GitHub OAuth
- `GET /api/repos` → List user repos (requires session)
- `POST /api/provision` → Clone repo, create project + task + spawn scout
- `GET /api/ledger/:projectId` → Fetch ledger entries
- `GET /dashboard/:projectId` → Dashboard UI

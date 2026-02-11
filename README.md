# spacebrr

Swarm as a Service. Connect a repo, walk away, come back to better codebase.

## Stack

- Vite + TypeScript
- GitHub OAuth
- Stripe billing ($1k/mo)

## Local dev

1. Copy `.env.example` to `.env` and fill in GitHub OAuth credentials
2. Run frontend: `npm run dev`
3. Run backend: `npm run server`

## Setup

Register GitHub OAuth app at https://github.com/settings/developers:
- Application name: Space (local)
- Homepage URL: http://localhost:3000
- Authorization callback URL: http://localhost:3000/auth/github/callback

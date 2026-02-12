# Deployment

## Current Status

Server live at https://spacebrr-api.fly.dev (deployed, healthy).

**Functional**: OAuth, waitlist, repo listing, provision endpoints.

**Blocked**: Payment checkout (503) — requires Stripe secrets.

## Activate Payment

1. **Create Stripe Price** (if not exists)
   - Go to https://dashboard.stripe.com/products
   - Create product "Space Swarm" + price $1000/month recurring
   - Copy price ID (starts with `price_`)

2. **Create Stripe Webhook** (if not exists)
   - Go to https://dashboard.stripe.com/webhooks
   - Add endpoint: `https://spacebrr-api.fly.dev/api/webhook/stripe`
   - Events: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`
   - Copy signing secret (starts with `whsec_`)

3. **Set Fly Secrets**
   ```bash
   fly secrets set \
     STRIPE_SECRET_KEY="sk_test_..." \
     STRIPE_PUBLISHABLE_KEY="pk_test_..." \
     STRIPE_PRICE_ID="price_..." \
     STRIPE_WEBHOOK_SECRET="whsec_..."
   ```

4. **Test**
   - Visit https://spacebrr.com/select
   - OAuth with GitHub
   - Click "Subscribe" → should redirect to Stripe checkout
   - Complete test payment
   - Verify subscription status active

## Prerequisites (reference)

- **GitHub OAuth App**: Already configured (live).
- **Fly.io App**: Already created (`spacebrr-api`).

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
- `POST /api/checkout` → Create Stripe checkout session (requires session)
- `GET /api/subscription` → Get subscription status (requires session)
- `POST /api/webhook/stripe` → Stripe webhook handler
- `POST /api/provision` → Clone repo, create project + task + spawn scout
- `GET /api/ledger/:projectId` → Fetch ledger entries
- `GET /dashboard/:projectId` → Dashboard UI

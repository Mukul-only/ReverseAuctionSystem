# Architecture

## Shape

```
Browser (React 19 SPA)
   │  HTTPS (dev: Vite proxy / built SPA served by FastAPI)
   │  · session cookie __Host-ra_session (HttpOnly, Secure, SameSite=Lax)
   │  · X-CSRF-Token on every mutation
   │  · WebSocket /ws/auctions/{id} (same cookie + Origin)
   ▼
FastAPI (single process for the demo)
   ├── middleware: body-size limit → origin check → security headers
   ├── routers: auth · auctions · bids · admin · ws · health
   ├── services: auth · mfa · admin · auction · bid · audit
   ├── security: passwords · sessions · csrf · ratelimit · crypto · totp · challenges
   └── SQLAlchemy 2.1 → SQLite (WAL, foreign keys, append-only triggers)
```

The built SPA and the API are served from one origin in demo mode. That is
deliberate: `__Host-` cookies, `SameSite`, CSP, and CSRF behave exactly as they
would in production. In development Vite proxies `/api` and `/ws` to the
backend.

## Data model

| Table | Purpose | Integrity guard |
|---|---|---|
| `users` | account, role, TOTP state, lockout counters | role checked enum; email normalised |
| `sessions` | opaque server sessions | only SHA-256 of the token stored |
| `auctions` | requirement, price ceiling, decrement, window, status | check constraints on price/window |
| `bids` | immutable descending bids | unique `(auction_id, idempotency_key)`; no-update/delete triggers; descending-insert trigger |
| `audit_events` | append-only security log | no-update/delete triggers; HMAC chain |

### Bid ledger flow

1. Seller posts `{amount, idempotency_key}` with session + CSRF.
2. `bid_service.place` checks role, ownership, status, deadline, and the
   descending ceiling, then handles the idempotent replay path.
3. A canonical JSON payload (`auction_id`, `seller_id`, `amount`, `nonce`,
   `created_at`, `prev_hash`) is signed with HMAC-SHA256 under a per-auction
   HKDF key.
4. The row is inserted. `prev_hash` is the previous bid's signature, so the
   ledger is a hash chain.
5. The new bid is broadcast to WebSocket viewers.

Verification (`GET /api/auctions/{id}/verify`) recomputes every signature and
link in id order and reports the first invalid bid.

### Audit flow

1. Security-relevant handlers call `audit_service.record(...)`.
2. The service reads the current head hash, canonicalises the metadata, signs
   `(actor, action, entity, metadata, created_at, prev_hash)`, and appends.
3. Verification walks `seq` order, recomputing each hash and link.
4. The anchor endpoint signs `seq:hash:count` so an operator can store the head
   outside the database and later detect truncation.

Audit writes are best-effort at the edge: a failure never takes down the action
it is recording, but the ledger's own verification makes silent gaps visible.

### Authentication and MFA flow

```
register ──► session cookie + CSRF
login (no MFA) ──► session cookie + CSRF
login (MFA) ──► signed challenge (no cookie)
     └── POST /auth/mfa/login {challenge, code} ──► session cookie + CSRF
```

The challenge is a signed `itsdangerous` token with a 5-minute TTL. TOTP
secrets are AES-256-GCM encrypted at rest; verification advances
`totp_last_step` so a code cannot be replayed.

## Trust boundaries

| Boundary | What crosses it | Control |
|---|---|---|
| Browser → API | untrusted JSON, cookies, Origin | schema validation, CSRF, Origin allowlist, rate limits |
| API → database | ORM statements, signed rows | parameterised SQL, triggers, hash chains |
| Browser → WebSocket | handshake headers, socket frames | Origin allowlist, session required, read-only feed |
| Operator → admin console | admin actions | role check + enrolled TOTP + CSRF + audit |
| Process → secrets | `SECRET_KEY` | environment only, weak-value boot guard |

## Deliberate scope cuts

- No payments or file uploads — smaller attack surface, easier to secure.
- No email delivery; TOTP is shown in-app.
- In-process WebSocket hub and rate limiter: single-node only. A real
  deployment would use Redis pub/sub and a shared limiter.
- `create_all` instead of Alembic migrations: zero-setup demo. A production
  deployment would add migrations.
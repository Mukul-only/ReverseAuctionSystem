# Revauction — Reverse Auction Management System

A reverse auction platform where a **buyer** posts a requirement with a ceiling
price and a deadline, **sellers** compete by bidding downward in real time, and
the lowest valid bid at close wins.

The project is an MCA academic build with **cybersecurity as the primary
focus**: every bid is signed, every privileged action is audited, and each
control is proven by an attack test suite.

> Full design and milestone plan: [`PLAN.md`](./PLAN.md)

---

## Status

| Milestone | Scope | State |
|---|---|---|
| 1 | Scaffold — FastAPI, React SPA, Geist design system, health check | ✅ done |
| 2 | Data layer — models, SQLite WAL, append-only guards, seed data | ✅ done |
| 3 | Auth core — Argon2id, sessions, CSRF, rate limits | ✅ done |
| 4 | RBAC + ownership checks | ✅ done |
| 5 | Auction lifecycle | ✅ done |
| 6 | Signed bid ledger — descending rules, HMAC per bid, hash chain, verification | ✅ done |
| 7 | Live feed — authenticated WebSocket, origin checks, polling fallback | ✅ done |
| 8 | TOTP MFA — encrypted secrets, login challenge, admin console | ✅ done |
| 9 | Audit ledger — HMAC hash chain, verification, signed anchor | ✅ done |
| 10 | Hardening — HSTS, size limits, safe errors, header review | ✅ done |
| 11 | Attack test suite + live demo script | ✅ done |
| 12 | Documentation — security, threat model, architecture | ✅ done |

---

## Stack

- **Backend:** FastAPI 0.162 · SQLAlchemy 2.1 · SQLite (WAL) · Pydantic 2
- **Frontend:** React 19 · TypeScript · Vite · Tailwind CSS 4
- **Security:** Argon2id · opaque server sessions · CSRF tokens · TOTP (PyOTP) ·
  HMAC-SHA256 hash chains
- **Design:** Vercel Geist — see [`docs/DESIGN.md`](./docs/DESIGN.md)
- **Docs:** [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) ·
  [`docs/SECURITY.md`](./docs/SECURITY.md) (OWASP Top 10) ·
  [`docs/THREAT_MODEL.md`](./docs/THREAT_MODEL.md)

Verified on Python 3.14 and Node 26.

---

## Quick start

### 1. Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
# generate a real secret and put it in .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Seed demo data (idempotent):

```bash
.venv/bin/python -m scripts.seed
```

Demo accounts all use `DemoPass!234`:
`admin@revauction.dev`, `buyer@revauction.dev`, `seller@revauction.dev`,
`seller2@revauction.dev`.

The seed enrols the administrator's TOTP factor with the fixed demo secret
`JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP` from the report. Any authenticator app can
scan the printed `otpauth://` URI; the seed also prints the current code.

The app **refuses to boot** if `SECRET_KEY` is missing, shorter than 32
characters, or a known placeholder.

### Attack demo

With the server running, this drives real attacks and prints a pass/fail line
for each control (CSRF, origin, SQLi, XSS, IDOR, bid rules, MFA, audit chain,
forged WebSocket origin):

```bash
cd backend
.venv/bin/python -m scripts.attack_demo
# add --tamper to prove a direct database edit breaks the bid chain
```

### 2. Frontend (dev, hot reload)

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` and `/ws` to the backend, so
cookies and CSRF behave as if same-origin.

### 3. Combined mode (single origin, demo)

```bash
cd frontend && npm run build
cd ../backend && .venv/bin/uvicorn app.main:app --port 8000
```

Open <http://localhost:8000>. FastAPI serves the built SPA at `/` and the API at
`/api`; client-side routes fall back to `index.html`.

### Tests

```bash
cd backend
.venv/bin/pytest
```

---

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness probe |
| POST | `/api/auth/register` | Create a buyer/seller account and session |
| POST | `/api/auth/login` | Authenticate; returns an MFA challenge when enrolled |
| POST | `/api/auth/mfa/login` | Complete a login with a TOTP code |
| POST | `/api/auth/logout` | Revoke the session (requires CSRF) |
| GET | `/api/auth/me` | Current user + CSRF token |
| POST | `/api/auth/mfa/setup` | Begin TOTP enrolment (password re-entry) |
| POST | `/api/auth/mfa/verify` | Confirm a code and enable TOTP |
| POST | `/api/auth/mfa/disable` | Disable TOTP (password + current code) |
| GET | `/api/auctions` | List open auctions (public) |
| GET | `/api/auctions/mine` | Auctions owned by the caller |
| POST | `/api/auctions` | Create an auction (buyer + CSRF only) |
| GET | `/api/auctions/{id}` | Auction detail (public) |
| POST | `/api/auctions/{id}/close` | Close an ended auction and award the lowest bid (owner only) |
| POST | `/api/auctions/{id}/cancel` | Cancel an auction (owner or admin) |
| GET | `/api/auctions/{id}/bids` | Signed bid ledger in placement order (public) |
| POST | `/api/auctions/{id}/bids` | Place a descending bid (seller + CSRF; idempotent) |
| GET | `/api/auctions/{id}/verify` | Recompute the hash chain and report tampering |
| GET | `/api/admin/users` | List users (admin + MFA) |
| PATCH | `/api/admin/users/{id}/role` | Change a role (self/last-admin guarded) |
| POST | `/api/admin/users/{id}/unlock` | Clear a lockout |
| POST | `/api/admin/users/{id}/revoke-sessions` | Revoke every session for a user |
| GET | `/api/admin/audit` | Audit events, newest first |
| POST | `/api/admin/audit/verify` | Recompute the audit chain |
| GET | `/api/admin/audit/anchor` | Signed digest of the chain head |
| GET | `/api/admin/security-events` | Auth / MFA / admin events only |
| WS | `/ws/auctions/{id}` | Live bid/status feed (session cookie + Origin check) |
| GET | `/api/docs` | OpenAPI UI (Swagger) |

---

## Project layout

```
.
├── PLAN.md                  # full build plan
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI app + SPA serving
│   │   ├── config.py        # env settings, weak-secret guard
│   │   ├── db.py            # engine, WAL pragmas, append-only triggers
│   │   ├── realtime.py      # per-auction WebSocket hub + wire format
│   │   ├── models/          # users, sessions, auctions, bids, audit events
│   │   ├── schemas/         # Pydantic request/response models
│   │   ├── routers/         # health, auth, auctions, bids, admin, ws
│   │   ├── services/        # auth, mfa, admin, auction, bid, audit
│   │   └── security/        # passwords, sessions, CSRF, rate limiting, crypto, TOTP
│   ├── scripts/
│   │   ├── seed.py          # demo users, auctions, signed bids, admin MFA
│   │   └── attack_demo.py   # live attack demonstration for the viva
│   ├── tests/
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── components/ui/   # Button, Input, Textarea, Card, Badge, Eyebrow
│       ├── components/auction/  # cards, status badge, countdown
│       ├── hooks/           # useAuctionSocket (live feed + reconnect)
│       ├── pages/           # Landing, Login, Auctions, NewAuction, Detail,
│       │                    # AccountSecurity, Admin
│       ├── lib/             # api client, class + money/date helpers
│       └── index.css        # Geist tokens + mesh gradient
└── docs/
    ├── DESIGN.md            # adopted design system
    ├── ARCHITECTURE.md      # components, data flow, trust boundaries
    ├── SECURITY.md          # controls mapped to OWASP Top 10
    └── THREAT_MODEL.md      # assets, adversaries, mitigations, limits
```

---

## Authorization model

| Action | Buyer | Seller | Admin |
|---|---|---|---|
| List / read auctions | ✅ | ✅ | ✅ |
| Create an auction | ✅ | ❌ | ❌ |
| Close an ended auction | owner only | ❌ | ❌ |
| Cancel an open auction | owner only | ❌ | ✅ |
| Place a descending bid | ❌ | ✅ | ❌ |
| Read the bid ledger / verify chain | ✅ | ✅ | ✅ |
| Manage users, roles, sessions | ❌ | ❌ | ✅ + MFA |
| Read the audit ledger / verify chain | ❌ | ❌ | ✅ + MFA |

Every mutation also requires a session-bound CSRF token. Ownership is checked
server-side on every route, so changing an ID in the URL cannot reach another
buyer's auction (IDOR). Sellers can only bid as themselves, and an auction owner
can never bid on their own requirement even if their role changes.

**Separation of duties:** an administrator can cancel any auction, but cannot
create, bid on, close, or award one — only the owning buyer closes. Admin
routes additionally require an enrolled TOTP factor, so a stolen admin password
alone reaches nothing.

---

## Security notes for reviewers

- Secrets live only in `backend/.env` (git-ignored); `.env.example` documents
  the shape.
- Sessions use `__Host-` cookies with `HttpOnly`, `Secure`, and
  `SameSite=Lax`.
- Baseline headers are already applied: `X-Content-Type-Options`,
  `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, a strict CSP when
  the backend serves the built SPA, and HSTS whenever cookies are `Secure`.
- Oversized bodies are refused with `413` before they are read, and unhandled
  exceptions return a generic `500` without stack traces.
- The SPA fallback rejects `api/` and `ws/` prefixes and blocks path traversal
  by resolving candidates against the dist root.
- Money is stored as integer minor units — never floats.
- Auction titles and descriptions are tag-stripped on write; React escapes on
  render, so user content cannot execute script.

### Signed bid ledger (Milestone 6)

- Bids are **strictly descending**: each new amount must be at least one
  `min_decrement` below the current lowest (or the starting price for the
  first bid). A `BEFORE INSERT` SQLite trigger re-checks the ceiling so a
  race cannot slip in a non-descending bid.
- Each bid is signed with **HMAC-SHA256** under a per-auction key derived from
  `SECRET_KEY` via **HKDF-SHA256**. The signed payload is canonical JSON over
  `auction_id`, `seller_id`, `amount`, `nonce`, `created_at`, and `prev_hash`.
- `prev_hash` is the previous bid's signature, forming an append-only
  **hash chain**. `GET /api/auctions/{id}/verify` recomputes every signature
  and link; a mismatch names the first bad bid.
- `bids` rows are **immutable at the database level** (no-update / no-delete
  triggers). Verification therefore detects edits or deletions performed
  outside the application, even if an attacker disables the triggers.
- Bids are **idempotent**: `(auction_id, idempotency_key)` is unique. An
  identical retry returns `200` with the original row; reuse with a different
  amount returns `409`.
- Honest limitation: HMAC protects against database-level tampering, not a
  fully malicious server that holds the signing key. The full threat model is
  written up with the Milestone 12 documentation.

### Live feed (Milestone 7)

- `/ws/auctions/{id}` broadcasts a `snapshot` on connect, then `bid`,
  `auction`, and `presence` frames as state changes. Writes stay on the
  CSRF-protected HTTP routes; the socket is read-only plus a ping/pong
  heartbeat.
- **Origin allowlist (CSWSH defense):** browsers always send `Origin` on the
  handshake. A mismatching origin is refused before the upgrade, so a hostile
  page cannot ride a victim's session cookie. This mirrors the HTTP mutation
  policy because `BaseHTTPMiddleware` does not run for WebSockets.
- **Session required:** the handshake must carry a valid `__Host-` session
  cookie (closing with `4401` otherwise). The SPA falls back to polling when
  anonymous or disconnected.
- A per-auction viewer cap (200) bounds resource use; the hub is in-process
  and single-node by design for the demo.
- The client reconnects with exponential backoff, sends a heartbeat, and keeps
  a slow poll running as a safety net so missed frames (including deadline
  closes) are reconciled.

### Two-factor authentication (Milestone 8)

- TOTP secrets are encrypted at rest with **AES-256-GCM** under a key derived
  from `SECRET_KEY` via HKDF; the user id is bound as associated data, so a
  ciphertext copied to another account fails to decrypt.
- Enrolment is two-step: a pending secret is stored, then a live code must
  confirm it. Enabling, disabling, and enrolling all require the password
  again. Disabling also requires a current code.
- Login with MFA enabled returns a **signed, short-lived challenge** instead of
  a session. The session cookie is only issued after `/api/auth/mfa/login`
  verifies the code. Codes are single-use per 30-second step
  (`totp_last_step`), which blocks replay.
- Admin routes are blocked until the account enrols a factor
  (`require_admin_mfa`). TOTP attempts are rate-limited.
- The seed enrols the demo administrator with a fixed secret so the console is
  demonstrable; production accounts would enrol their own device.

### Audit ledger (Milestone 9)

- Logins, failed logins, registrations, MFA changes, auction
  creation/close/cancel, bids, and admin actions append to `audit_events`.
- Each event stores `prev_hash` plus an **HMAC-SHA256** over a canonical
  payload (actor, action, entity, metadata, timestamp, previous hash). Events
  are ordered by `seq`; verification recomputes every link.
- The table is append-only at the SQL level (no-update / no-delete triggers).
  Verification detects edits, inserts, deletions, and reordering even if those
  triggers are removed.
- `POST /api/admin/audit/verify` returns a report naming the first bad `seq`.
  `GET /api/admin/audit/anchor` returns a signed digest of the chain head; store
  it off-system to detect truncation of the newest events later.
- Honest limitation: like the bid ledger, this detects database tampering, not
  a fully malicious application server that holds the HMAC key.
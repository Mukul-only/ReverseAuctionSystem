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
| 6 | Signed bid ledger | ⬜ next |
| 7 | WebSocket live feed | ⬜ |
| 8 | TOTP MFA + admin dashboard | ⬜ |
| 9 | Hash-chained audit log | ⬜ |
| 10 | Hardening pass | ⬜ |
| 11 | Attack test suite + demo script | ⬜ |
| 12 | Documentation & report | ⬜ |

---

## Stack

- **Backend:** FastAPI 0.162 · SQLAlchemy 2.1 · SQLite (WAL) · Pydantic 2
- **Frontend:** React 19 · TypeScript · Vite · Tailwind CSS 4
- **Security:** Argon2id · opaque server sessions · CSRF tokens · TOTP (PyOTP) ·
  HMAC-SHA256 hash chains
- **Design:** Vercel Geist — see [`docs/DESIGN.md`](./docs/DESIGN.md)

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

The app **refuses to boot** if `SECRET_KEY` is missing, shorter than 32
characters, or a known placeholder.

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
| POST | `/api/auth/login` | Authenticate and rotate the session |
| POST | `/api/auth/logout` | Revoke the session (requires CSRF) |
| GET | `/api/auth/me` | Current user + CSRF token |
| GET | `/api/auctions` | List open auctions (public) |
| GET | `/api/auctions/mine` | Auctions owned by the caller |
| POST | `/api/auctions` | Create an auction (buyer + CSRF only) |
| GET | `/api/auctions/{id}` | Auction detail (public) |
| POST | `/api/auctions/{id}/close` | Close an ended auction (owner only) |
| POST | `/api/auctions/{id}/cancel` | Cancel an auction (owner or admin) |
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
│   │   ├── models/          # users, sessions, auctions, bids, audit events
│   │   ├── schemas/         # Pydantic request/response models
│   │   ├── routers/         # health, auth, auctions
│   │   ├── services/        # auth policy, auction lifecycle + ownership
│   │   └── security/        # Argon2id, sessions, CSRF, rate limiting, text
│   ├── scripts/seed.py      # demo users + auctions
│   ├── tests/
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── components/ui/   # Button, Input, Textarea, Card, Badge, Eyebrow
│       ├── components/auction/  # cards, status badge, countdown
│       ├── pages/           # Landing, Login, Auctions, NewAuction, Detail
│       ├── lib/             # api client, class + money/date helpers
│       └── index.css        # Geist tokens + mesh gradient
└── docs/
    └── DESIGN.md            # adopted design system
```

---

## Authorization model

| Action | Buyer | Seller | Admin |
|---|---|---|---|
| List / read auctions | ✅ | ✅ | ✅ |
| Create an auction | ✅ | ❌ | ❌ |
| Close an ended auction | owner only | ❌ | ❌ |
| Cancel an open auction | owner only | ❌ | ✅ |

Every mutation also requires a session-bound CSRF token. Ownership is checked
server-side on every route, so changing an ID in the URL cannot reach another
buyer's auction (IDOR).

---

## Security notes for reviewers

- Secrets live only in `backend/.env` (git-ignored); `.env.example` documents
  the shape.
- Sessions use `__Host-` cookies with `HttpOnly`, `Secure`, and
  `SameSite=Lax`.
- Baseline headers are already applied: `X-Content-Type-Options`,
  `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, and a strict CSP
  when the backend serves the built SPA.
- The SPA fallback rejects `api/` and `ws/` prefixes and blocks path traversal
  by resolving candidates against the dist root.
- Money is stored as integer minor units — never floats.
- Auction titles and descriptions are tag-stripped on write; React escapes on
  render, so user content cannot execute script.
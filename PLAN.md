# Reverse Auction Management System — Build Plan

A secure reverse-auction platform: a buyer posts a requirement with a ceiling price and a deadline; sellers compete by bidding **downward**; the lowest valid bid at close wins.

**Purpose:** MCA academic project / demo, with cybersecurity as the primary focus.
**Stack:** React (Vite + TypeScript) SPA · FastAPI · SQLAlchemy 2.1 · SQLite (WAL) · WebSocket.
**Design system:** Vercel "Geist" (ink-on-near-white, hairline borders, mesh gradient hero) — see [Design System](#9-design-system--vercel--geist).

---

## 1. Roles & Core Flow

| Role | Can do |
|---|---|
| Buyer | Create/manage own auctions, view bids, close & award |
| Seller | Browse open auctions, place descending bids, view own bid history |
| Admin | User management, audit log + integrity verification, security events |

**Flow:** register → login (+ TOTP for admin) → buyer creates auction → sellers bid live over WebSocket → auction auto-closes → lowest bid wins → every action hash-chained into an audit ledger.

**Deliberate scope cuts:** no payments, no file uploads, no email delivery (TOTP QR shown in-app). This keeps the attack surface small — itself part of the security story.

---

## 2. Architecture

```
React SPA (Vite + TS)  ──HTTPS/WS──▶  FastAPI
   React Router                         ├── Routers (auth, auctions, bids, admin, ws)
   Auth/CSRF client                     ├── Services (auth, auction, bid, audit)
   WebSocket hook                       ├── Security layer (argon2, sessions, csrf,
                                        │    totp, hmac-chain, ratelimit, headers)
                                        └── SQLAlchemy 2.1 ──▶ SQLite (WAL)
```

**Deployment shape for the demo:** FastAPI serves the *built* SPA at `/` and the API at `/api` — same origin. This makes `__Host-` cookies, `SameSite`, CSP, and CSRF behavior realistic. Vite dev server proxies `/api` and `/ws` during development.

**Money** is stored as **integer minor units** (paise/cents), never floats — precision and integrity.

**Toolchain verified:** FastAPI 0.162, Pydantic 2.14, SQLAlchemy 2.1, Argon2, PyOTP all install cleanly on Python 3.14 (cp314 wheels).

---

## 3. Security Design (the heart of the project)

### 3.1 Auth & session security
- **Argon2id** password hashing (tuned memory/time/parallelism), per-user salt.
- Password policy + common-password blocklist.
- **Opaque server-side sessions**, not JWT: 256-bit random token, stored **SHA-256 hashed** in DB, delivered in a `__Host-` cookie (`HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`).
- Session **rotation on login and privilege change**, idle + absolute timeouts, revocation on logout/password change.
- **TOTP MFA** (PyOTP) for admins: QR provisioning, confirm-before-enable, replay prevention via `last_used_step`, secret **encrypted at rest** (AES-GCM / Fernet key from env).
- **Account lockout** with progressive backoff after repeated failures; generic error messages; constant-time comparisons.
- Sessions-vs-JWT trade-off documented (revocation, no `alg` confusion).

### 3.2 RBAC & access control
- Roles `buyer` / `seller` / `admin`; FastAPI dependency `require_role(...)`.
- **Deny-by-default** routing with an explicit public allowlist.
- **Resource-level ownership checks** on every mutation → blocks IDOR (a seller can only bid as themselves; a buyer only manages their own auctions).
- Separation of duties: admins cannot bid; admins cannot silently edit auctions.
- Frontend route guards are UX only — **all authorization enforced server-side**.

### 3.3 Input validation & OWASP Top 10
- Pydantic v2 strict models, whitelists, length caps, `Decimal`/integer money.
- SQLAlchemy parameterized queries → SQLi defense.
- Stored-XSS defense: sanitize descriptions server-side (allowlist), plus React auto-escaping.
- **CSRF**: double-submit token bound to the session, required on all state-changing requests.
- **Security headers**: CSP with nonce (no `unsafe-inline`), HSTS, `X-Content-Type-Options`, `frame-ancestors 'none'`, `Referrer-Policy`, `Permissions-Policy`.
- **Rate limiting**: login, register, TOTP verify, bid placement (per-IP + per-account token bucket).
- CORS locked to the known origin with credentials; WebSocket **Origin validation** (CSWSH defense).
- Safe error handling (no stack traces), structured logs that never contain secrets.
- Pinned dependencies + `pip-audit` / `npm audit` in docs.

### 3.4 Audit logging & integrity
- Append-only `audit_events` table; **HMAC-SHA256 hash chain**: `hᵢ = HMAC(key, hᵢ₋₁ ‖ canonical_json(eventᵢ))`.
- SQLite triggers block `UPDATE`/`DELETE` on the table (defense in depth).
- Logged: register, login success/fail, MFA events, auction create/close/cancel, bid placed, admin actions, integrity checks.
- Admin **"Verify chain"** action recomputes the chain and reports the first broken link.
- **External anchoring** of the chain head (appended to a log file) so wholesale DB rewrites are detectable.

### 3.5 Bid integrity & crypto
- Every bid is **HMAC-signed** over a canonical payload (`auction_id, seller_id, amount, nonce, timestamp`) using a per-auction key derived via **HKDF**.
- **Per-auction hash chain** (`prev_hash`) makes the bid ledger tamper-evident; a verify endpoint detects edits/insertions/deletions.
- **Server-authoritative** amounts and timestamps — client values never trusted.
- **Idempotency keys + nonces** prevent duplicate-submit and replay.
- Honest threat-model note: server-side HMAC protects against *database* tampering, not a fully malicious server; commit/reveal sealed bids documented as future work.

### 3.6 Transport & secrets
- TLS (dev self-signed cert) + HTTPS redirect + HSTS.
- Secrets only via `.env` (with `.env.example`); **app refuses to boot** with a default/weak `SECRET_KEY`.
- TOTP secrets and sensitive fields encrypted at rest (AES-GCM envelope, master key from env).
- Session tokens hashed at rest; tokens never logged.
- Secure cookie flags including `__Host-` prefix.

---

## 4. Data Model

| Table | Key fields |
|---|---|
| `users` | id, email (unique), password_hash, role, totp_secret_enc, totp_enabled, failed_attempts, locked_until, created_at |
| `sessions` | id, user_id, token_hash, csrf_token, created_at, last_seen_at, expires_at, revoked_at, ip, user_agent |
| `auctions` | id, buyer_id, title, description, starting_price, min_decrement, currency, starts_at, ends_at, status, winner_bid_id, created_at |
| `bids` | id, auction_id, seller_id, amount, nonce, idempotency_key, prev_hash, signature, created_at |
| `audit_events` | seq, actor_id, action, entity_type, entity_id, metadata_json, prev_hash, hash, created_at |

Auction state machine: `draft → open → closed → awarded` (or `cancelled`). Unique constraints enforce one bid per idempotency key and prevent self-outbidding loops.

---

## 5. API Surface

```
POST   /api/auth/register | login | logout
GET    /api/auth/me
POST   /api/auth/mfa/setup | verify | disable
GET    /api/auctions            POST /api/auctions
GET    /api/auctions/{id}       POST /api/auctions/{id}/close | cancel
GET    /api/auctions/{id}/bids  POST /api/auctions/{id}/bids
GET    /api/auctions/{id}/verify      ← recompute bid chain
GET    /api/admin/users | /admin/audit | /admin/security-events
POST   /api/admin/audit/verify
WS     /ws/auctions/{id}        (session cookie + Origin check)
GET    /api/health
```

---

## 6. Frontend

Vite + React + TypeScript, React Router, Tailwind CSS, self-hosted Geist fonts.

Pages: **Landing/Auth**, **Auction list**, **Auction detail** (live bid feed, countdown, bid form, integrity badge), **Create auction**, **My auctions**, **MFA setup**, **Admin dashboard** (users, audit viewer with verify, security events).

A single `apiClient` injects the CSRF header and handles 401 → redirect. A `useAuctionSocket` hook consumes the WebSocket with polling fallback.

---

## 7. Repo Layout

```
Reverse_Auction_System/
├── PLAN.md
├── backend/
│   ├── app/
│   │   ├── main.py  config.py  db.py
│   │   ├── models/  schemas/  routers/
│   │   ├── security/   (passwords, sessions, csrf, totp, crypto, ratelimit, headers)
│   │   └── services/   (auth, auction, bid, audit)
│   ├── tests/          (unit, integration, security attack tests)
│   ├── scripts/seed.py  scripts/attack_demo.py
│   └── requirements.txt  .env.example
├── frontend/
│   ├── src/api/  components/  components/ui/  pages/  hooks/  lib/  styles/
│   └── index.html  vite.config.ts  package.json
├── docs/  SECURITY.md  ARCHITECTURE.md  THREAT_MODEL.md  DESIGN.md
└── README.md
```

---

## 8. Build Milestones

Each milestone is independently verifiable.

1. **Scaffold** — git init, venv, FastAPI skeleton, Vite React TS, Tailwind, Geist fonts, `/api/health` green.
2. **Data layer** — models, SQLite WAL, seed script, table creation.
3. **Auth core** — register/login/logout, Argon2, sessions, CSRF, headers, rate limit.
4. **RBAC + ownership** — role dependencies + IDOR checks + tests.
5. **Auctions** — CRUD + state machine + validation.
6. **Bidding engine** — descending rules, HMAC signing, hash chain, idempotency, verify endpoint.
7. **Live feed** — WebSocket broadcast + auth/origin checks + polling fallback.
8. **MFA + admin** — TOTP enrollment, admin users, audit viewer, security events.
9. **Audit chain** — HMAC chaining, append-only triggers, verify + external anchor.
10. **Hardening pass** — CSP/HSTS/CORS, safe errors, TLS dev certs, secret-boot check.
11. **Tests & demo** — pytest suite incl. SQLi/XSS/CSRF/IDOR/rate-limit/tamper/replay attacks; `attack_demo.py` for the viva.
12. **Docs** — README, SECURITY.md mapping to OWASP Top 10, threat model, demo script.

---

## 9. Design System — Vercel / Geist

Source spec: `/home/mukul/Downloads/vercel.md` (adopted as-is, with the caveat that line 60 of that file contains a stray injected string inside the `label-sm` weight token; `label-sm` is treated as **weight 500**).

The Geist system is monochrome ink-on-near-white with hairline borders and mono eyebrows. It is **CSP-friendly**: no CSS-in-JS, no external fonts, CSS gradient instead of raster images.

### 9.1 Token layer

`frontend/src/styles/tokens.css` is the single source of truth, wired into Tailwind v4 via `@theme`.

```css
:root {
  /* surface + ink duet */
  --canvas: #fafafa;        --elevated: #ffffff;
  --ink: #171717;           --body: #4d4d4d;
  --mute: #8f8f8f;          --faint: #a1a1a1;
  --hairline: #ebebeb;      --hairline-soft: #f2f2f2;
  --primary: #171717;       --on-primary: #ffffff;

  /* accents — used sparingly */
  --link: #0070f3;          --link-deep: #0761d1;   --link-soft: #d3e5ff;
  --error: #ee0000;         --error-deep: #c50000;
  --warning: #f5a623;       --warning-soft: #ffefcf; --warning-deep: #ab570a;
  --violet: #7928ca;        --cyan: #50e3c2;  --pink: #ff0080;  --magenta: #eb367f;

  /* mesh stops */
  --g-develop-a: #007cf0;   --g-develop-b: #00dfd8;
  --g-preview-a: #7928ca;   --g-preview-b: #ff0080;
  --g-ship-a: #ff4d4d;      --g-ship-b: #f9cb28;

  /* radii */
  --r-sm: 6px;  --r-md: 12px;  --r-lg: 16px;
  --r-pill-cat: 64px;  --r-pill: 100px;

  /* spacing: 4 8 12 16 24 32 40 64 96 128 */
  /* shadows: level-1 whisper, level-2 floating stack */
}
```

**Typography** — Geist Sans + Geist Mono, self-hosted via `@fontsource-variable/geist` and `@fontsource-variable/geist-mono` (v5.3.0). Self-hosting keeps `font-src 'self'` strict and leaks nothing to a font CDN.

| Utility | Spec |
|---|---|
| `.display-xl` | 48/48, 600, −2.4px |
| `.heading-lg` | 32/40, 600, −1.28px |
| `.heading-md` | 20/28, 600, −0.4px |
| `.label-sm` | 14/20, 500, −0.28px |
| `.eyebrow` | Geist Mono 12/16, 500, uppercase |
| `.body-lg / md / sm` | 16/24 · 14/20 · 12/16, 400 |
| `.btn-lg / md` | 16/20 · 14/20, 500 |
| `.code` | Geist Mono 14/20, 400 |

### 9.2 Component mapping

| Design token | Where it lands in the app |
|---|---|
| `nav-bar` | Sticky app header: ink wordmark `REVAUCTION`, mono role chip, ghost-sm user menu, hairline bottom |
| `button-primary` (black **pill**) | **Only** landing hero + auth CTA — the "marketing surface" |
| `button-primary-sm` / `button-ghost-sm` (6px square) | **All** in-app actions: Place Bid, Close Auction, Verify Chain, Logout — shape-by-context rule |
| `text-input` | All forms: 6px radius, hairline, blue focus ring |
| `feature-card` | Auction cards, stat tiles, security panels |
| `pricing-card` | Create-auction form panel, MFA setup panel |
| `code-block` | Bid hash/signature rows, audit entries, TOTP secret, API docs |
| `button-category-pill` | Admin tabs (Users / Audit / Security) and auction filters |
| `button-icon-circular` | Copy-hash, refresh, close-modal |
| `hero-band` + mesh gradient | Landing + login page only |
| Level-2 shadow | Modals, dropdowns, toasts only |

**Color policy:** chrome stays ink/grey. Color appears only in (a) the hero mesh, (b) a small status dot, (c) links/focus. Status is conveyed by **label + dot**, never color alone.

### 9.3 Page designs

1. **Landing / Auth** — split layout. Left: mesh gradient bloom, `.eyebrow` "REVERSE AUCTION PROTOCOL", `.display-xl` "The lowest bid wins." plus a black pill CTA. Right: white `pricing-card` with the login/register form in 6px inputs.
2. **Auction list** — `.eyebrow` "OPEN AUCTIONS", `.heading-lg` title, 3-up `feature-card` grid. Card: title, current low in mono, mono countdown, bid count, status dot.
3. **Auction detail** — two columns. Left: bid ledger as a hairline table with mono amounts and truncated signatures. Right: sticky bid panel (amount input, min-decrement hint, live pulse dot) + countdown + "verify integrity" link.
4. **Create auction** — `pricing-card` panel, 2-column field grid, black square submit, inline validation in `--error`.
5. **Admin** — category-pill tabs; users table; audit table with mono hash chain, copy buttons, and a **Verify chain** action rendering a pass/fail banner.
6. **MFA setup** — QR rendered **locally** (`qrcode` lib) so the TOTP secret never touches a third-party QR service. Secret in a `code-block`, confirm-code input, enable button.

### 9.4 Security ↔ design guardrails

- **No CSS-in-JS.** Tailwind + CSS variables compile to a static stylesheet → CSP stays `style-src 'self' 'nonce-...'` with no `unsafe-inline`.
- **No external assets.** Fonts self-hosted, gradient is CSS, icons inline SVG → tight `img-src`/`font-src`/`connect-src`.
- **Contrast audit:** `body` (#4d4d4d) on canvas ≈ 7.5:1 PASS; `mute` (#8f8f8f) ≈ 3.1:1 → captions/metadata only; `faint` → placeholders/disabled only.
- **Reduced motion** respected by countdown pulse and hover transitions.
- No dark mode — the system defines none.

---

## 10. Testing & Demo Story

- **pytest + httpx** integration tests for every route.
- **Security attack suite** proving defenses: SQLi payloads, stored-XSS payloads, CSRF-less rejection, cross-role/IDOR attempts, rate-limit lockout, bid tamper detection, replayed idempotency key, forged WebSocket origin.
- **`attack_demo.py`** — scripted walkthrough firing each attack and printing `BLOCKED` with the reason. Ideal for viva/report appendix.

---

## 11. Assumptions

- SQLite is fine for a demo (WAL mode; concurrency limit noted in docs).
- Sessions over JWT (better revocation); rationale documented.
- Admin TOTP is mandatory to demonstrate MFA end-to-end.
- No email service — TOTP QR shown in-app.
- Single-machine; Docker optional.
- Light theme only (per Geist spec).
# Security controls (OWASP Top 10:2021)

Each row names the control, where it lives, and the test or demo that proves
it. `pytest` runs the tests; `python -m scripts.attack_demo` exercises a live
server.

## A01 — Broken access control

- Deny-by-default role dependencies (`require_roles`) and an admin-MFA gate
  (`require_admin_mfa`) in `app/dependencies.py`.
- Ownership checks in `auction_service.close/cancel` and
  `bid_service.place`; an owner can never bid on their own requirement.
- Admin separation of duties: admins cancel auctions but cannot create, bid,
  close, or award them.
- The SPA guard in `Admin.tsx` is cosmetic; the server is authoritative.

**Proof:** `tests/test_hardening.py::test_another_buyer_cannot_close_an_auction`,
`test_admin.py`, `test_bids.py`.

## A02 — Cryptographic failures

- Argon2id password hashing (64 MiB, t=3, p=4) with transparent rehash.
- Opaque 256-bit session tokens; only SHA-256 hashes are stored.
- TOTP secrets encrypted with AES-256-GCM under an HKDF-derived key, with the
  user id as associated data.
- Bids and audit events signed with HMAC-SHA256 under domain-separated HKDF
  keys.
- Secrets come from the environment; boot fails on a missing/weak `SECRET_KEY`.

**Proof:** `tests/test_crypto.py`, `test_mfa.py::test_secret_is_encrypted_at_rest`,
`test_audit.py`, `test_bids.py` tamper tests.

## A03 — Injection

- SQLAlchemy parameterised queries throughout; no string-built SQL.
- Pydantic models with `extra="forbid"`, bounded lengths, and validators.
- Tags and control characters stripped from free text; React escapes on render.
- Auction and bid numeric bounds prevent overflow/abuse.

**Proof:** `test_hardening.py::test_sql_injection_in_login_does_not_authenticate`,
`test_sql_injection_in_email_is_rejected`, `test_stored_xss_is_stripped`.

## A04 — Insecure design

- Re-authentication (password) before MFA enrolment or disable.
- One-time TOTP steps (`totp_last_step`) block replay.
- Idempotency keys prevent double bids after a retry.
- Descending-bid rule is enforced in the service *and* by a DB trigger.
- Admin MFA is mandatory, not optional.

## A05 — Security misconfiguration

- Security headers: `nosniff`, `DENY`, referrer policy, permissions policy,
  strict CSP, HSTS when cookies are `Secure`.
- `DEBUG=false` by default; unhandled errors return a generic `500`.
- Request bodies over 1 MB refused before reading.
- Explicit CORS and Origin allowlists; no wildcard credentials.

**Proof:** `test_hardening.py::test_security_headers_are_present`,
`test_oversized_body_is_refused`.

## A06 — Vulnerable and outdated components

- Pinned versions in `backend/requirements.txt` and `frontend/package-lock.json`.
- Minimal dependency set; `cryptography`, `PyOTP`, and `itsdangerous` are the
  only crypto-adjacent additions.
- Reviewer step: `pip list --outdated` / `npm audit` before submission.

## A07 — Identification and authentication failures

- Argon2id, generic login errors, constant-time-ish unknown-email handling.
- Lockout after repeated failures and per-IP/per-account sliding windows.
- Session rotation on login; idle and absolute expiry; server-side revocation.
- CSRF synchroniser token bound to the session.
- TOTP with a signed login challenge and replay guard.

**Proof:** `test_auth.py`, `test_mfa.py`, `test_hardening.py` rate-limit test.

## A08 — Software and data integrity failures

- Bid hash chain with per-auction keys; audit hash chain with a signed anchor.
- Append-only database triggers on both ledgers.
- Tamper tests drop the triggers, mutate/delete rows, and assert detection.

**Proof:** `test_bids.py` tamper tests, `test_audit.py` tamper/removal tests,
`scripts.attack_demo --tamper`.

## A09 — Security logging and monitoring failures

- `audit_events` records logins, failures, MFA, bids, auction lifecycle, and
  admin actions.
- Security-event view filters auth/MFA/admin activity for the console.
- The anchor supports off-system retention and truncation detection.
- Server logs never include passwords, tokens, or TOTP secrets.

## A10 — Server-side request forgery

- The application makes no outbound HTTP requests, so SSRF has no surface.
- WebSocket and HTTP origins are allowlisted; no user-supplied URLs are fetched.

---

## Transport and deployment notes

- Demo cookie flags require HTTPS. Over plain HTTP, pass the cookie manually in
  smoke scripts (as the tests do) or terminate TLS in front of uvicorn.
- HSTS is emitted only when `COOKIE_SECURE=true`.
- For a real deployment: TLS termination, Redis-backed sessions/limits, a
  process manager, and Alembic migrations.

## Known limitations (honest scope)

- HMAC protects against **database-level** tampering. A fully malicious
  application server that holds `SECRET_KEY` can re-sign rows. Mitigating that
  needs an external signer or transparency log.
- In-memory rate limiting and sessions are per-process. Multi-worker
  deployments need shared storage.
- No account-recovery flow, so there is no recovery-abuse surface to test.
- TOTP is the only second factor (no WebAuthn/passkeys).
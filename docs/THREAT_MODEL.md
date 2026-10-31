# Threat model

A lightweight, STRIDE-oriented threat model for the reverse auction system. It
names what we protect, who we protect it from, where the trust boundaries are,
and which control addresses each threat — plus what we explicitly do *not*
defend against.

Scope: the FastAPI API, the React SPA it serves, the SQLite store, and the
WebSocket feed. It is an academic single-node deployment; enterprise hardening
notes are called out where they would differ.

---

## 1. Assets

| Asset | Why it matters | Where it lives |
|---|---|---|
| Account credentials | Full account takeover if leaked | `users.password_hash` (Argon2id) |
| Session tokens | Impersonation for the session lifetime | `__Host-ra_session` cookie; SHA-256 in `sessions` |
| TOTP secrets | Defeats the second factor if leaked | `users.totp_secret_enc` (AES-256-GCM) |
| Bid ledger | Determines the winner and the price paid | `bids` (+ signatures) |
| Audit ledger | Non-repudiation of security actions | `audit_events` (+ HMAC chain) |
| `SECRET_KEY` | Derives every signing/encryption key | Environment only |
| Auction integrity | Fairness, correct winner | `auctions`, `bids` |
| Availability | Live bidding must stay up | Process + SQLite |

## 2. Actors

| Actor | Capability | Trust |
|---|---|---|
| Anonymous visitor | Read auctions and ledgers, register | Untrusted |
| Buyer | Create/close/cancel own auctions | Authenticated, partially trusted |
| Seller | Place descending bids | Authenticated, partially trusted |
| Administrator | Manage users, cancel auctions, read audit | Privileged; **must** enrol TOTP |
| Database attacker | Direct edit/insert/delete on `data/app.db` | Untrusted; assumed possible |
| Network attacker | Observe/modify traffic, forge Origins | Untrusted |
| Malicious operator | Holds `SECRET_KEY` and the server | **Out of scope** (see §7) |

## 3. Trust boundaries

```
   untrusted network
        │
   ┌────▼─────────────────────────────┐
   │ Browser / attacker-controlled JS │
   └────┬─────────────────────────────┘
        │  B1: HTTP + WebSocket  (cookies, JSON, Origin)
   ┌────▼─────────────────────────────┐
   │ FastAPI process                  │
   │  middleware → routers → services │
   └────┬─────────────────────────────┘
        │  B2: SQLAlchemy → SQLite
   ┌────▼─────────────────────────────┐
   │ SQLite file (data/app.db)        │
   └──────────────────────────────────┘
        ▲
        │  B3: operator / backup / disk access
   ┌────┴─────────────────────────────┐
   │ Secrets env + admin console      │
   └──────────────────────────────────┘
```

- **B1 (network):** everything arriving is untrusted — bodies, headers,
  cookies, `Origin`, and WebSocket frames.
- **B2 (data store):** the application trusts its own ORM statements, not the
  raw rows; signed ledgers make post-hoc edits detectable.
- **B3 (operator):** the console is privileged, so it is gated by role **and**
  an enrolled TOTP factor, and every action is audited.

---

## 4. STRIDE analysis

### Spoofing an identity

| # | Threat | Control | Proof |
|---|---|---|---|
| S1 | Credential stuffing / password brute force | Argon2id, generic errors, per-IP + per-account sliding windows, account lockout | `test_auth.py`, `test_hardening.py::test_login_attempts_are_rate_limited` |
| S2 | Session-token theft via XSS | HttpOnly cookie; `__Host-` prefix; session bound to CSRF; CSP blocks inline script | `test_auth.py`, `test_hardening.py::test_security_headers_are_present` |
| S3 | Session fixation | Session rotated on login; prior session revoked (`_establish`) | `test_auth.py` |
| S4 | Forged MFA challenge | Challenge is a signed `itsdangerous` token with a 5-minute TTL | `test_mfa.py::test_mfa_login_rejects_a_forged_challenge` |
| S5 | Cross-site login CSRF | `Origin` allowlist middleware applies to unauthenticated mutations too | `test_hardening.py::test_login_csrf_is_guarded_by_origin` |

### Tampering with data

| # | Threat | Control | Proof |
|---|---|---|---|
| T1 | Edit a bid to win | Per-auction HMAC-SHA256 signature over canonical payload | `test_bids.py` tamper tests |
| T2 | Delete or reorder bids | `prev_hash` chain; verification walks id order | `test_bids.py::test_verify_detects_...` |
| T3 | Forge a cheaper bid | Server computes `seller_id` from the session, not the body; signature is server-side | `test_bids.py::test_idempotency_keys_are_scoped_to_the_bidder` |
| T4 | Edit/delete audit events | HMAC chain + append-only triggers; anchor detects truncation | `test_audit.py` tamper/removal/anchor tests |
| T5 | Undersell the decrement / raise a price | Descending ceiling enforced in the service **and** by a DB trigger | `test_bids.py`, `attack_demo` ("bid above the descending ceiling is rejected") |
| T6 | Double-bid via retry | `(auction_id, idempotency_key)` uniqueness; replay returns the original | `test_bids.py::test_replaying_a_key_returns_the_original_bid` |
| T7 | Cross-tenant mutation (IDOR) | Ownership resolved server-side from the session on every route | `test_hardening.py::test_another_buyer_cannot_close_an_auction` |

### Repudiation

| # | Threat | Control | Proof |
|---|---|---|---|
| R1 | "I never placed that bid" | Signed, chained bid rows with actor id and timestamp | `test_bids.py` |
| R2 | "I never disabled MFA / changed that role" | Every security action appended to the signed audit chain | `test_audit.py::test_core_actions_are_recorded`, `test_admin.py::test_change_role` |
| R3 | Operator rewrites history | Off-system signed anchor (`seq:hash:count`) detects truncation | `test_audit.py::test_anchor_signs_the_head` |

### Information disclosure

| # | Threat | Control | Proof |
|---|---|---|---|
| I1 | DB dump yields usable sessions | Only SHA-256 hashes of tokens are stored | `test_models.py` / `sessions.py` |
| I2 | DB dump yields TOTP secrets | AES-256-GCM at rest, HKDF key, user id as AAD | `test_mfa.py::test_secret_is_encrypted_at_rest` |
| I3 | Error messages leak internals | Generic `500`, generic login errors, no stack traces | `main.py` handler; `test_hardening.py` |
| I4 | User enumeration on register/login | Generic conflict / invalid-credentials responses | `test_auth.py` |
| I5 | Secrets in logs | Passwords/tokens/TOTP codes are never logged | code review; `SECURITY.md` §A09 |

### Denial of service

| # | Threat | Control | Proof |
|---|---|---|---|
| D1 | Huge request body exhausts memory | `Content-Length` checked first; `413` over `max_request_bytes` | `test_hardening.py::test_oversized_body_is_refused` |
| D2 | Login flood | IP + account sliding windows, `429` with `Retry-After` | `test_hardening.py` |
| D3 | Bid flood | Per-account bid limiter | `test_bids.py` |
| D4 | WebSocket connection flood / broadcast amplification | 200-viewer cap per auction; hub drops slow/full sockets | `test_ws.py` |
| D5 | Expensive TOTP guessing | MFA limiter per IP and per user | `test_mfa.py` |

### Elevation of privilege

| # | Threat | Control | Proof |
|---|---|---|---|
| E1 | Seller hits buyer/admin routes | Deny-by-default `require_roles` | `test_hardening.py::test_a_buyer_cannot_bid`, `test_admin.py` |
| E2 | Admin console without a second factor | `require_admin_mfa` blocks the whole router until TOTP is enrolled | `test_mfa.py::test_admin_routes_require_enrolled_mfa` |
| E3 | Admin awards or closes an auction | Separation of duties in `auction_service`; admins may only cancel | `test_auctions.py`, README authorization table |
| E4 | Stolen session enrols attacker's authenticator | Enrolment requires the account password; disable requires password **and** code | `test_mfa.py::test_setup_requires_the_correct_password` |
| E5 | CSRF-driven privilege change | Session-bound synchroniser token on every mutation; `Origin` allowlist | `test_hardening.py::test_mutation_without_csrf_is_rejected` |
| E6 | Self-demotion / last-admin loss | Guarded in `admin_service.change_role` | `test_admin.py::test_last_admin_cannot_be_demoted` |

---

## 5. Attack-surface inventory

| Surface | Entry point | Guard |
|---|---|---|
| JSON API | `/api/*` | Pydantic validation, session, CSRF, roles, rate limits |
| WebSocket | `/ws/auctions/{id}` | `Origin` allowlist + session cookie; feed is read-only |
| Static SPA | `/{full_path}` | Path traversal blocked; `api/`/`ws/` prefixes excluded |
| SQLite file | local disk | Append-only triggers + signed ledgers |
| Admin console | `/api/admin/*` | role + enrolled TOTP + CSRF + audit |

## 6. Attack-run evidence

`backend/scripts/attack_demo.py` drives a live server through the concrete
attacks above and prints one PASS/FAIL line per control — CSRF, foreign
`Origin`, SQL injection, stored XSS, IDOR, the descending rule, idempotency,
bid-chain integrity, MFA, admin authorization, the audit chain and anchor, a
forged WebSocket `Origin`, and (with `--tamper`) a direct database edit that
the bid chain detects. `backend/tests/` (145 tests) provides the same coverage
deterministically.

## 7. Out of scope / residual risk

| Risk | Why it remains | Mitigation path |
|---|---|---|
| Malicious server / operator with `SECRET_KEY` | HMAC keys are derived in-process, so a trusted-but-malicious server can re-sign rows | External signer, HSM, or an append-only transparency log |
| Compromised host / disk | Attacker with the DB file and the key can rewrite history | OS-level integrity, encrypted volumes, remote log shipping |
| Multi-worker deployment | In-memory sessions and rate limits are per-process | Redis-backed sessions and a shared limiter |
| Payment settlement and delivery | No money movement or fulfilment in scope | Separate, audited settlement service |
| Client-side malware | A keylogger or malicious extension defeats passwords and TOTP | Hardware keys / WebAuthn, device posture |
| Phishing and social engineering | Realistic MFA-code relay is not blocked | Phishing-resistant WebAuthn, user training |
| Repudiation of the operator's own OS actions | The app cannot attest to host-level events | External SIEM / audit collection |

## 8. Assumptions

- `SECRET_KEY` is high-entropy, unique per environment, and never committed
  (boot refuses weak or placeholder values).
- The demo runs over HTTPS in the intended deployment, so `Secure` cookies and
  HSTS are meaningful. Over plain-HTTP dev, smoke scripts pass the cookie
  manually.
- Clock drift on the authenticator stays within one 30-second step; larger
  drift is a usability failure, not a security one.
- SQLite triggers are intact during normal operation. If an attacker removes
  them, the hash chains — not the triggers — are what detect the edit.

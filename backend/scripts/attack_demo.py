"""End-to-end security demonstration against a running server.

Run from ``backend/`` after seeding and starting uvicorn::

    .venv/bin/python -m scripts.attack_demo
    .venv/bin/python -m scripts.attack_demo --tamper

Each check prints PASS/FAIL and the process exits non-zero if anything fails.
The default run is HTTP/WebSocket only. ``--tamper`` additionally proves that
the signed bid ledger detects a direct database edit (it restores the row and
the triggers afterwards).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import time
import uuid
from dataclasses import dataclass

import httpx
import pyotp
import websockets
from websockets.exceptions import InvalidStatus

BASE = os.getenv("RA_BASE_URL", "http://127.0.0.1:8000")
ORIGIN = os.getenv("RA_ORIGIN", "http://localhost:5173")
PASSWORD = "DemoPass!234"
COOKIE = "__Host-ra_session"
ADMIN_SECRET = os.getenv(
    "RA_ADMIN_TOTP_SECRET", "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
)

PASSED = 0
FAILED = 0


def check(name: str, expected, actual) -> None:
    global PASSED, FAILED
    ok = expected == actual
    print(f"{'PASS' if ok else 'FAIL'}  {name:<58} {actual!r}")
    if ok:
        PASSED += 1
    else:
        FAILED += 1
        print(f"      expected {expected!r}")


@dataclass
class Session:
    token: str
    csrf: str


http = httpx.Client(timeout=15)


def _token_from(response: httpx.Response) -> str:
    raw = response.headers.get("set-cookie", "")
    return raw.split(f"{COOKIE}=", 1)[1].split(";", 1)[0]


def login(email: str) -> Session | None:
    response = http.post(
        f"{BASE}/api/auth/login",
        json={"email": email, "password": PASSWORD},
        headers={"Origin": ORIGIN},
    )
    if response.status_code != 200:
        return None
    body = response.json()
    if body.get("mfa_required"):
        return None  # caller must use admin_login
    return Session(_token_from(response), body["csrf_token"])


def complete_mfa(challenge: str, email: str) -> Session | None:
    """Submit a TOTP code, waiting one window if the code was just used."""
    for attempt in range(2):
        code = pyotp.TOTP(ADMIN_SECRET).now()
        response = http.post(
            f"{BASE}/api/auth/mfa/login",
            json={"challenge": challenge, "code": code},
            headers={"Origin": ORIGIN},
        )
        if response.status_code == 200 and response.json().get("user", {}).get("email") == email:
            return Session(_token_from(response), response.json()["csrf_token"])
        if attempt == 0 and response.status_code == 401:
            # Replay guard: wait for the next 30-second window.
            time.sleep(max(1, 30 - int(time.time()) % 30))
    return None


def admin_login() -> Session | None:
    response = http.post(
        f"{BASE}/api/auth/login",
        json={"email": "admin@revauction.dev", "password": PASSWORD},
        headers={"Origin": ORIGIN},
    )
    if response.status_code != 200:
        return None
    body = response.json()
    if not body.get("mfa_required"):
        print("      (admin has no second factor enrolled; run the seed)")
        return Session(_token_from(response), body["csrf_token"])
    return complete_mfa(body["challenge"], "admin@revauction.dev")


def call(
    method: str,
    path: str,
    session: Session | None = None,
    *,
    csrf: bool = True,
    origin: str | None = ORIGIN,
    json_body: object | None = None,
) -> httpx.Response:
    headers: dict[str, str] = {}
    if session:
        headers["Cookie"] = f"{COOKIE}={session.token}"
        if csrf:
            headers["X-CSRF-Token"] = session.csrf
    if origin:
        headers["Origin"] = origin
    return http.request(
        method, f"{BASE}{path}", headers=headers, json=json_body
    )


def create_auction(session: Session, title: str) -> int:
    response = call(
        "POST",
        "/api/auctions",
        session,
        json_body={
            "title": title,
            "description": "attack demo",
            "starting_price": 1_000_000,
            "min_decrement": 5_000,
            "duration_hours": 2,
        },
    )
    return response.json()["id"]


def place_bid(session: Session, auction_id: int, amount: int, key: str) -> httpx.Response:
    return call(
        "POST",
        f"/api/auctions/{auction_id}/bids",
        session,
        json_body={"amount": amount, "idempotency_key": key},
    )


# --------------------------------------------------------------------------
# HTTP checks
# --------------------------------------------------------------------------


def run_http_checks() -> int | None:
    health = http.get(f"{BASE}/api/health")
    check("server health", 200, health.status_code)

    buyer = login("buyer@revauction.dev")
    seller = login("seller@revauction.dev")
    admin = admin_login()
    check("buyer + seller login", (True, True), (buyer is not None, seller is not None))
    check("admin login requires and passes MFA", True, admin is not None)
    if buyer is None or seller is None or admin is None:
        print("Cannot continue without the seeded demo accounts.")
        return None

    # --- CSRF and origin ---------------------------------------------------
    no_token = httpx.post(
        f"{BASE}/api/auctions",
        json={"title": "no csrf", "starting_price": 1000, "min_decrement": 10},
        headers={"Cookie": f"{COOKIE}={buyer.token}", "Origin": ORIGIN},
    )
    check("mutation without CSRF is blocked", 403, no_token.status_code)

    foreign = call(
        "POST",
        "/api/auctions",
        buyer,
        origin="https://evil.example",
        json_body={
            "title": "csrf",
            "starting_price": 1000,
            "min_decrement": 10,
        },
    )
    check("mutation from a foreign origin is blocked", 403, foreign.status_code)

    # --- Injection and XSS -------------------------------------------------
    sqli = http.post(
        f"{BASE}/api/auth/login",
        json={"email": "buyer@revauction.dev", "password": "' OR '1'='1' --"},
        headers={"Origin": ORIGIN},
    )
    check("SQL injection cannot log in", 401, sqli.status_code)

    xss = call(
        "POST",
        "/api/auctions",
        buyer,
        json_body={
            "title": "<script>alert(1)</script>Injection demo",
            "description": "<img src=x onerror=alert(1)>",
            "starting_price": 100_000,
            "min_decrement": 1_000,
            "duration_hours": 1,
        },
    )
    check(
        "stored XSS is stripped before persistence",
        True,
        xss.status_code == 201 and "<script>" not in xss.json()["title"],
    )
    if xss.status_code == 201:
        call("POST", f"/api/auctions/{xss.json()['id']}/cancel", buyer)

    # --- IDOR --------------------------------------------------------------
    auction_id = create_auction(buyer, f"Attack demo {uuid.uuid4().hex[:8]}")
    other = login("seller@revauction.dev")
    if other is None:  # pragma: no cover - seeded account
        return auction_id
    idor = call("POST", f"/api/auctions/{auction_id}/cancel", other)
    check("a non-owner cannot cancel (IDOR blocked)", 403, idor.status_code)

    # --- Bid integrity -----------------------------------------------------
    too_high = place_bid(seller, auction_id, 1_000_000, f"demo-high-{uuid.uuid4()}")
    check("bid above the descending ceiling is rejected", 409, too_high.status_code)

    key = f"demo-{uuid.uuid4()}"
    first = place_bid(seller, auction_id, 995_000, key)
    check("a valid descending bid is accepted", 201, first.status_code)
    replay = place_bid(seller, auction_id, 995_000, key)
    check("idempotent replay returns the same row", 200, replay.status_code)
    check("replay does not create a second bid", True, replay.json()["id"] == first.json()["id"])

    chain = call("GET", f"/api/auctions/{auction_id}/verify", seller)
    check("bid chain verifies", True, chain.json()["valid"])

    # --- Admin surface -----------------------------------------------------
    users = call("GET", "/api/admin/users", admin)
    check("admin console reachable with MFA", 200, users.status_code)
    anonymous_admin = call("GET", "/api/admin/users")
    check("anonymous admin access is refused", 401, anonymous_admin.status_code)
    seller_admin = call("GET", "/api/admin/users", seller)
    check("seller admin access is refused", 403, seller_admin.status_code)

    verify = call("POST", "/api/admin/audit/verify", admin)
    check("audit chain verifies", True, verify.json()["valid"])
    anchor = call("GET", "/api/admin/audit/anchor", admin)
    check("audit anchor is signed", True, bool(anchor.json()["signature"]))

    return auction_id


# --------------------------------------------------------------------------
# WebSocket checks
# --------------------------------------------------------------------------


async def run_ws_checks(session: Session, auction_id: int) -> None:
    url = f"{BASE.replace('http', 'ws')}/ws/auctions/{auction_id}"

    try:
        async with websockets.connect(
            url,
            origin="https://evil.example",
            additional_headers={"Cookie": f"{COOKIE}={session.token}"},
            proxy=None,
        ) as ws:
            await asyncio.wait_for(ws.recv(), timeout=2)
    except InvalidStatus as error:
        check("WebSocket handshake rejects a foreign origin", 403, error.response.status_code)
    except Exception as error:  # noqa: BLE001 - refused is the expected outcome
        check("WebSocket handshake rejects a foreign origin", "refused", type(error).__name__)
    else:  # pragma: no cover
        check("WebSocket handshake rejects a foreign origin", "refused", "connected")

    async with websockets.connect(
        url,
        origin=ORIGIN,
        additional_headers={"Cookie": f"{COOKIE}={session.token}"},
        proxy=None,
    ) as ws:
        snapshot = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        check("authenticated socket receives a snapshot", "snapshot", snapshot["type"])


# --------------------------------------------------------------------------
# Optional direct-database tamper proof
# --------------------------------------------------------------------------


def run_tamper_proof(auction_id: int) -> None:
    db_path = os.getenv("RA_DB_PATH", "data/app.db")
    if not os.path.exists(db_path):
        print(f"SKIP  tamper proof (database not found at {db_path})")
        return

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT id, amount, signature FROM bids WHERE auction_id = ? ORDER BY id LIMIT 1",
            (auction_id,),
        ).fetchone()
        if row is None:
            print("SKIP  tamper proof (no bid to tamper with)")
            return
        bid_id, amount, signature = row
        conn.execute("DROP TRIGGER IF EXISTS bids_no_update")
        conn.execute(
            "UPDATE bids SET amount = ? WHERE id = ?", (amount - 1, bid_id)
        )
        conn.commit()

    try:
        report = http.get(f"{BASE}/api/auctions/{auction_id}/verify").json()
        check("tampered bid is detected", False, report["valid"])
    finally:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE bids SET amount = ? WHERE id = ?", (amount, bid_id)
            )
            conn.execute(
                "CREATE TRIGGER IF NOT EXISTS bids_no_update BEFORE UPDATE ON bids "
                "BEGIN SELECT RAISE(ABORT, 'bids are immutable'); END"
            )
            conn.commit()

    restored = http.get(f"{BASE}/api/auctions/{auction_id}/verify").json()
    check("restoring the row restores the chain", True, restored["valid"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Reverse auction attack demo")
    parser.add_argument(
        "--tamper",
        action="store_true",
        help="prove that a direct database edit breaks the bid chain",
    )
    args = parser.parse_args()

    print(f"Target: {BASE}\n")
    auction_id = run_http_checks()

    seller = login("seller@revauction.dev")
    if auction_id is not None and seller is not None:
        asyncio.run(run_ws_checks(seller, auction_id))

    if args.tamper and auction_id is not None:
        run_tamper_proof(auction_id)

    if auction_id is not None:
        buyer = login("buyer@revauction.dev")
        if buyer is not None:
            call("POST", f"/api/auctions/{auction_id}/cancel", buyer)

    print(f"\n==== {PASSED} passed, {FAILED} failed ====")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
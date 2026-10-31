"""Seed demo users and auctions.

Run from ``backend/``::

    .venv/bin/python -m scripts.seed

Idempotent: existing users and auctions are left untouched, and the two signed
demo bids per auction use stable idempotency keys, so re-running adds nothing.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.models import Auction, AuctionStatus, Role, User
from app.models.mixins import utcnow
from app.security import totp as totp_utils
from app.security.passwords import hash_password
from app.services import bid_service

DEMO_PASSWORD = "DemoPass!234"

# Fixed demo secret so the viva can enrol an authenticator from a printout.
ADMIN_TOTP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"

DEMO_USERS: tuple[tuple[str, Role], ...] = (
    ("admin@revauction.dev", Role.ADMIN),
    ("buyer@revauction.dev", Role.BUYER),
    ("seller@revauction.dev", Role.SELLER),
    ("seller2@revauction.dev", Role.SELLER),
)

AUCTION_SPECS: tuple[dict[str, object], ...] = (
    {
        "title": "Bulk office chairs — 120 units",
        "description": (
            "Ergonomic mesh chairs delivered to the Pune campus. "
            "GST invoice required. Assembly included."
        ),
        "starting_price": 24_000_000,  # ₹2,40,000.00 in paise
        "min_decrement": 50_000,  # ₹500.00
        "ends_in": timedelta(days=2),
    },
    {
        "title": "Cloud migration audit — 4 weeks",
        "description": (
            "Independent review of the current AWS estate, IAM boundaries, "
            "and backup posture. Report plus remediation plan."
        ),
        "starting_price": 15_000_000,
        "min_decrement": 25_000,
        "ends_in": timedelta(days=5),
    },
    {
        "title": "Campus Wi-Fi site survey",
        "description": (
            "Passive and active survey across three buildings. "
            "Deliver heat maps and an AP placement plan."
        ),
        "starting_price": 5_000_000,
        "min_decrement": 10_000,
        "ends_in": timedelta(days=1),
    },
)


def seed() -> None:
    init_db()
    now = utcnow()

    with SessionLocal() as db:
        users: dict[str, User] = {}

        for email, role in DEMO_USERS:
            user = db.scalar(select(User).where(User.email == email))
            if user is None:
                user = User(
                    email=email,
                    password_hash=hash_password(DEMO_PASSWORD),
                    role=role,
                )
                db.add(user)
                db.flush()
            users[email] = user

        buyer = users["buyer@revauction.dev"]
        auctions_created = 0
        seeded_auctions: list[Auction] = []

        # Enrol the demo administrator's second factor so the admin console is
        # reachable out of the box. The secret is fixed and printed below.
        admin = users["admin@revauction.dev"]
        if not admin.totp_enabled:
            admin.totp_secret_enc = totp_utils.encrypt_secret(
                ADMIN_TOTP_SECRET, user_id=admin.id
            )
            admin.totp_enabled = True
            admin.totp_last_step = None

        for spec in AUCTION_SPECS:
            title = str(spec["title"])
            existing = db.scalar(select(Auction).where(Auction.title == title))
            if existing is not None:
                seeded_auctions.append(existing)
                continue

            auction = Auction(
                buyer_id=buyer.id,
                title=title,
                description=str(spec["description"]),
                starting_price=int(spec["starting_price"]),  # type: ignore[arg-type]
                min_decrement=int(spec["min_decrement"]),  # type: ignore[arg-type]
                currency="INR",
                starts_at=now - timedelta(hours=1),
                ends_at=now + spec["ends_in"],  # type: ignore[operator]
                status=AuctionStatus.OPEN,
            )
            db.add(auction)
            seeded_auctions.append(auction)
            auctions_created += 1

        db.commit()

        # Two signed, chained bids per open auction, using stable idempotency
        # keys so re-running the seed is a no-op.
        sellers = [
            users["seller@revauction.dev"],
            users["seller2@revauction.dev"],
        ]
        bids_created = 0
        for auction in seeded_auctions:
            for offset, seller in enumerate(sellers, start=1):
                amount = auction.starting_price - auction.min_decrement * offset
                try:
                    _, created = bid_service.place(
                        db,
                        auction,
                        seller,
                        amount=amount,
                        idempotency_key=f"seed-{auction.id}-{offset}",
                    )
                except bid_service.BidError:
                    continue
                if created:
                    bids_created += 1

    print("Seed complete.")
    print(f"  users: {len(DEMO_USERS)}  (password: {DEMO_PASSWORD})")
    for email, role in DEMO_USERS:
        print(f"    - {email:<28} {role.value}")
    print(f"  auctions created: {auctions_created}")
    print(f"  signed bids created: {bids_created}")
    print("  admin 2FA: enabled")
    print(f"    secret:  {ADMIN_TOTP_SECRET}")
    print(
        "    otpauth: "
        + totp_utils.provisioning_uri(
            ADMIN_TOTP_SECRET, account="admin@revauction.dev"
        )
    )
    print(
        "    current code: "
        + totp_utils.generate_code(ADMIN_TOTP_SECRET)
        + "  (rotates every 30s)"
    )


if __name__ == "__main__":
    seed()
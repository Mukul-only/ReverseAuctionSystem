"""Model registry.

Importing this package registers every table on ``Base.metadata`` before
``init_db`` runs.
"""

from .auction import Auction
from .audit import AuditEvent
from .bid import Bid
from .enums import AuctionStatus, Role
from .session import UserSession
from .user import User

__all__ = [
    "Auction",
    "AuctionStatus",
    "AuditEvent",
    "Bid",
    "Role",
    "User",
    "UserSession",
]
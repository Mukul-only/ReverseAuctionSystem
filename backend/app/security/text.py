"""Plain-text sanitisation.

The API stores plain text only. Tags are stripped before persistence as
defense in depth; React escapes on render as the primary XSS control.
"""

from __future__ import annotations

import re

_TAG_RE = re.compile(r"<[^>]*>")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_plain_text(value: str) -> str:
    """Strip HTML tags and control characters, preserving newlines."""
    without_tags = _TAG_RE.sub("", value)
    without_control = _CONTROL_RE.sub("", without_tags)
    return without_control.strip()


def sanitize_single_line(value: str) -> str:
    """Strip tags plus all whitespace runs — used for titles."""
    return " ".join(sanitize_plain_text(value).split())
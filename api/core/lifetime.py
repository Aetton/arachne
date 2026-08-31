"""Human-facing lifetime parsing for ephemeral resources."""
from __future__ import annotations

import re
from datetime import timedelta

_LIFETIME_RE = re.compile(r"^\s*(\d+)\s*([mhd])\s*$", re.IGNORECASE)


def parse_lifetime(value) -> timedelta | None:
    """Parse user-facing values like 30m, 2h or 1d.

    Empty/None means no automatic expiry. Backend-specific scheduling details do
    not leak into scenario YAML.
    """
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError("lifetime must look like 30m, 2h or 1d")

    match = _LIFETIME_RE.fullmatch(value)
    if not match:
        raise ValueError("lifetime must look like 30m, 2h or 1d")

    amount = int(match.group(1))
    if amount <= 0:
        raise ValueError("lifetime must be greater than zero")

    unit = match.group(2).lower()
    if unit == "m":
        return timedelta(minutes=amount)
    if unit == "h":
        return timedelta(hours=amount)
    return timedelta(days=amount)


def normalize_lifetime(value) -> str | None:
    """Return canonical compact form while validating the value."""
    delta = parse_lifetime(value)
    if delta is None:
        return None
    raw = str(value).strip().lower()
    match = _LIFETIME_RE.fullmatch(raw)
    assert match is not None
    return f"{int(match.group(1))}{match.group(2).lower()}"

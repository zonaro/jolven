"""UTC build versions shared by Meson and the GitHub release workflow.

Format: YY.DDD.HHmm, where DDD is the one-based, zero-padded ordinal day
(001-366) and HHmm is 24-hour UTC time (0000-2359).
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone

_VERSION = re.compile(r"^([0-9]{2})\.([0-9]{3})\.([0-9]{2})([0-9]{2})$")


def validate_version(value: str) -> str:
    """Reject non-calendar versions, including day 366 in non-leap years."""
    match = _VERSION.fullmatch(value)
    if match is None:
        raise ValueError(f"Invalid Jolven version {value!r}; expected YY.DDD.HHmm")
    year, ordinal, hour, minute = map(int, match.groups())
    full_year = 2000 + year
    date = datetime(full_year, 1, 1, tzinfo=timezone.utc) + timedelta(days=ordinal - 1)
    if not (1 <= ordinal <= 366 and date.year == full_year):
        raise ValueError("Invalid ordinal day in Jolven version")
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("Invalid 24-hour time in Jolven version")
    return value


def build_version() -> str:
    """Use one frozen CI version or the current UTC minute for local builds."""
    override = os.getenv("JOLVEN_VERSION", "").strip() or os.getenv(
        "CARTRIDGES_VERSION", ""
    ).strip()
    return validate_version(
        override or datetime.now(timezone.utc).strftime("%y.%j.%H%M")
    )

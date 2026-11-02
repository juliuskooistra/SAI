"""
Time helpers: the database stores UTC, the shop thinks in Zurich time.

All times in the code are timezone-aware UTC (SQLModel refuses naive ones).
Everything that needs "now" calls `utcnow()` from this module, so tests can
freeze the clock in one place.
"""
from datetime import datetime, timezone

from .config import SHOP_TZ


_frozen_now: datetime | None = None  # set by tests through freeze_time()


def utcnow() -> datetime:
    """Current time, aware UTC."""
    return _frozen_now or datetime.now(timezone.utc)


def freeze_time(value: datetime | None) -> None:
    """Tests only: make utcnow() return `value` (None = real clock again)."""
    global _frozen_now
    _frozen_now = value


def to_utc(value: datetime) -> datetime:
    """Turn an incoming time into aware UTC. A time without offset is Zurich time."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=SHOP_TZ)
    return value.astimezone(timezone.utc)


def to_local(value: datetime | None) -> datetime | None:
    """Turn a stored UTC time into Zurich time for responses and rules."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(SHOP_TZ)


def format_local(value: datetime) -> str:
    """Human-readable Zurich time for error messages, e.g. 'Sat 7 Nov 14:00'."""
    local = to_local(value)
    return f"{local:%a} {local.day} {local:%b %H:%M}"

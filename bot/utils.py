from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

# В базе все даты — TIMESTAMPTZ (хранятся в UTC); в интерфейсе показываем в часовом поясе TZ.
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def since(days: int | None) -> datetime:
    """Начало периода; None/0 — «всё время»."""
    return utcnow() - timedelta(days=days) if days else EPOCH


@lru_cache(maxsize=8)
def _zone(tz_name: str) -> ZoneInfo:
    return ZoneInfo(tz_name)


def to_local(dt: datetime, tz_name: str) -> datetime:
    return dt.astimezone(_zone(tz_name))


def fmt_local(dt: datetime | None, tz_name: str) -> str:
    return to_local(dt, tz_name).strftime("%d.%m.%Y %H:%M") if dt else "—"


def fmt_short_date(dt: datetime | None, tz_name: str) -> str:
    return to_local(dt, tz_name).strftime("%d.%m") if dt else "—"


def fmt_hours(h: float | None) -> str:
    if h is None:
        return "—"
    if h < 1:
        return f"{max(int(h * 60), 1)} мин"
    if h < 48:
        return f"{h:.1f} ч"
    return f"{h / 24:.1f} дн"

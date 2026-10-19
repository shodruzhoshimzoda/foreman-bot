from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# В базе все даты хранятся в UTC в формате SQLite: "YYYY-MM-DD HH:MM:SS"
DB_FMT = "%Y-%m-%d %H:%M:%S"


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_db(dt: datetime) -> str:
    """aware-datetime -> UTC строка; naive считается уже UTC."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime(DB_FMT)


def now_str() -> str:
    return to_db(utcnow())


def from_db(s: str) -> datetime:
    return datetime.strptime(s, DB_FMT)


def to_local(s: str, tz_name: str) -> datetime:
    return from_db(s).replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz_name))


def fmt_local(s: str | None, tz_name: str) -> str:
    if not s:
        return "—"
    return to_local(s, tz_name).strftime("%d.%m.%Y %H:%M")


def fmt_short_date(s: str | None, tz_name: str) -> str:
    if not s:
        return "—"
    return to_local(s, tz_name).strftime("%d.%m")


def fmt_hours(h: float | None) -> str:
    if h is None:
        return "—"
    if h < 1:
        return f"{max(int(h * 60), 1)} мин"
    if h < 48:
        return f"{h:.1f} ч"
    return f"{h / 24:.1f} дн"

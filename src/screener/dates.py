from __future__ import annotations

from datetime import date, datetime
from typing import Callable
from zoneinfo import ZoneInfo

NEW_YORK_TIMEZONE = ZoneInfo("America/New_York")
NY_DATE_ALIASES = {"", "auto", "ny-today", "ny_today"}


def resolve_ny_run_date(value: str | None = None, *, clock: Callable[[], datetime] | None = None) -> str:
    """Resolve an operational run date string to an America/New_York ISO date.

    Explicit YYYY-MM-DD values are preserved. Empty/auto aliases use the current
    date in America/New_York so UTC/KST schedulers do not accidentally advance
    the NASDAQ trading date during the early KST morning.
    """
    if value is None or value.strip().lower() in NY_DATE_ALIASES:
        now = clock() if clock is not None else datetime.now(tz=NEW_YORK_TIMEZONE)
        if now.tzinfo is None:
            now = now.replace(tzinfo=NEW_YORK_TIMEZONE)
        return now.astimezone(NEW_YORK_TIMEZONE).date().isoformat()

    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Date must be YYYY-MM-DD, 'auto', or 'ny-today'.") from exc

    normalized = parsed.isoformat()
    if normalized != value:
        raise ValueError("Date must be YYYY-MM-DD, 'auto', or 'ny-today'.")
    return normalized

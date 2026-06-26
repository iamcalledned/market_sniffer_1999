from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta


def subtract_calendar_months(day: date, months: int) -> date:
    month_index = day.year * 12 + (day.month - 1) - months
    year = month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(day.day, monthrange(year, month)[1]))


def default_backfill_window(today: date | None = None, months: int = 24) -> tuple[date, date]:
    end = today or date.today()
    return subtract_calendar_months(end, months), end


def business_days(start: date, end: date) -> list[date]:
    days: list[date] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal


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


class MarketCalendar:
    def __init__(self, calendar_name: str = "XNYS"):
        self.calendar = mcal.get_calendar(calendar_name)

    def sessions(self, start: date, end: date) -> list[date]:
        schedule = self.calendar.schedule(start_date=start.isoformat(), end_date=end.isoformat())
        return [idx.date() for idx in schedule.index]

    def previous_session(self, day: date) -> date:
        sessions = self.sessions(day - timedelta(days=14), day - timedelta(days=1))
        if not sessions:
            raise ValueError(f"no prior market session found before {day}")
        return sessions[-1]

    def completed_session_end_date(
        self,
        now: datetime | None = None,
        post_close_buffer_minutes: int = 30,
        provider_final_confirmed: bool = False,
    ) -> date:
        current = now or datetime.now(ZoneInfo("America/New_York"))
        if current.tzinfo is None:
            current = current.replace(tzinfo=ZoneInfo("America/New_York"))
        local_day = current.astimezone(ZoneInfo("America/New_York")).date()
        schedule = self.calendar.schedule(start_date=local_day.isoformat(), end_date=local_day.isoformat())
        if schedule.empty:
            return self.previous_session(local_day)
        close_ts = schedule.iloc[0]["market_close"].to_pydatetime()
        safe_close = close_ts + timedelta(minutes=post_close_buffer_minutes)
        if current.astimezone(close_ts.tzinfo) >= safe_close or provider_final_confirmed:
            return local_day
        return self.previous_session(local_day)

    def recent_completed_range(self, session_count: int, now: datetime | None = None) -> tuple[date, date]:
        end = self.completed_session_end_date(now)
        sessions = self.sessions(end - timedelta(days=max(20, session_count * 4)), end)
        selected = sessions[-session_count:]
        return selected[0], selected[-1]


def market_backfill_window(months: int = 24, now: datetime | None = None) -> tuple[date, date]:
    end = MarketCalendar().completed_session_end_date(now)
    return subtract_calendar_months(end, months), end


def warn_if_possible_incomplete_market_date(end: date, now: datetime | None = None) -> str | None:
    safe_end = MarketCalendar().completed_session_end_date(now)
    if end > safe_end:
        return f"requested --to {end} is after latest completed market session {safe_end}"
    return None

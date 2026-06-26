from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

from market_sniffer.collectors.base import DailyBar, EntitlementError, MissingCredentialError, ProviderError
from market_sniffer.services.dates import business_days


class MassiveClient:
    def __init__(self, api_key: str | None):
        self.api_key = api_key

    def daily_bars(self, symbol: str, start: date, end: date) -> tuple[dict[str, Any], list[DailyBar]]:
        if not self.api_key:
            raise MissingCredentialError("MASSIVE_API_KEY or POLYGON_API_KEY is required for real market collection")
        url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/day/{start}/{end}"
        params = {"adjusted": "true", "sort": "asc", "limit": "50000", "apiKey": self.api_key}
        response = httpx.get(url, params=params, timeout=30)
        payload = response.json()
        if response.status_code in {401, 403}:
            raise EntitlementError(f"Massive/Polygon entitlement unavailable for {symbol}")
        if response.status_code >= 400 or payload.get("status") == "ERROR":
            raise ProviderError(f"Massive/Polygon error for {symbol}: {payload.get('error', response.text)}")
        bars: list[DailyBar] = []
        for row in payload.get("results", []):
            trade_date = datetime.fromtimestamp(row["t"] / 1000, tz=timezone.utc).date()
            bars.append(
                DailyBar(
                    trade_date=trade_date,
                    open=Decimal(str(row["o"])),
                    high=Decimal(str(row["h"])),
                    low=Decimal(str(row["l"])),
                    close=Decimal(str(row["c"])),
                    adjusted_close=Decimal(str(row["c"])),
                    volume=int(row["v"]) if row.get("v") is not None else None,
                    vwap=Decimal(str(row["vw"])) if row.get("vw") is not None else None,
                    transaction_count=int(row["n"]) if row.get("n") is not None else None,
                    adjusted=True,
                )
            )
        return payload, bars

    def corporate_actions(self, symbol: str, start: date, end: date) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if not self.api_key:
            raise MissingCredentialError("MASSIVE_API_KEY or POLYGON_API_KEY is required for corporate actions")
        return {"symbol": symbol, "start": start.isoformat(), "end": end.isoformat(), "results": []}, []


class FixtureMassiveClient:
    def daily_bars(self, symbol: str, start: date, end: date) -> tuple[dict[str, Any], list[DailyBar]]:
        bars: list[DailyBar] = []
        for idx, day in enumerate(business_days(start, min(end, start.replace(day=min(start.day + 4, 28))))):
            base = Decimal("100") + Decimal(idx) + Decimal(sum(ord(c) for c in symbol) % 20)
            bars.append(
                DailyBar(
                    trade_date=day,
                    open=base,
                    high=base + Decimal("1"),
                    low=base - Decimal("1"),
                    close=base + Decimal("0.25"),
                    adjusted_close=base + Decimal("0.25"),
                    volume=1000000 + idx,
                )
            )
        return {"symbol": symbol, "resultsCount": len(bars), "fixture": True}, bars

    def corporate_actions(self, symbol: str, start: date, end: date) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        return {"symbol": symbol, "start": start.isoformat(), "end": end.isoformat(), "results": [], "fixture": True}, []

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from market_sniffer.collectors.base import DailyBar, MissingCredentialError, ProviderError
from market_sniffer.services.dates import business_days


class YahooHistoricalClient:
    def __init__(self, enabled: bool):
        self.enabled = enabled

    def daily_bars(self, symbol: str, start: date, end: date) -> tuple[dict[str, Any], list[DailyBar]]:
        if not self.enabled:
            raise MissingCredentialError(
                "Yahoo historical validation is disabled; set YAHOO_ENABLED=true and "
                "YAHOO_HISTORICAL_VALIDATION_ENABLED=true"
            )
        try:
            import yfinance as yf  # type: ignore
        except ImportError as exc:
            raise MissingCredentialError("Install the yahoo extra to use Yahoo historical validation") from exc
        ticker = yf.Ticker(symbol)
        # yfinance end is exclusive for history(); include the requested end date.
        # auto_adjust=False preserves Yahoo's native Close plus separate Adj Close.
        frame = ticker.history(
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            interval="1d",
            auto_adjust=False,
            actions=True,
        )
        if frame is None or frame.empty:
            raise ProviderError(f"Yahoo returned no historical daily bars for {symbol}")
        rows: list[dict[str, Any]] = []
        bars: list[DailyBar] = []
        for idx, row in frame.iterrows():
            trade_date = idx.date()
            raw = {
                "date": trade_date.isoformat(),
                "open": None if row.get("Open") is None else float(row["Open"]),
                "high": None if row.get("High") is None else float(row["High"]),
                "low": None if row.get("Low") is None else float(row["Low"]),
                "close": None if row.get("Close") is None else float(row["Close"]),
                "adj_close": None if row.get("Adj Close") is None else float(row["Adj Close"]),
                "volume": None if row.get("Volume") is None else int(row["Volume"]),
            }
            rows.append(raw)
            adjusted_close = raw["adj_close"] if raw["adj_close"] is not None else raw["close"]
            bars.append(
                DailyBar(
                    trade_date=trade_date,
                    open=Decimal(str(raw["open"])),
                    high=Decimal(str(raw["high"])),
                    low=Decimal(str(raw["low"])),
                    close=Decimal(str(raw["close"])),
                    adjusted_close=Decimal(str(adjusted_close)) if adjusted_close is not None else None,
                    volume=raw["volume"],
                    adjusted=True,
                    price_basis="provider_adjusted_unknown",
                )
            )
        return {"symbol": symbol, "start": start.isoformat(), "end": end.isoformat(), "rows": rows}, bars

    def corporate_actions(self, symbol: str, start: date, end: date) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        return {"symbol": symbol, "start": start.isoformat(), "end": end.isoformat(), "rows": []}, []


class FixtureYahooHistoricalClient:
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
                    adjusted=True,
                    price_basis="provider_adjusted_unknown",
                )
            )
        return {"symbol": symbol, "resultsCount": len(bars), "fixture": True}, bars

    def corporate_actions(self, symbol: str, start: date, end: date) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        return {"symbol": symbol, "start": start.isoformat(), "end": end.isoformat(), "results": [], "fixture": True}, []


class YahooQuoteClient:
    def __init__(self, enabled: bool, quotes_enabled: bool):
        self.enabled = enabled
        self.quotes_enabled = quotes_enabled

    def quote_snapshot(self, symbol: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not self.enabled or not self.quotes_enabled:
            raise MissingCredentialError("Yahoo quote snapshots are disabled by default")
        try:
            import yfinance as yf  # type: ignore
        except ImportError as exc:
            raise MissingCredentialError("Install the yahoo extra to use Yahoo quote snapshots") from exc
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        now = datetime.now(timezone.utc)
        payload = dict(info)
        quote = {
            "quote_timestamp_utc": now,
            "last_price": info.get("last_price"),
            "bid": info.get("bid"),
            "ask": info.get("ask"),
            "prior_close": info.get("previous_close"),
            "volume": info.get("last_volume"),
            "market_state": None,
            "quote_delay_seconds": None,
            "quote_quality": "unknown",
            "is_tradeable_quote": False,
            "is_stale": False,
        }
        return payload, quote


class FixtureYahooQuoteClient:
    def quote_snapshot(self, symbol: str) -> tuple[dict[str, Any], dict[str, Any]]:
        now = datetime(2026, 1, 2, 15, 30, tzinfo=timezone.utc)
        price = Decimal("100") + Decimal(sum(ord(c) for c in symbol) % 50)
        quote = {
            "quote_timestamp_utc": now,
            "last_price": price,
            "bid": price - Decimal("0.01"),
            "ask": price + Decimal("0.01"),
            "prior_close": price - Decimal("1.00"),
            "volume": 123456,
            "market_state": "regular",
            "quote_delay_seconds": 900,
            "quote_quality": "delayed",
            "is_tradeable_quote": False,
            "is_stale": False,
        }
        return {"symbol": symbol, "fixture": True, "quote": {k: str(v) for k, v in quote.items()}}, quote

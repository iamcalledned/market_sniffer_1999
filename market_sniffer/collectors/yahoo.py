from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from market_sniffer.collectors.base import MissingCredentialError


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

from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from market_sniffer.collectors.yahoo import FixtureYahooQuoteClient, YahooQuoteClient
from market_sniffer.db.repository import WarehouseRepository
from market_sniffer.services.quotes.view_models import YahooQuoteViewModel
from market_sniffer.settings import get_settings


class YahooQuoteService:
    def __init__(self, session: Session, fixture: bool = False):
        self.session = session
        self.repo = WarehouseRepository(session)
        self.fixture = fixture

        settings = get_settings()
        self.client: FixtureYahooQuoteClient | YahooQuoteClient
        if fixture:
            self.client = FixtureYahooQuoteClient()
        else:
            self.client = YahooQuoteClient(settings.yahoo_enabled, settings.yahoo_quotes_enabled)

    def validate_symbol(self, symbol: str) -> str:
        """Validates that a symbol fits standard ticker syntax constraints."""
        cleaned = symbol.strip().upper()
        if not cleaned:
            raise ValueError("Symbol cannot be empty.")
        if not re.match(r"^[A-Z0-9.-]{1,10}$", cleaned):
            raise ValueError(
                f"Invalid symbol format: '{symbol}'. Symbols must be 1-10 alphanumeric characters (dots/dashes allowed)."
            )
        return cleaned

    def lookup_quote(self, symbol: str, persist: bool = False) -> YahooQuoteViewModel:
        """Performs a best-effort quote lookup for a single validated symbol."""
        cleaned_symbol = self.validate_symbol(symbol)
        now = datetime.now(timezone.utc)

        # Call Yahoo Provider
        payload, quote = self.client.quote_snapshot(cleaned_symbol)

        is_persisted = False
        if persist:
            raw_payload = self.repo.raw_payload(
                "yahoo",
                "quote_snapshot",
                {"symbol": cleaned_symbol, "user_requested": True},
                payload,
            )
            is_persisted = self.repo.insert_quote_snapshot(
                cleaned_symbol, "yahoo", raw_payload, quote
            )
            self.session.commit()

        # Format delay label clearly
        delay_sec = quote.get("quote_delay_seconds")

        # Check timestamp
        ts = quote.get("quote_timestamp_utc")
        if ts is None:
            ts = now
        elif isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))

        return YahooQuoteViewModel(
            symbol=cleaned_symbol,
            last_price=quote.get("last_price"),
            bid=quote.get("bid"),
            ask=quote.get("ask"),
            prior_close=quote.get("prior_close"),
            volume=quote.get("volume"),
            market_state=quote.get("market_state"),
            quote_delay_seconds=delay_sec,
            quote_quality=quote.get("quote_quality", "best-effort"),
            quote_timestamp_utc=ts,
            request_timestamp_utc=now,
            is_persisted=is_persisted,
        )

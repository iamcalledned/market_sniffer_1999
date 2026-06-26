from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass
class YahooQuoteViewModel:
    symbol: str
    last_price: Decimal | None
    bid: Decimal | None
    ask: Decimal | None
    prior_close: Decimal | None
    volume: int | None
    market_state: str | None
    quote_delay_seconds: int | None
    quote_quality: str
    quote_timestamp_utc: datetime
    request_timestamp_utc: datetime
    provider: str = "Yahoo"
    is_persisted: bool = False

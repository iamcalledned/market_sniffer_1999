from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Protocol


class ProviderError(RuntimeError):
    event_type = "collector_failure"


class MissingCredentialError(ProviderError):
    event_type = "collector_failure"


class EntitlementError(ProviderError):
    event_type = "unavailable_entitlement"


class RateLimitError(ProviderError):
    event_type = "rate_limit_hit"


@dataclass(frozen=True)
class FredObservation:
    observation_date: date
    value: Decimal
    realtime_start: date | None
    realtime_end: date | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class DailyBar:
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adjusted_close: Decimal | None
    volume: int | None
    vwap: Decimal | None = None
    transaction_count: int | None = None
    adjusted: bool = True
    price_basis: str = "split_adjusted"

    def asdict(self) -> dict[str, Any]:
        return {
            "trade_date": self.trade_date,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "adjusted_close": self.adjusted_close,
            "volume": self.volume,
            "vwap": self.vwap,
            "transaction_count": self.transaction_count,
            "adjusted": self.adjusted,
            "price_basis": self.price_basis,
        }


class FredClient(Protocol):
    def observations(self, series_id: str, start: date, end: date) -> tuple[dict[str, Any], list[FredObservation]]:
        ...


class MarketDataClient(Protocol):
    def daily_bars(self, symbol: str, start: date, end: date) -> tuple[dict[str, Any], list[DailyBar]]:
        ...

    def corporate_actions(self, symbol: str, start: date, end: date) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        ...


class QuoteClient(Protocol):
    def quote_snapshot(self, symbol: str) -> tuple[dict[str, Any], dict[str, Any]]:
        ...

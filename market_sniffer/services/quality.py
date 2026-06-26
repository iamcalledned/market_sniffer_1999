from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from market_sniffer.db import models as m
from market_sniffer.db.repository import WarehouseRepository


class DataQualityService:
    def __init__(self, session: Session):
        self.session = session
        self.repo = WarehouseRepository(session)

    def check_quote_freshness(self, max_age_minutes: int = 20) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
        count = 0
        quotes = self.session.scalars(select(m.QuoteSnapshot).where(m.QuoteSnapshot.quote_timestamp_utc < cutoff)).all()
        for quote in quotes:
            quote.is_stale = True
            quote.quote_quality = "stale"
            self.repo.record_event(
                "quote_freshness_problem",
                "Quote snapshot is older than configured freshness tolerance.",
                severity="warning",
                collector_run_id=None,
                details={"quote_snapshot_id": quote.id, "max_age_minutes": max_age_minutes},
            )
            count += 1
        self.session.commit()
        return count

    @staticmethod
    def classify_quote(
        quote_timestamp_utc: datetime | None,
        received_at_utc: datetime,
        provider_quality: str | None = None,
        provider_delay_seconds: int | None = None,
        stale_after_seconds: int = 1200,
    ) -> tuple[str, bool]:
        if provider_quality == "live" and provider_delay_seconds == 0:
            return "live", False
        if quote_timestamp_utc is None:
            return "unknown", False
        age = (received_at_utc - quote_timestamp_utc).total_seconds()
        if age > stale_after_seconds:
            return "stale", True
        if provider_quality in {"delayed", "near_real_time", "market_closed", "last_known", "unavailable"}:
            return provider_quality, False
        if provider_delay_seconds is not None and provider_delay_seconds > 0:
            return "delayed", False
        return "unknown", False

    def summary(self) -> dict[str, int]:
        return self.repo.counts()

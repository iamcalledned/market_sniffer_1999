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

    def summary(self) -> dict[str, int]:
        return self.repo.counts()

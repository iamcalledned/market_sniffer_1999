from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from market_sniffer.db import models as m
from market_sniffer.db.repository import WarehouseRepository, utc_now


DEFAULT_RETENTION_DAYS = {
    "quote": 90,
    "intraday": 90,
    "validation": 90,
}


@dataclass(frozen=True)
class RetentionResult:
    eligible: int
    pruned: int
    protected: int
    dry_run: bool


class RetentionService:
    def __init__(self, session: Session):
        self.session = session
        self.repo = WarehouseRepository(session)

    def prune_raw_payloads(
        self,
        scope: str,
        dry_run: bool = True,
        retention_days: int | None = None,
    ) -> RetentionResult:
        if scope not in DEFAULT_RETENTION_DAYS:
            raise ValueError(f"unsupported retention scope: {scope}")
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days or DEFAULT_RETENTION_DAYS[scope])
        payloads = self.session.scalars(
            select(m.RawPayload).where(
                m.RawPayload.retention_class == scope,
                m.RawPayload.pruned_at_utc.is_(None),
                m.RawPayload.retrieved_at_utc < cutoff,
            )
        ).all()
        protected_ids = self._protected_payload_ids()
        eligible = 0
        protected = 0
        pruned = 0
        for payload in payloads:
            if payload.protected or payload.id in protected_ids:
                protected += 1
                continue
            eligible += 1
            if not dry_run:
                payload.response_payload = None
                payload.error_context = {
                    **(payload.error_context or {}),
                    "retention_pruned": True,
                    "retention_scope": scope,
                }
                payload.pruned_at_utc = utc_now()
                pruned += 1
        if not dry_run:
            run = self.repo.start_run("raw_payload_retention", "maintenance", target_type="raw_payload", target_key=scope)
            run.fetched_count = len(payloads)
            run.updated_count = pruned
            run.skipped_count = protected
            self.repo.finish_run(run, "succeeded")
            self.session.commit()
        return RetentionResult(eligible=eligible, pruned=pruned, protected=protected, dry_run=dry_run)

    def _protected_payload_ids(self) -> set[int]:
        discrepancy_ids = {
            row.raw_payload_id
            for row in self.session.scalars(select(m.SourceDiscrepancy)).all()
            if row.raw_payload_id is not None and row.status in {"material_difference", "validation_unavailable"}
        }
        event_details = self.session.scalars(select(m.DataQualityEvent)).all()
        event_ids = {
            int(event.details["raw_payload_id"])
            for event in event_details
            if isinstance(event.details, dict) and event.details.get("raw_payload_id") is not None
        }
        canonical_ids = {
            row.raw_payload_id
            for row in self.session.scalars(select(m.CanonicalMarketBarDaily)).all()
        } | {
            row.raw_payload_id
            for row in self.session.scalars(select(m.CanonicalObservation)).all()
        }
        return discrepancy_ids | event_ids | canonical_ids

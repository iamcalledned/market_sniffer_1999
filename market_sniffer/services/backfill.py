from __future__ import annotations

import time
from datetime import date
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from market_sniffer.collectors.base import FredClient, MarketDataClient, ProviderError, QuoteClient, RateLimitError
from market_sniffer.db import models as m
from market_sniffer.db.repository import WarehouseRepository
from market_sniffer.services.registry_service import Registry


DISCREPANCY_STATUSES = {
    "match",
    "minor_difference",
    "material_difference",
    "not_comparable",
    "validation_unavailable",
}


class BackfillService:
    def __init__(
        self,
        session: Session,
        registry: Registry,
        fred_client: FredClient,
        market_client: MarketDataClient,
        quote_client: QuoteClient | None = None,
        validation_client: MarketDataClient | None = None,
    ):
        self.session = session
        self.registry = registry
        self.repo = WarehouseRepository(session)
        self.fred_client = fred_client
        self.market_client = market_client
        self.quote_client = quote_client
        self.validation_client = validation_client

    def backfill(
        self,
        profile: str,
        start: date,
        end: date,
        only: Iterable[str] | None = None,
        dry_run: bool = False,
        continue_on_error: bool = False,
        fred_end: date | None = None,
        resume: bool = False,
        force: bool = False,
    ) -> int:
        only_set = set(only or [])
        parent = self.repo.start_run("backfill", profile, date_from=start, date_to=end)
        failures = 0
        try:
            if profile in {"core", "fred_macro"}:
                failures += self._fred(start, fred_end or end, only_set, parent.id, dry_run, continue_on_error, resume, force)
            if profile in {"core", "daily_market"}:
                failures += self._daily_market(start, end, only_set, parent.id, dry_run, continue_on_error, resume, force)
            if profile == "core":
                failures += self._corporate_actions(start, end, only_set, parent.id, dry_run, continue_on_error, resume, force)
                failures += self._yahoo_validation_sample(start, end, only_set, parent.id, dry_run, continue_on_error, resume, force)
            self.repo.finish_run(parent, "failed" if failures else "succeeded")
            return failures
        except Exception as exc:
            self.repo.finish_run(parent, "failed", {"error": str(exc)})
            raise

    def validate_history(
        self,
        symbols: Iterable[str],
        start: date,
        end: date,
        continue_on_error: bool = False,
    ) -> dict[str, dict[str, int]]:
        profile_cfg = self.registry.profiles.get("daily_market", {})
        precedence = profile_cfg.get("canonical_source_precedence", ["massive", "yahoo"])
        price_basis = profile_cfg.get("price_basis", "split_adjusted")
        fallback_allowed = bool(profile_cfg.get("yahoo_fallback_allowed", False))
        summary = {
            symbol: {status: 0 for status in DISCREPANCY_STATUSES}
            for symbol in symbols
        }
        for symbol in symbols:
            run = self.repo.start_run(
                "validate_history",
                "validation",
                "yahoo",
                target_type="instrument",
                target_key=symbol,
                date_from=start,
                date_to=end,
            )
            try:
                massive_payload, massive_bars = self._with_retries(lambda: self.market_client.daily_bars(symbol, start, end))
                massive_raw = self.repo.raw_payload(
                    "massive",
                    "aggs/ticker/range/1/day",
                    {"symbol": symbol, "from": start.isoformat(), "to": end.isoformat(), "apiKey": "***REDACTED***"},
                    massive_payload,
                )
                for bar in massive_bars:
                    _, source_bar = self.repo.insert_daily_bar(symbol, "massive", massive_raw, bar.asdict())
                    self.repo.canonicalize_daily_bar(
                        symbol,
                        source_bar.trade_date,
                        precedence,
                        price_basis=price_basis,
                        allow_yahoo_fallback=fallback_allowed,
                    )

                if self.validation_client is None:
                    raise ProviderError("Yahoo historical validation client is not configured")
                yahoo_payload, yahoo_bars = self._with_retries(lambda: self.validation_client.daily_bars(symbol, start, end))
                yahoo_raw = self.repo.raw_payload(
                    "yahoo",
                    "historical_daily_bars",
                    {"symbol": symbol, "from": start.isoformat(), "to": end.isoformat()},
                    yahoo_payload,
                    retention_class="validation",
                )
                run.fetched_count = len(yahoo_bars)
                for bar in yahoo_bars:
                    inserted, _ = self.repo.insert_daily_bar(symbol, "yahoo", yahoo_raw, bar.asdict())
                    if inserted:
                        run.inserted_count += 1
                    else:
                        run.skipped_count += 1
                    self._compare_yahoo_bar(symbol, bar.trade_date, bar, yahoo_raw.id, run.id)
                    for status, count in self._current_discrepancy_counts(symbol, bar.trade_date).items():
                        summary[symbol][status] += count
                self.repo.finish_run(run, "succeeded")
            except ProviderError as exc:
                run.failed_count = 1
                self.repo.record_event(
                    exc.event_type,
                    str(exc),
                    "error",
                    "yahoo",
                    symbol=symbol,
                    collector_run_id=run.id,
                    observation_date=end,
                    details={"status": "validation_unavailable"},
                )
                self.repo.finish_run(run, "failed", {"error": str(exc)})
                summary[symbol]["validation_unavailable"] += 1
                if not continue_on_error:
                    raise
        self.session.commit()
        return summary

    def _current_discrepancy_counts(self, symbol: str, trade_date: date) -> dict[str, int]:
        inst = self.repo.instrument(symbol)
        rule_version = str(self._daily_validation_policy()["comparison_rule_version"])
        rows = self.session.scalars(
            select(m.SourceDiscrepancy).where(
                m.SourceDiscrepancy.instrument_id == inst.id,
                m.SourceDiscrepancy.trade_date == trade_date,
                m.SourceDiscrepancy.comparison_rule_version == rule_version,
            )
        ).all()
        counts = {status: 0 for status in DISCREPANCY_STATUSES}
        for row in rows:
            counts[row.status] += 1
        return counts

    def _fred(
        self,
        start: date,
        end: date,
        only: set[str],
        parent_run_id: int,
        dry_run: bool,
        continue_on_error: bool,
        resume: bool,
        force: bool,
    ) -> int:
        failures = 0
        for code, meta in self.registry.series.items():
            if only and code not in only and f"FRED:{code}" not in only:
                continue
            if meta.get("collection_profile") != "fred_macro" or not meta.get("backfill", True):
                continue
            if resume and not force and self._completed_run_exists("fred_observations", "series", code, start, end):
                print(f"resume skip fred {code} {start}..{end}: completed")
                continue
            run = self.repo.start_run("fred_observations", "fred_macro", "fred", parent_run_id, "series", code, start, end)
            try:
                payload, observations = self._with_retries(lambda: self.fred_client.observations(meta["source_id"], start, end))
                raw_payload = self.repo.raw_payload(
                    "fred",
                    "series/observations",
                    {"series_id": meta["source_id"], "observation_start": start.isoformat(), "observation_end": end.isoformat()},
                    payload,
                )
                run.fetched_count = len(observations)
                if not observations:
                    self.repo.record_event("missing_expected_observation", f"FRED returned no observations for {code}", "warning", "fred", code, collector_run_id=run.id)
                if not dry_run:
                    for obs in observations:
                        inserted, _ = self.repo.insert_fred_observation(
                            code,
                            raw_payload,
                            obs.observation_date,
                            obs.value,
                            obs.realtime_start,
                            obs.realtime_end,
                            obs.raw,
                        )
                        if inserted:
                            run.inserted_count += 1
                        else:
                            run.skipped_count += 1
                self.repo.finish_run(run, "succeeded")
                print(f"fred {code} {start}..{end} fetched={run.fetched_count} inserted={run.inserted_count} skipped={run.skipped_count} failed=0")
            except ProviderError as exc:
                failures += 1
                run.failed_count = 1
                self.repo.record_event(exc.event_type, str(exc), "error", "fred", code, collector_run_id=run.id)
                self.repo.finish_run(run, "failed", {"error": str(exc)})
                print(f"fred {code} {start}..{end} fetched=0 inserted=0 skipped=0 failed=1")
                if not continue_on_error:
                    raise
        self.session.commit()
        return failures

    def _corporate_actions(
        self,
        start: date,
        end: date,
        only: set[str],
        parent_run_id: int,
        dry_run: bool,
        continue_on_error: bool,
        resume: bool,
        force: bool,
    ) -> int:
        failures = 0
        for symbol, meta in self.registry.instruments.items():
            if only and symbol not in only and f"MASSIVE:{symbol}" not in only and f"POLYGON:{symbol}" not in only:
                continue
            if not meta.get("daily", True):
                continue
            if resume and not force and self._completed_run_exists(
                "massive_corporate_actions", "instrument", symbol, start, end
            ):
                print(f"resume skip massive corporate_actions {symbol} {start}..{end}: completed")
                continue
            run = self.repo.start_run(
                "massive_corporate_actions",
                "daily_market",
                "massive",
                parent_run_id,
                "instrument",
                symbol,
                start,
                end,
            )
            try:
                payload, actions = self._with_retries(lambda: self.market_client.corporate_actions(symbol, start, end))
                raw_payload = self.repo.raw_payload(
                    "massive",
                    "corporate_actions",
                    {"symbol": symbol, "from": start.isoformat(), "to": end.isoformat(), "apiKey": "***REDACTED***"},
                    payload,
                )
                run.fetched_count = len(actions)
                if not dry_run:
                    for action in actions:
                        if self.repo.insert_corporate_action(symbol, "massive", raw_payload, action):
                            run.inserted_count += 1
                        else:
                            run.skipped_count += 1
                self.repo.finish_run(run, "succeeded")
                print(
                    f"massive corporate_actions {symbol} {start}..{end} "
                    f"fetched={run.fetched_count} inserted={run.inserted_count} "
                    f"skipped={run.skipped_count} failed=0"
                )
            except ProviderError as exc:
                failures += 1
                run.failed_count = 1
                self.repo.record_event(exc.event_type, str(exc), "error", "massive", symbol=symbol, collector_run_id=run.id)
                self.repo.finish_run(run, "failed", {"error": str(exc)})
                if not continue_on_error:
                    raise
        self.session.commit()
        return failures

    def _yahoo_validation_sample(
        self,
        start: date,
        end: date,
        only: set[str],
        parent_run_id: int,
        dry_run: bool,
        continue_on_error: bool,
        resume: bool,
        force: bool,
    ) -> int:
        failures = 0
        sample = self.registry.profiles.get("validation", {}).get("sample_symbols", [])
        for symbol in sample:
            if only and symbol not in only and f"YAHOO:{symbol}" not in only:
                continue
            if resume and not force and self._completed_run_exists("yahoo_validation_history", "instrument", symbol, start, end):
                print(f"resume skip yahoo validation {symbol} {start}..{end}: completed")
                continue
            run = self.repo.start_run(
                "yahoo_validation_history",
                "validation",
                "yahoo",
                parent_run_id,
                "instrument",
                symbol,
                start,
                end,
            )
            try:
                if self.validation_client is None:
                    raise ProviderError("Yahoo historical validation client is not configured")
                payload, bars = self._with_retries(lambda: self.validation_client.daily_bars(symbol, start, end))
                raw_payload = self.repo.raw_payload(
                    "yahoo",
                    "historical_daily_bars",
                    {"symbol": symbol, "from": start.isoformat(), "to": end.isoformat()},
                    payload,
                    retention_class="validation",
                )
                run.fetched_count = len(bars)
                if not dry_run:
                    for bar in bars:
                        inserted, _source_bar = self.repo.insert_daily_bar(symbol, "yahoo", raw_payload, bar.asdict())
                        if inserted:
                            run.inserted_count += 1
                        else:
                            run.skipped_count += 1
                        self._compare_yahoo_bar(symbol, bar.trade_date, bar, raw_payload.id, run.id)
                self.repo.finish_run(run, "succeeded")
                print(
                    f"yahoo validation {symbol} {start}..{end} "
                    f"fetched={run.fetched_count} inserted={run.inserted_count} "
                    f"skipped={run.skipped_count} failed={run.failed_count}"
                )
            except ProviderError as exc:
                failures += 1
                run.failed_count = 1
                self.repo.record_event(
                    exc.event_type,
                    str(exc),
                    "error",
                    "yahoo",
                    symbol=symbol,
                    collector_run_id=run.id,
                    observation_date=end,
                    details={"status": "validation_unavailable"},
                )
                self.repo.record_discrepancy(symbol, end, "massive", "yahoo", "close", "validation_unavailable")
                self.repo.finish_run(run, "failed", {"error": str(exc)})
                print(f"yahoo validation {symbol} {start}..{end} fetched=0 inserted=0 skipped=0 failed=1")
                if not continue_on_error:
                    raise
        self.session.commit()
        return failures

    def _daily_market(
        self,
        start: date,
        end: date,
        only: set[str],
        parent_run_id: int,
        dry_run: bool,
        continue_on_error: bool,
        resume: bool,
        force: bool,
    ) -> int:
        failures = 0
        profile_cfg = self.registry.profiles.get("daily_market", {})
        precedence = profile_cfg.get("canonical_source_precedence", ["massive", "yahoo"])
        price_basis = profile_cfg.get("price_basis", "split_adjusted")
        fallback_allowed = bool(profile_cfg.get("yahoo_fallback_allowed", False))
        for symbol, meta in self.registry.instruments.items():
            if only and symbol not in only and f"MASSIVE:{symbol}" not in only and f"POLYGON:{symbol}" not in only:
                continue
            if not meta.get("daily", True) or "daily_market" not in meta.get("collection_profiles", []):
                continue
            if resume and not force and self._completed_run_exists("massive_daily_bars", "instrument", symbol, start, end):
                print(f"resume skip massive {symbol} {start}..{end}: completed")
                continue
            run = self.repo.start_run("massive_daily_bars", "daily_market", "massive", parent_run_id, "instrument", symbol, start, end)
            try:
                payload, bars = self._with_retries(lambda: self.market_client.daily_bars(symbol, start, end))
                raw_payload = self.repo.raw_payload(
                    "massive",
                    "aggs/ticker/range/1/day",
                    {"symbol": symbol, "from": start.isoformat(), "to": end.isoformat(), "apiKey": "***REDACTED***"},
                    payload,
                )
                run.fetched_count = len(bars)
                if not dry_run:
                    for bar in bars:
                        if bar.open <= 0 or bar.high < bar.low or bar.close <= 0:
                            self.repo.record_event("suspicious_value_jump", f"Malformed market bar for {symbol}", "error", "massive", symbol=symbol, collector_run_id=run.id, observation_date=bar.trade_date)
                            run.failed_count += 1
                            continue
                        inserted, source_bar = self.repo.insert_daily_bar(symbol, "massive", raw_payload, bar.asdict())
                        if inserted:
                            run.inserted_count += 1
                        else:
                            run.skipped_count += 1
                        self.repo.canonicalize_daily_bar(
                            symbol,
                            source_bar.trade_date,
                            precedence,
                            price_basis=price_basis,
                            allow_yahoo_fallback=fallback_allowed,
                        )
                self.repo.finish_run(run, "succeeded" if run.failed_count == 0 else "failed")
                if run.failed_count == 0:
                    self.repo.resolve_events({"collector_failure", "rate_limit_hit"}, "massive", symbol=symbol)
                print(f"massive {symbol} {start}..{end} fetched={run.fetched_count} inserted={run.inserted_count} skipped={run.skipped_count} failed={run.failed_count}")
            except ProviderError as exc:
                failures += 1
                run.failed_count = 1
                self.repo.record_event(exc.event_type, str(exc), "error", "massive", symbol=symbol, collector_run_id=run.id)
                self.repo.finish_run(run, "failed", {"error": str(exc)})
                print(f"massive {symbol} {start}..{end} fetched=0 inserted=0 skipped=0 failed=1")
                if not continue_on_error:
                    raise
        self.session.commit()
        return failures

    def _completed_run_exists(
        self, collector_name: str, target_type: str, target_key: str, start: date, end: date
    ) -> bool:
        return (
            self.session.scalar(
                select(m.CollectorRun.id).where(
                    m.CollectorRun.collector_name == collector_name,
                    m.CollectorRun.target_type == target_type,
                    m.CollectorRun.target_key == target_key,
                    m.CollectorRun.date_from == start,
                    m.CollectorRun.date_to == end,
                    m.CollectorRun.status == "succeeded",
                )
            )
            is not None
        )

    def _with_retries(self, operation):
        attempts = int(self.registry.profiles.get("core", {}).get("retry_attempts", 3))
        delay = 0.25
        for attempt in range(1, attempts + 1):
            try:
                return operation()
            except RateLimitError:
                if attempt >= attempts:
                    raise
                time.sleep(delay)
                delay *= 2
            except ProviderError as exc:
                if "connection error" not in str(exc).lower() or attempt >= attempts:
                    raise
                time.sleep(delay)
                delay *= 2
        return operation()

    def _compare_yahoo_bar(
        self, symbol: str, trade_date: date, yahoo_bar, yahoo_raw_payload_id: int, collector_run_id: int | None
    ) -> None:
        policy = self._daily_validation_policy()
        rule_version = str(policy["comparison_rule_version"])
        allowed_pairs = {tuple(pair) for pair in policy["allowed_price_basis_pairs"]}
        yahoo_basis = getattr(yahoo_bar, "price_basis", None) or (
            yahoo_bar.get("price_basis") if isinstance(yahoo_bar, dict) else None
        )
        yahoo_basis = yahoo_basis or policy.get("source_price_basis", {}).get("yahoo", "unknown")
        inst = self.repo.instrument(symbol)
        massive = self.repo.source("massive")
        primary = self.session.scalar(
            select(m.MarketBarDaily).where(
                m.MarketBarDaily.instrument_id == inst.id,
                m.MarketBarDaily.trade_date == trade_date,
                m.MarketBarDaily.source_id == massive.id,
                m.MarketBarDaily.price_basis == policy.get("source_price_basis", {}).get("massive", "split_adjusted"),
            )
        )
        if primary is None:
            details = self._comparison_details(
                "validation source bar missing",
                "close",
                trade_date,
                None,
                self._bar_value(yahoo_bar, "close"),
                None,
                yahoo_basis,
                rule_version,
                "validation_unavailable",
            )
            self.repo.record_discrepancy(
                symbol,
                trade_date,
                "massive",
                "yahoo",
                "close",
                "validation_unavailable",
                validation_value=self._bar_value(yahoo_bar, "close"),
                raw_payload_id=yahoo_raw_payload_id,
                comparison_rule_version=rule_version,
                details=details,
            )
            self.repo.record_event(
                "source_discrepancy",
                f"Yahoo validation could not compare {symbol} {trade_date}: missing Massive bar.",
                "warning",
                "yahoo",
                symbol=symbol,
                collector_run_id=collector_run_id,
                observation_date=trade_date,
            )
            return
        primary_basis = primary.price_basis
        if (primary_basis, yahoo_basis) not in allowed_pairs:
            reason = f"incompatible price basis pair {primary_basis}/{yahoo_basis}"
            for field in ["close", "volume"]:
                self.repo.record_discrepancy(
                    symbol,
                    trade_date,
                    "massive",
                    "yahoo",
                    field,
                    "not_comparable",
                    self._model_value(primary, field),
                    self._bar_value(yahoo_bar, field),
                    yahoo_raw_payload_id,
                    comparison_rule_version=rule_version,
                    details=self._comparison_details(
                        reason,
                        field,
                        trade_date,
                        self._model_value(primary, field),
                        self._bar_value(yahoo_bar, field),
                        primary_basis,
                        yahoo_basis,
                        rule_version,
                        "not_comparable",
                    ),
                )
            return
        close_policy = policy["close"]
        volume_policy = policy["volume"]
        close_status = self._classify_difference(
            primary.close,
            self._bar_value(yahoo_bar, "close") or Decimal("0"),
            Decimal(str(close_policy["match_percent"])),
            Decimal(str(close_policy["minor_difference_percent"])),
            Decimal(str(close_policy["material_difference_percent"])),
        )
        volume_status = self._classify_difference(
            Decimal(primary.volume or 0),
            Decimal(self._bar_value(yahoo_bar, "volume") or 0),
            Decimal(str(volume_policy["match_percent"])),
            Decimal(str(volume_policy["minor_difference_percent"])),
            Decimal(str(volume_policy["material_difference_percent"])),
        )
        yahoo_close = self._bar_value(yahoo_bar, "close")
        yahoo_volume = self._bar_value(yahoo_bar, "volume")
        self.repo.record_discrepancy(
            symbol,
            trade_date,
            "massive",
            "yahoo",
            "close",
            close_status,
            primary.close,
            yahoo_close,
            yahoo_raw_payload_id,
            comparison_rule_version=rule_version,
            details=self._comparison_details(
                "allowed basis pair",
                "close",
                trade_date,
                primary.close,
                yahoo_close,
                primary_basis,
                yahoo_basis,
                rule_version,
                close_status,
            ),
        )
        self.repo.record_discrepancy(
            symbol,
            trade_date,
            "massive",
            "yahoo",
            "volume",
            volume_status,
            Decimal(primary.volume or 0),
            Decimal(yahoo_volume or 0),
            yahoo_raw_payload_id,
            comparison_rule_version=rule_version,
            details=self._comparison_details(
                "allowed basis pair",
                "volume",
                trade_date,
                Decimal(primary.volume or 0),
                Decimal(yahoo_volume or 0),
                primary_basis,
                yahoo_basis,
                rule_version,
                volume_status,
            ),
        )
        if "material_difference" in {close_status, volume_status}:
            self.repo.record_event(
                "source_discrepancy",
                f"Material Yahoo validation difference for {symbol} {trade_date}.",
                "warning",
                "yahoo",
                symbol=symbol,
                collector_run_id=collector_run_id,
                observation_date=trade_date,
                details={"close_status": close_status, "volume_status": volume_status, "rule_version": rule_version},
            )

    def _daily_validation_policy(self) -> dict[str, Any]:
        return self.registry.validation["daily_bars"]

    @staticmethod
    def _model_value(row: m.MarketBarDaily, field: str) -> Decimal | None:
        value = getattr(row, field)
        if value is None:
            return None
        return Decimal(str(value))

    @staticmethod
    def _bar_value(bar, field: str) -> Decimal | None:
        value = bar.get(field) if isinstance(bar, dict) else getattr(bar, field, None)
        if value is None:
            return None
        return Decimal(str(value))

    @staticmethod
    def _comparison_details(
        reason: str,
        field: str,
        trade_date: date,
        primary_value: Decimal | None,
        validation_value: Decimal | None,
        primary_price_basis: str | None,
        validation_price_basis: str | None,
        rule_version: str,
        status: str,
    ) -> dict[str, Any]:
        difference = None
        percentage = None
        if primary_value is not None and validation_value is not None:
            difference = abs(primary_value - validation_value)
            if primary_value != 0:
                percentage = difference / abs(primary_value)
        return {
            "primary_source": "massive",
            "validation_source": "yahoo",
            "field": field,
            "trade_date": trade_date.isoformat(),
            "primary_value": None if primary_value is None else str(primary_value),
            "validation_value": None if validation_value is None else str(validation_value),
            "absolute_difference": None if difference is None else str(difference),
            "percentage_difference": None if percentage is None else str(percentage),
            "primary_price_basis": primary_price_basis,
            "validation_price_basis": validation_price_basis,
            "comparison_rule_version": rule_version,
            "comparison_status": status,
            "reason": reason,
        }

    @staticmethod
    def _classify_difference(
        primary: Decimal,
        validation: Decimal,
        match_relative: Decimal,
        minor_relative: Decimal,
        material_relative: Decimal,
    ) -> str:
        if primary == validation:
            return "match"
        if primary == 0:
            return "material_difference"
        relative = abs(primary - validation) / abs(primary)
        if relative <= match_relative:
            return "match"
        if relative <= minor_relative:
            return "minor_difference"
        if relative >= material_relative:
            return "material_difference"
        return "minor_difference"

    def collect_fixture_quote(self, symbol: str) -> bool:
        if self.quote_client is None:
            return False
        payload, quote = self.quote_client.quote_snapshot(symbol)
        raw_payload = self.repo.raw_payload("yahoo", "quote_snapshot", {"symbol": symbol}, payload)
        inserted = self.repo.insert_quote_snapshot(symbol, "yahoo", raw_payload, quote)
        self.session.commit()
        return inserted

from __future__ import annotations

from datetime import date
from typing import Iterable

from sqlalchemy.orm import Session

from market_sniffer.collectors.base import FredClient, MarketDataClient, ProviderError, QuoteClient
from market_sniffer.db.repository import WarehouseRepository
from market_sniffer.services.registry_service import Registry


class BackfillService:
    def __init__(
        self,
        session: Session,
        registry: Registry,
        fred_client: FredClient,
        market_client: MarketDataClient,
        quote_client: QuoteClient | None = None,
    ):
        self.session = session
        self.registry = registry
        self.repo = WarehouseRepository(session)
        self.fred_client = fred_client
        self.market_client = market_client
        self.quote_client = quote_client

    def backfill(
        self,
        profile: str,
        start: date,
        end: date,
        only: Iterable[str] | None = None,
        dry_run: bool = False,
        continue_on_error: bool = False,
    ) -> int:
        only_set = set(only or [])
        parent = self.repo.start_run("backfill", profile, date_from=start, date_to=end)
        failures = 0
        try:
            if profile in {"core", "fred_macro"}:
                failures += self._fred(start, end, only_set, parent.id, dry_run, continue_on_error)
            if profile in {"core", "daily_market"}:
                failures += self._daily_market(start, end, only_set, parent.id, dry_run, continue_on_error)
            if profile == "core":
                failures += self._corporate_actions(start, end, only_set, parent.id, dry_run, continue_on_error)
                self._yahoo_validation_sample(start, end, only_set, parent.id, dry_run)
            self.repo.finish_run(parent, "failed" if failures else "succeeded")
            return failures
        except Exception as exc:
            self.repo.finish_run(parent, "failed", {"error": str(exc)})
            raise

    def _fred(self, start: date, end: date, only: set[str], parent_run_id: int, dry_run: bool, continue_on_error: bool) -> int:
        failures = 0
        for code, meta in self.registry.series.items():
            if only and code not in only and f"FRED:{code}" not in only:
                continue
            if meta.get("collection_profile") != "fred_macro" or not meta.get("backfill", True):
                continue
            run = self.repo.start_run("fred_observations", "fred_macro", "fred", parent_run_id, "series", code, start, end)
            try:
                payload, observations = self.fred_client.observations(meta["source_id"], start, end)
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
        self, start: date, end: date, only: set[str], parent_run_id: int, dry_run: bool, continue_on_error: bool
    ) -> int:
        failures = 0
        for symbol, meta in self.registry.instruments.items():
            if only and symbol not in only and f"MASSIVE:{symbol}" not in only and f"POLYGON:{symbol}" not in only:
                continue
            if not meta.get("daily", True):
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
                payload, actions = self.market_client.corporate_actions(symbol, start, end)
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
        self, start: date, end: date, only: set[str], parent_run_id: int, dry_run: bool
    ) -> None:
        sample = self.registry.profiles.get("validation", {}).get("sample_symbols", [])
        for symbol in sample:
            if only and symbol not in only and f"YAHOO:{symbol}" not in only:
                continue
            run = self.repo.start_run(
                "yahoo_validation_sample",
                "validation",
                "yahoo",
                parent_run_id,
                "instrument",
                symbol,
                start,
                end,
            )
            if not dry_run:
                self.repo.record_discrepancy(
                    symbol,
                    end,
                    "massive",
                    "yahoo",
                    "close",
                    "validation_unavailable",
                )
                self.repo.record_event(
                    "source_discrepancy",
                    "Yahoo validation sample is registered but live validation is disabled in v1.",
                    "info",
                    "yahoo",
                    symbol=symbol,
                    collector_run_id=run.id,
                    observation_date=end,
                    details={"status": "validation_unavailable"},
                )
            self.repo.finish_run(run, "succeeded")
            print(
                f"yahoo validation {symbol} {start}..{end} "
                "fetched=0 inserted=0 skipped=0 failed=0 status=validation_unavailable"
            )

    def _daily_market(self, start: date, end: date, only: set[str], parent_run_id: int, dry_run: bool, continue_on_error: bool) -> int:
        failures = 0
        for symbol, meta in self.registry.instruments.items():
            if only and symbol not in only and f"MASSIVE:{symbol}" not in only and f"POLYGON:{symbol}" not in only:
                continue
            if not meta.get("daily", True):
                continue
            run = self.repo.start_run("massive_daily_bars", "daily_market", "massive", parent_run_id, "instrument", symbol, start, end)
            try:
                payload, bars = self.market_client.daily_bars(symbol, start, end)
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
                        if self.repo.insert_daily_bar(symbol, "massive", raw_payload, bar.asdict()):
                            run.inserted_count += 1
                        else:
                            run.skipped_count += 1
                self.repo.finish_run(run, "succeeded" if run.failed_count == 0 else "failed")
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

    def collect_fixture_quote(self, symbol: str) -> bool:
        if self.quote_client is None:
            return False
        payload, quote = self.quote_client.quote_snapshot(symbol)
        raw_payload = self.repo.raw_payload("yahoo", "quote_snapshot", {"symbol": symbol}, payload)
        inserted = self.repo.insert_quote_snapshot(symbol, "yahoo", raw_payload, quote)
        self.session.commit()
        return inserted

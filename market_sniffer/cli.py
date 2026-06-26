from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from typing import Any, Callable, Sequence

from alembic import command
from alembic.config import Config
from sqlalchemy import select

from market_sniffer.collectors.fred import FixtureFredClient, FredApiClient
from market_sniffer.collectors.massive import FixtureMassiveClient, MassiveClient
from market_sniffer.collectors.yahoo import (
    FixtureYahooHistoricalClient,
    FixtureYahooQuoteClient,
    YahooHistoricalClient,
    YahooQuoteClient,
)
from market_sniffer.db import models as m
from market_sniffer.db.engine import assert_sqlite_pragmas, create_db_engine, session_factory
from market_sniffer.db.repository import WarehouseRepository
from market_sniffer.services.backfill import BackfillService
from market_sniffer.services.dates import (
    MarketCalendar,
    default_backfill_window,
    market_backfill_window,
    warn_if_possible_incomplete_market_date,
)
from market_sniffer.services.quality import DataQualityService
from market_sniffer.services.retention import RetentionService
from market_sniffer.services.metric_registry import MetricRegistryError, load_metric_registry
from market_sniffer.services.metrics import MetricCalculationService
from market_sniffer.services.registry_service import RegistryError, describe_key, load_registry
from market_sniffer.settings import PROJECT_ROOT, get_settings


def _session():
    settings = get_settings()
    engine = create_db_engine(settings.db_path)
    return session_factory(engine)(), engine


def _alembic_config() -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "market_sniffer/db/migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{get_settings().db_path}")
    return cfg


def cmd_db(args: argparse.Namespace) -> int:
    if args.db_command == "init":
        command.upgrade(_alembic_config(), "head")
        session, engine = _session()
        with session:
            repo = WarehouseRepository(session)
            repo.bootstrap_registry(load_registry())
            pragmas = assert_sqlite_pragmas(engine)
            print(f"database={get_settings().db_path}")
            print(f"pragmas={json.dumps(pragmas, sort_keys=True)}")
        return 0
    if args.db_command == "summary":
        session, _ = _session()
        with session:
            print(json.dumps(WarehouseRepository(session).counts(), indent=2, sort_keys=True))
        return 0
    raise SystemExit(f"unknown db command {args.db_command}")


def cmd_registry(args: argparse.Namespace) -> int:
    try:
        registry = load_registry()
        if args.registry_command == "validate":
            print(
                f"registry ok: sources={len(registry.sources)} series={len(registry.series)} "
                f"instruments={len(registry.instruments)} profiles={len(registry.profiles)}"
            )
            return 0
        if args.registry_command == "show":
            print(json.dumps(describe_key(registry, args.key), indent=2, sort_keys=True))
            return 0
    except RegistryError as exc:
        print(f"registry error: {exc}", file=sys.stderr)
        return 2
    raise SystemExit(f"unknown registry command {args.registry_command}")


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def cmd_backfill(args: argparse.Namespace) -> int:
    command.upgrade(_alembic_config(), "head")
    registry = load_registry()
    settings = get_settings()
    fred_start, fred_end = default_backfill_window(months=args.months)
    market_start, market_end = market_backfill_window(months=args.months)
    start = _parse_date(args.date_from) or (fred_start if args.profile == "fred_macro" else market_start)
    explicit_end = _parse_date(args.date_to)
    end = explicit_end or (fred_end if args.profile == "fred_macro" else market_end)
    if explicit_end and args.profile in {"core", "daily_market"}:
        warning = warn_if_possible_incomplete_market_date(explicit_end)
        if warning:
            print(f"warning: {warning}", file=sys.stderr)
    if args.profile in {"core", "daily_market"}:
        print(f"effective_market_end_date={end}")
    if args.profile in {"core", "fred_macro"}:
        print(f"effective_fred_end_date={explicit_end or fred_end}")
    fixture = args.fixture
    fred = FixtureFredClient() if fixture else FredApiClient(settings.fred_api_key)
    market = FixtureMassiveClient() if fixture else MassiveClient(settings.massive_api_key)
    quote = FixtureYahooQuoteClient() if fixture else YahooQuoteClient(settings.yahoo_enabled, settings.yahoo_quotes_enabled)
    yahoo_validation_enabled = bool(
        registry.sources.get("yahoo", {}).get("enabled", settings.yahoo_enabled)
        and settings.yahoo_historical_validation_enabled
    )
    validation = FixtureYahooHistoricalClient() if fixture else YahooHistoricalClient(yahoo_validation_enabled)
    if args.force and (not args.date_from or not args.date_to or not args.only):
        print("--force requires explicit --from, --to, and at least one --only target", file=sys.stderr)
        return 2
    session, _ = _session()
    with session:
        repo = WarehouseRepository(session)
        repo.bootstrap_registry(registry)
        service = BackfillService(session, registry, fred, market, quote, validation)
        failures = service.backfill(
            args.profile,
            start,
            end,
            only=args.only or None,
            dry_run=args.dry_run,
            continue_on_error=args.continue_on_error,
            fred_end=explicit_end or fred_end,
            resume=args.resume,
            force=args.force,
        )
    return 1 if failures and not args.continue_on_error else 0


def cmd_collect(args: argparse.Namespace) -> int:
    args.months = 0
    return cmd_backfill(args)


def cmd_validate_history(args: argparse.Namespace) -> int:
    command.upgrade(_alembic_config(), "head")
    settings = get_settings()
    registry = load_registry()
    start = _parse_date(args.date_from)
    end = _parse_date(args.date_to)
    if start is None or end is None:
        print("validate-history requires --from and --to", file=sys.stderr)
        return 2
    if not args.fixture and (not settings.massive_api_key or not settings.yahoo_historical_validation_enabled):
        print(
            "validate-history requires MASSIVE_API_KEY/POLYGON_API_KEY and "
            "YAHOO_HISTORICAL_VALIDATION_ENABLED=true unless --fixture is used",
            file=sys.stderr,
        )
        return 1
    market = FixtureMassiveClient() if args.fixture else MassiveClient(settings.massive_api_key)
    validation = FixtureYahooHistoricalClient() if args.fixture else YahooHistoricalClient(settings.yahoo_historical_validation_enabled)
    session, _ = _session()
    with session:
        repo = WarehouseRepository(session)
        repo.bootstrap_registry(registry)
        service = BackfillService(session, registry, FixtureFredClient(), market, validation_client=validation)
        summary = service.validate_history(args.symbols, start, end, continue_on_error=args.continue_on_error)
        rule_version = registry.validation["daily_bars"]["comparison_rule_version"]
        print(json.dumps({"comparison_rule_version": rule_version, "from": start, "to": end, "summary": summary}, indent=2, sort_keys=True, default=str))
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    session, engine = _session()
    with session:
        print(f"database={get_settings().db_path}")
        print(f"pragmas={json.dumps(assert_sqlite_pragmas(engine), sort_keys=True)}")
        print(json.dumps(WarehouseRepository(session).counts(), indent=2, sort_keys=True))
    return 0


def cmd_data_health(args: argparse.Namespace) -> int:
    session, _ = _session()
    with session:
        registry = load_registry()
        service = DataQualityService(session)
        new_events = service.check_quote_freshness(args.quote_max_age_minutes)
        summary = service.summary()
        unresolved = session.scalars(select(m.DataQualityEvent).where(m.DataQualityEvent.resolved.is_(False))).all()
        print(f"new_quote_freshness_events={new_events}")
        print(f"unresolved_quality_events={len(unresolved)}")
        print(
            json.dumps(
                {"active_validation": validation_summary(session, registry, current=True)},
                indent=2,
                sort_keys=True,
                default=str,
            )
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if unresolved and args.fail_on_events else 0


def validation_summary(
    session,
    registry,
    current: bool = True,
    symbols: list[str] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    active_rule = registry.validation["daily_bars"]["comparison_rule_version"]
    statuses = ["match", "minor_difference", "material_difference", "not_comparable", "validation_unavailable"]
    stmt = select(m.SourceDiscrepancy, m.Instrument.symbol).join(m.Instrument, m.SourceDiscrepancy.instrument_id == m.Instrument.id)
    if current:
        stmt = stmt.where(m.SourceDiscrepancy.comparison_rule_version == active_rule)
    if symbols:
        stmt = stmt.where(m.Instrument.symbol.in_(symbols))
    if date_from:
        stmt = stmt.where(m.SourceDiscrepancy.trade_date >= date_from)
    if date_to:
        stmt = stmt.where(m.SourceDiscrepancy.trade_date <= date_to)
    rows = session.execute(stmt).all()
    by_status = {status: 0 for status in statuses}
    by_field: dict[str, dict[str, int]] = {}
    by_symbol: dict[str, dict[str, int]] = {}
    by_rule: dict[str, dict[str, int]] = {}
    for discrepancy, symbol in rows:
        by_status[discrepancy.status] = by_status.get(discrepancy.status, 0) + 1
        by_field.setdefault(discrepancy.field_name, {status: 0 for status in statuses})[discrepancy.status] += 1
        by_symbol.setdefault(symbol, {status: 0 for status in statuses})[discrepancy.status] += 1
        by_rule.setdefault(discrepancy.comparison_rule_version, {status: 0 for status in statuses})[discrepancy.status] += 1
    legacy_stmt = select(m.SourceDiscrepancy).where(m.SourceDiscrepancy.comparison_rule_version != active_rule)
    if symbols:
        legacy_stmt = legacy_stmt.join(m.Instrument, m.SourceDiscrepancy.instrument_id == m.Instrument.id).where(m.Instrument.symbol.in_(symbols))
    if date_from:
        legacy_stmt = legacy_stmt.where(m.SourceDiscrepancy.trade_date >= date_from)
    if date_to:
        legacy_stmt = legacy_stmt.where(m.SourceDiscrepancy.trade_date <= date_to)
    legacy_count = len(session.scalars(legacy_stmt).all())
    return {
        "active_rule_version": active_rule,
        "mode": "current" if current else "all_rules",
        "symbols": symbols or "all",
        "from": date_from,
        "to": date_to,
        "counts_by_status": by_status,
        "counts_by_field": by_field,
        "counts_by_symbol": by_symbol,
        "counts_by_rule": by_rule,
        "legacy_audit_row_count": legacy_count,
    }


def cmd_validation(args: argparse.Namespace) -> int:
    registry = load_registry()
    current = not args.all_rules
    date_from = _parse_date(args.date_from)
    date_to = _parse_date(args.date_to)
    session, _ = _session()
    with session:
        print(
            json.dumps(
                validation_summary(session, registry, current=current, symbols=args.symbols, date_from=date_from, date_to=date_to),
                indent=2,
                sort_keys=True,
                default=str,
            )
        )
    return 0


def cmd_retention(args: argparse.Namespace) -> int:
    session, _ = _session()
    with session:
        result = RetentionService(session).prune_raw_payloads(
            args.scope,
            dry_run=args.dry_run or not args.confirm,
            retention_days=args.retention_days,
        )
        print(json.dumps(result.__dict__, indent=2, sort_keys=True))
    return 0


def cmd_verify_foundation(args: argparse.Namespace) -> int:
    verify_db_path = args.db_path or f"/tmp/market_sniffer_verify_{os.getpid()}.sqlite3"
    os.environ["MARKET_SNIFFER_DB_PATH"] = verify_db_path
    settings = get_settings()
    if not args.fixture and (not settings.fred_api_key or not settings.massive_api_key):
        print("verify-foundation requires FRED_API_KEY and MASSIVE_API_KEY/POLYGON_API_KEY unless --fixture is used")
        return 1
    if not args.fixture:
        live_status = _live_source_checks(settings, require_yahoo=True)
        print(json.dumps({"live_capability": live_status}, indent=2, sort_keys=True, default=str))
        if any(not item["success"] for item in live_status):
            return 1
    command.upgrade(_alembic_config(), "head")
    registry = load_registry()
    start, end = MarketCalendar().recent_completed_range(args.days)
    fred = FixtureFredClient() if args.fixture else FredApiClient(settings.fred_api_key)
    market = FixtureMassiveClient() if args.fixture else MassiveClient(settings.massive_api_key)
    quote = FixtureYahooQuoteClient() if args.fixture else YahooQuoteClient(settings.yahoo_enabled, settings.yahoo_quotes_enabled)
    validation = (
        FixtureYahooHistoricalClient()
        if args.fixture
        else YahooHistoricalClient(enabled=settings.yahoo_historical_validation_enabled)
    )
    targets = ["DGS10", "BAMLH0A0HYM2", "SPY", "QQQ"]
    session, _ = _session()
    with session:
        repo = WarehouseRepository(session)
        repo.bootstrap_registry(registry)
        service = BackfillService(session, registry, fred, market, quote, validation)
        failures = service.backfill("core", start, end, only=targets, continue_on_error=True)
        first_counts = repo.counts()
        rerun_failures = service.backfill("core", start, end, only=targets, continue_on_error=True, resume=True)
        second_counts = repo.counts()
        DataQualityService(session).check_quote_freshness()
        sample_bar = session.scalar(select(m.CanonicalMarketBarDaily).limit(1))
        sample_obs = session.scalar(select(m.CanonicalObservation).limit(1))
        report = {
            "range": {"from": start.isoformat(), "to": end.isoformat()},
            "database": verify_db_path,
            "failures": failures,
            "rerun_failures": rerun_failures,
            "first_counts": first_counts,
            "second_counts": second_counts,
            "lineage_samples": {
                "canonical_bar": {
                    "source_market_bar_id": sample_bar.source_market_bar_id,
                    "raw_payload_id": sample_bar.raw_payload_id,
                }
                if sample_bar
                else None,
                "fred_observation": {
                    "raw_observation_id": sample_obs.raw_observation_id,
                    "raw_payload_id": sample_obs.raw_payload_id,
                    "is_latest_vintage": sample_obs.is_latest_vintage,
                }
                if sample_obs
                else None,
            },
        }
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 1 if failures or rerun_failures else 0


def cmd_inspect(args: argparse.Namespace) -> int:
    session, _ = _session()
    start = _parse_date(args.date_from)
    end = _parse_date(args.date_to)
    with session:
        if args.inspect_type == "series":
            key = args.key.split(":", 1)[1] if ":" in args.key else args.key
            series = session.scalar(select(m.DataSeries).where(m.DataSeries.series_code == key))
            if not series:
                print(f"series not found: {args.key}", file=sys.stderr)
                return 2
            series_stmt = select(m.CanonicalObservation).where(m.CanonicalObservation.series_id == series.id)
            if start:
                series_stmt = series_stmt.where(m.CanonicalObservation.observation_date >= start)
            if end:
                series_stmt = series_stmt.where(m.CanonicalObservation.observation_date <= end)
            rows = session.scalars(
                series_stmt.order_by(m.CanonicalObservation.observation_date).limit(args.limit)
            ).all()
            for row in rows:
                print(f"{series.series_code} {row.observation_date} value={row.value} unit={row.unit} source_id={row.source_id} raw_observation_id={row.raw_observation_id}")
            return 0
        if args.inspect_type == "instrument":
            key = args.key.split(":", 1)[1] if ":" in args.key else args.key
            instrument = session.scalar(select(m.Instrument).where(m.Instrument.symbol == key))
            if not instrument:
                print(f"instrument not found: {args.key}", file=sys.stderr)
                return 2
            bar_stmt = select(m.MarketBarDaily).where(m.MarketBarDaily.instrument_id == instrument.id)
            if start:
                bar_stmt = bar_stmt.where(m.MarketBarDaily.trade_date >= start)
            if end:
                bar_stmt = bar_stmt.where(m.MarketBarDaily.trade_date <= end)
            rows = session.scalars(bar_stmt.order_by(m.MarketBarDaily.trade_date).limit(args.limit)).all()
            for row in rows:
                print(f"{instrument.symbol} {row.trade_date} close={row.close} volume={row.volume} source_id={row.source_id} raw_payload_id={row.raw_payload_id}")
            return 0
    return 2


def cmd_validate_sources(args: argparse.Namespace) -> int:
    settings = get_settings()
    registry = load_registry()
    missing: list[str] = []
    if registry.sources["fred"].get("enabled") and not settings.fred_api_key:
        missing.append("FRED_API_KEY")
    if registry.sources["massive"].get("enabled") and not settings.massive_api_key:
        missing.append("MASSIVE_API_KEY or POLYGON_API_KEY")
    if settings.yahoo_historical_validation_enabled and not settings.yahoo_enabled:
        missing.append("YAHOO_ENABLED must be true before YAHOO_HISTORICAL_VALIDATION_ENABLED")
    if settings.yahoo_quotes_enabled and not settings.yahoo_enabled:
        missing.append("YAHOO_ENABLED must be true before YAHOO_QUOTES_ENABLED")
    if missing and not args.live:
        print("missing or invalid capability configuration:")
        for item in missing:
            print(f"- {item}")
        return 1 if not args.allow_missing else 0
    if args.live:
        if missing:
            print("missing required live capability configuration:")
            for item in missing:
                print(f"- {item}")
            return 1
        results = _live_source_checks(
            settings,
            require_yahoo=bool(
                registry.sources.get("yahoo", {}).get("enabled", False)
                and settings.yahoo_historical_validation_enabled
            ),
        )
        print(json.dumps(results, indent=2, sort_keys=True, default=str))
        return 1 if any(not item["success"] for item in results) else 0
    print("source capability configuration ok")
    return 0


def cmd_metrics(args: argparse.Namespace) -> int:
    try:
        registry = load_metric_registry()
    except MetricRegistryError as exc:
        print(f"metric registry error: {exc}", file=sys.stderr)
        return 2
    if args.metrics_command == "validate":
        print(
            f"metric registry ok: enabled_metrics={len(registry.enabled_metrics)} "
            f"enabled_evidence_rules={len(registry.enabled_rules)}"
        )
        return 0
    command.upgrade(_alembic_config(), "head")
    session, _ = _session()
    with session:
        service = MetricCalculationService(session, registry)
        if args.metrics_command == "list":
            for item in service.list_metrics():
                print(
                    f"{item['metric_code']} category={item['category']} formula={item['formula']} "
                    f"version={item['formula_version']} enabled={item['enabled']}"
                )
            return 0
        if args.metrics_command == "calculate":
            as_of = _parse_date(args.as_of)
            if as_of is None:
                print("metrics calculate requires --as-of", file=sys.stderr)
                return 2
            print(json.dumps(service.calculate_date(as_of), indent=2, sort_keys=True, default=str))
            return 0
        if args.metrics_command == "backfill":
            summary = service.backfill(
                profile=args.profile,
                start=_parse_date(args.date_from),
                end=_parse_date(args.date_to),
                only=args.only,
            )
            print(json.dumps(summary, indent=2, sort_keys=True, default=str))
            return 0 if summary.get("failed", 0) == 0 else 1
        if args.metrics_command == "inspect":
            return _cmd_metric_inspect(session, args.metric_code, _parse_date(args.date_from), _parse_date(args.date_to), args.limit)
        if args.metrics_command == "health":
            print(json.dumps(service.health(), indent=2, sort_keys=True, default=str))
            return 0
    return 2


def _cmd_metric_inspect(session, metric_code: str, start: date | None, end: date | None, limit: int) -> int:
    definition = session.scalar(select(m.MetricDefinition).where(m.MetricDefinition.metric_code == metric_code))
    if definition is None:
        print(f"metric not found: {metric_code}", file=sys.stderr)
        return 2
    stmt = select(m.MetricObservation).where(m.MetricObservation.metric_definition_id == definition.id)
    if start:
        stmt = stmt.where(m.MetricObservation.as_of_date >= start)
    if end:
        stmt = stmt.where(m.MetricObservation.as_of_date <= end)
    rows = session.scalars(stmt.order_by(m.MetricObservation.as_of_date.desc()).limit(limit)).all()
    for row in rows:
        print(
            f"{metric_code} {row.as_of_date} value={row.value_numeric} "
            f"quality={row.quality_status} formula_version={row.formula_version}"
        )
    return 0


def cmd_evidence(args: argparse.Namespace) -> int:
    command.upgrade(_alembic_config(), "head")
    session, _ = _session()
    with session:
        if args.evidence_command == "recent":
            recent_start = date.today() - timedelta(days=args.days)
            recent_stmt = (
                select(m.EvidenceEvent, m.MetricDefinition.metric_code)
                .join(m.MetricDefinition, m.EvidenceEvent.metric_definition_id == m.MetricDefinition.id)
                .where(m.EvidenceEvent.as_of_date >= recent_start)
                .order_by(m.EvidenceEvent.as_of_date.desc(), m.EvidenceEvent.id.desc())
            )
            return _print_evidence_rows(session.execute(recent_stmt).all(), args.limit)
        if args.evidence_command == "inspect":
            event = session.get(m.EvidenceEvent, args.event_id)
            if event is None:
                print(f"evidence event not found: {args.event_id}", file=sys.stderr)
                return 2
            definition = session.get(m.MetricDefinition, event.metric_definition_id)
            payload = {
                "id": event.id,
                "event_code": event.event_code,
                "event_type": event.event_type,
                "severity": event.severity,
                "metric_code": definition.metric_code if definition else None,
                "as_of_date": event.as_of_date,
                "headline": event.headline,
                "detail": event.detail,
                "value_numeric": event.value_numeric,
                "prior_value_numeric": event.prior_value_numeric,
                "threshold_numeric": event.threshold_numeric,
                "evidence": event.evidence_json,
            }
            print(json.dumps(payload, indent=2, sort_keys=True, default=str))
            return 0
        if args.evidence_command == "evaluate":
            as_of = _parse_date(args.as_of)
            if as_of is None:
                print("evidence evaluate requires --as-of", file=sys.stderr)
                return 2
            service = MetricCalculationService(session, load_metric_registry())
            res = service.calculate_date(as_of)
            print(json.dumps(res, indent=2, sort_keys=True))
            return 0
        if args.evidence_command == "summary":
            summary_start = _parse_date(args.date_from)
            summary_end = _parse_date(args.date_to)
            if summary_start is None or summary_end is None:
                print("evidence summary requires --from and --to", file=sys.stderr)
                return 2
            summary_stmt = select(m.EvidenceEvent).where(
                m.EvidenceEvent.as_of_date >= summary_start,
                m.EvidenceEvent.as_of_date <= summary_end,
            )
            rows = session.scalars(summary_stmt).all()
            by_type: dict[str, int] = {}
            by_severity: dict[str, int] = {}
            for event in rows:
                by_type[event.event_type] = by_type.get(event.event_type, 0) + 1
                by_severity[event.severity] = by_severity.get(event.severity, 0) + 1
            print(
                json.dumps(
                    {
                        "from": summary_start,
                        "to": summary_end,
                        "count": len(rows),
                        "by_type": by_type,
                        "by_severity": by_severity,
                    },
                    indent=2,
                    sort_keys=True,
                    default=str,
                )
            )
            return 0
    return 2


def cmd_web(args: argparse.Namespace) -> int:
    from market_sniffer.web import create_app
    app = create_app({"fixture": args.fixture})
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0



def _print_evidence_rows(rows: Sequence[Any], limit: int) -> int:
    for event, metric_code in rows[:limit]:
        print(
            f"{event.id} {event.as_of_date} {event.severity} {event.event_type} "
            f"{metric_code} value={event.value_numeric} headline={event.headline}"
        )
    return 0


def _live_source_checks(settings, require_yahoo: bool) -> list[dict[str, object]]:
    _latest_start, end = MarketCalendar().recent_completed_range(1)
    start = end - timedelta(days=30)
    checks: list[dict[str, object]] = []
    operations: list[tuple[str, str, Callable[[], tuple[dict[str, Any], Sequence[Any]]]]] = [
        ("fred", "series/observations DGS10", lambda: FredApiClient(settings.fred_api_key).observations("DGS10", start, end)),
        ("massive", "daily_bars SPY", lambda: MassiveClient(settings.massive_api_key).daily_bars("SPY", start, end)),
    ]
    for source, operation, func in operations:
        try:
            payload, rows = func()
            row_count = len(rows)
            checks.append(
                {
                    "source": source,
                    "operation": operation,
                    "success": row_count > 0,
                    "row_count": row_count,
                    "status": payload.get("status") if isinstance(payload, dict) else None,
                    "failure_class": None if row_count > 0 else "empty_response",
                    "required_action": None if row_count > 0 else "check provider entitlement/date availability",
                }
            )
        except Exception as exc:
            checks.append(
                {
                    "source": source,
                    "operation": operation,
                    "success": False,
                    "failure_class": exc.__class__.__name__,
                    "status": None,
                    "required_action": "verify credentials, entitlement, rate limits, and provider availability",
                }
            )
    if require_yahoo:
        try:
            payload, rows = YahooHistoricalClient(enabled=True).daily_bars("SPY", start, end)
            checks.append(
                {
                    "source": "yahoo",
                    "operation": "historical_daily_bars SPY",
                    "success": bool(rows),
                    "row_count": len(rows),
                    "status": "ok" if rows else "empty",
                    "failure_class": None if rows else "empty_response",
                    "required_action": None if rows else "check Yahoo availability",
                }
            )
        except Exception as exc:
            checks.append(
                {
                    "source": "yahoo",
                    "operation": "historical_daily_bars SPY",
                    "success": False,
                    "failure_class": exc.__class__.__name__,
                    "status": None,
                    "required_action": "check yfinance dependency/network/provider availability",
                }
            )
    return checks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="market-sniffer")
    sub = parser.add_subparsers(dest="command", required=True)

    db = sub.add_parser("db")
    db_sub = db.add_subparsers(dest="db_command", required=True)
    db_sub.add_parser("init")
    db_sub.add_parser("summary")
    db.set_defaults(func=cmd_db)

    registry = sub.add_parser("registry")
    registry_sub = registry.add_subparsers(dest="registry_command", required=True)
    registry_sub.add_parser("validate")
    show = registry_sub.add_parser("show")
    show.add_argument("key")
    registry.set_defaults(func=cmd_registry)

    backfill = sub.add_parser("backfill")
    backfill.add_argument("--profile", default="core")
    backfill.add_argument("--months", type=int, default=24)
    backfill.add_argument("--from", dest="date_from")
    backfill.add_argument("--to", dest="date_to")
    backfill.add_argument("--only", action="append")
    backfill.add_argument("--dry-run", action="store_true")
    backfill.add_argument("--continue-on-error", action="store_true")
    backfill.add_argument("--force", action="store_true", help="Reserved for explicit reload workflows; v1 remains idempotent.")
    backfill.add_argument("--resume", action="store_true", help="Idempotent inserts make interrupted ranges safe to rerun.")
    backfill.add_argument("--fixture", action="store_true", help="Use deterministic local fixture clients instead of external APIs.")
    backfill.set_defaults(func=cmd_backfill)

    collect = sub.add_parser("collect")
    collect.add_argument("--profile", default="core")
    collect.add_argument("--from", dest="date_from")
    collect.add_argument("--to", dest="date_to")
    collect.add_argument("--only", action="append")
    collect.add_argument("--dry-run", action="store_true")
    collect.add_argument("--continue-on-error", action="store_true")
    collect.add_argument("--force", action="store_true")
    collect.add_argument("--resume", action="store_true")
    collect.add_argument("--fixture", action="store_true")
    collect.set_defaults(func=cmd_collect)

    validate_history = sub.add_parser("validate-history")
    validate_history.add_argument("--symbols", action="append", required=True)
    validate_history.add_argument("--from", dest="date_from", required=True)
    validate_history.add_argument("--to", dest="date_to", required=True)
    validate_history.add_argument("--continue-on-error", action="store_true")
    validate_history.add_argument("--fixture", action="store_true")
    validate_history.set_defaults(func=cmd_validate_history)

    validation_cmd = sub.add_parser("validation")
    validation_sub = validation_cmd.add_subparsers(dest="validation_command", required=True)
    validation_summary_parser = validation_sub.add_parser("summary")
    mode = validation_summary_parser.add_mutually_exclusive_group()
    mode.add_argument("--current", action="store_true", help="Show only the active comparison rule version.")
    mode.add_argument("--all-rules", action="store_true", help="Show current and legacy/audit comparison rule versions.")
    validation_summary_parser.add_argument("--symbols", action="append")
    validation_summary_parser.add_argument("--from", dest="date_from")
    validation_summary_parser.add_argument("--to", dest="date_to")
    validation_summary_parser.set_defaults(func=cmd_validation)

    status = sub.add_parser("status")
    status.set_defaults(func=cmd_status)

    health = sub.add_parser("data-health")
    health.add_argument("--quote-max-age-minutes", type=int, default=20)
    health.add_argument("--fail-on-events", action="store_true")
    health.set_defaults(func=cmd_data_health)

    retention = sub.add_parser("retention")
    retention_sub = retention.add_subparsers(dest="retention_command", required=True)
    prune = retention_sub.add_parser("prune-raw-payloads")
    prune.add_argument("--scope", choices=["quote", "intraday", "validation"], required=True)
    prune.add_argument("--retention-days", type=int)
    prune.add_argument("--dry-run", action="store_true")
    prune.add_argument("--confirm", action="store_true", help="Actually prune eligible payload bodies.")
    prune_alias = retention_sub.add_parser("prune")
    prune_alias.add_argument("--scope", choices=["quote", "intraday", "validation"], required=True)
    prune_alias.add_argument("--retention-days", type=int)
    prune_alias.add_argument("--dry-run", action="store_true")
    prune_alias.add_argument("--confirm", action="store_true", help="Actually prune eligible payload bodies.")
    retention.set_defaults(func=cmd_retention)

    inspect = sub.add_parser("inspect")
    inspect.add_argument("inspect_type", choices=["series", "instrument"])
    inspect.add_argument("key")
    inspect.add_argument("--from", dest="date_from")
    inspect.add_argument("--to", dest="date_to")
    inspect.add_argument("--limit", type=int, default=20)
    inspect.set_defaults(func=cmd_inspect)

    validate = sub.add_parser("validate-sources")
    validate.add_argument("--allow-missing", action="store_true")
    validate.add_argument("--live", action="store_true")
    validate.set_defaults(func=cmd_validate_sources)

    verify = sub.add_parser("verify-foundation")
    verify.add_argument("--days", type=int, default=5)
    verify.add_argument("--db-path")
    verify.add_argument("--fixture", action="store_true")
    verify.add_argument("--continue-on-error", action="store_true")
    verify.set_defaults(func=cmd_verify_foundation)

    metrics = sub.add_parser("metrics")
    metrics_sub = metrics.add_subparsers(dest="metrics_command", required=True)
    metrics_sub.add_parser("list")
    metrics_sub.add_parser("validate")
    metrics_backfill = metrics_sub.add_parser("backfill")
    metrics_backfill.add_argument("--profile", default="core")
    metrics_backfill.add_argument("--from", dest="date_from")
    metrics_backfill.add_argument("--to", dest="date_to")
    metrics_backfill.add_argument("--only", action="append")
    metrics_calculate = metrics_sub.add_parser("calculate")
    metrics_calculate.add_argument("--as-of", required=True)
    metrics_inspect = metrics_sub.add_parser("inspect")
    metrics_inspect.add_argument("metric_code")
    metrics_inspect.add_argument("--from", dest="date_from")
    metrics_inspect.add_argument("--to", dest="date_to")
    metrics_inspect.add_argument("--limit", type=int, default=20)
    metrics_sub.add_parser("health")
    metrics.set_defaults(func=cmd_metrics)

    evidence = sub.add_parser("evidence")
    evidence_sub = evidence.add_subparsers(dest="evidence_command", required=True)
    evidence_recent = evidence_sub.add_parser("recent")
    evidence_recent.add_argument("--days", type=int, default=7)
    evidence_recent.add_argument("--limit", type=int, default=50)
    evidence_inspect = evidence_sub.add_parser("inspect")
    evidence_inspect.add_argument("event_id", type=int)
    evidence_summary = evidence_sub.add_parser("summary")
    evidence_summary.add_argument("--from", dest="date_from", required=True)
    evidence_summary.add_argument("--to", dest="date_to", required=True)
    evidence_evaluate = evidence_sub.add_parser("evaluate")
    evidence_evaluate.add_argument("--as-of", required=True)
    evidence.set_defaults(func=cmd_evidence)

    web = sub.add_parser("web")
    web_sub = web.add_subparsers(dest="web_command", required=True)
    serve = web_sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--debug", action="store_true")
    serve.add_argument("--fixture", action="store_true")
    web.set_defaults(func=cmd_web)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

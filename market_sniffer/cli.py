from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from alembic import command
from alembic.config import Config
from sqlalchemy import select

from market_sniffer.collectors.fred import FixtureFredClient, FredApiClient
from market_sniffer.collectors.massive import FixtureMassiveClient, MassiveClient
from market_sniffer.collectors.yahoo import FixtureYahooQuoteClient, YahooQuoteClient
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
    session, _ = _session()
    with session:
        repo = WarehouseRepository(session)
        repo.bootstrap_registry(registry)
        service = BackfillService(session, registry, fred, market, quote)
        failures = service.backfill(
            args.profile,
            start,
            end,
            only=args.only or None,
            dry_run=args.dry_run,
            continue_on_error=args.continue_on_error,
            fred_end=explicit_end or fred_end,
        )
    return 1 if failures and not args.continue_on_error else 0


def cmd_collect(args: argparse.Namespace) -> int:
    args.months = 0
    today = date.today().isoformat()
    args.date_from = args.date_from or today
    args.date_to = args.date_to or today
    return cmd_backfill(args)


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
        service = DataQualityService(session)
        new_events = service.check_quote_freshness(args.quote_max_age_minutes)
        summary = service.summary()
        unresolved = session.scalars(select(m.DataQualityEvent).where(m.DataQualityEvent.resolved.is_(False))).all()
        print(f"new_quote_freshness_events={new_events}")
        print(f"unresolved_quality_events={len(unresolved)}")
        print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if unresolved and args.fail_on_events else 0


def cmd_retention(args: argparse.Namespace) -> int:
    session, _ = _session()
    with session:
        result = RetentionService(session).prune_raw_payloads(
            args.scope,
            dry_run=args.dry_run,
            retention_days=args.retention_days,
        )
        print(json.dumps(result.__dict__, indent=2, sort_keys=True))
    return 0


def cmd_verify_foundation(args: argparse.Namespace) -> int:
    settings = get_settings()
    if not args.fixture and (not settings.fred_api_key or not settings.massive_api_key):
        print("verify-foundation requires FRED_API_KEY and MASSIVE_API_KEY/POLYGON_API_KEY unless --fixture is used")
        return 1
    command.upgrade(_alembic_config(), "head")
    registry = load_registry()
    start, end = MarketCalendar().recent_completed_range(args.days)
    fred = FixtureFredClient() if args.fixture else FredApiClient(settings.fred_api_key)
    market = FixtureMassiveClient() if args.fixture else MassiveClient(settings.massive_api_key)
    quote = FixtureYahooQuoteClient() if args.fixture else YahooQuoteClient(settings.yahoo_enabled, settings.yahoo_quotes_enabled)
    targets = ["DGS10", "BAMLH0A0HYM2", "SPY", "QQQ"]
    session, _ = _session()
    with session:
        repo = WarehouseRepository(session)
        repo.bootstrap_registry(registry)
        service = BackfillService(session, registry, fred, market, quote)
        failures = service.backfill("core", start, end, only=targets, continue_on_error=args.continue_on_error)
        first_counts = repo.counts()
        rerun_failures = service.backfill("core", start, end, only=targets, continue_on_error=args.continue_on_error)
        second_counts = repo.counts()
        DataQualityService(session).check_quote_freshness()
        sample_bar = session.scalar(select(m.CanonicalMarketBarDaily).limit(1))
        sample_obs = session.scalar(select(m.CanonicalObservation).limit(1))
        report = {
            "range": {"from": start.isoformat(), "to": end.isoformat()},
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
    if settings.yahoo_quotes_enabled and not settings.yahoo_enabled:
        missing.append("YAHOO_ENABLED must be true before YAHOO_QUOTES_ENABLED")
    if missing:
        print("missing or invalid capability configuration:")
        for item in missing:
            print(f"- {item}")
        return 1 if not args.allow_missing else 0
    print("source capability configuration ok")
    return 0


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
    validate.set_defaults(func=cmd_validate_sources)

    verify = sub.add_parser("verify-foundation")
    verify.add_argument("--days", type=int, default=5)
    verify.add_argument("--fixture", action="store_true")
    verify.add_argument("--continue-on-error", action="store_true")
    verify.set_defaults(func=cmd_verify_foundation)
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

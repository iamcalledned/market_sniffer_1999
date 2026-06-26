from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    db_path: Path
    log_level: str
    massive_api_key: str | None
    fred_api_key: str | None
    yahoo_enabled: bool
    yahoo_quotes_enabled: bool


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_settings() -> Settings:
    db_path = Path(os.getenv("MARKET_SNIFFER_DB_PATH", "runtime/market_sniffer.sqlite3"))
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    return Settings(
        db_path=db_path,
        log_level=os.getenv("MARKET_SNIFFER_LOG_LEVEL", "INFO"),
        massive_api_key=os.getenv("MASSIVE_API_KEY") or os.getenv("POLYGON_API_KEY"),
        fred_api_key=os.getenv("FRED_API_KEY"),
        yahoo_enabled=_bool_env("YAHOO_ENABLED", False),
        yahoo_quotes_enabled=_bool_env("YAHOO_QUOTES_ENABLED", False),
    )


def redact_secrets(value: object) -> object:
    if isinstance(value, dict):
        return {k: ("***REDACTED***" if "key" in k.lower() or "token" in k.lower() else redact_secrets(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_secrets(v) for v in value]
    return value

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from market_sniffer.settings import PROJECT_ROOT


@dataclass(frozen=True)
class Registry:
    sources: dict[str, dict[str, Any]]
    series: dict[str, dict[str, Any]]
    instruments: dict[str, dict[str, Any]]
    profiles: dict[str, dict[str, Any]]
    validation: dict[str, Any]


class RegistryError(ValueError):
    pass


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: UniqueKeyLoader, node: yaml.Node, deep: bool = False) -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    for key_node, value_node in node.value:  # type: ignore[attr-defined]
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise RegistryError(f"duplicate registry key {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.load(fh, Loader=UniqueKeyLoader) or {}
    if not isinstance(data, dict):
        raise RegistryError(f"{path} must contain a YAML mapping")
    return data


def load_registry(config_dir: Path | None = None) -> Registry:
    root = config_dir or PROJECT_ROOT / "config"
    collection_config = _load_yaml(root / "collection_profiles.yaml")
    sources = _load_yaml(root / "source_registry.yaml").get("sources", {})
    series = _load_yaml(root / "series_registry.yaml").get("series", {})
    instruments = _load_yaml(root / "instrument_registry.yaml").get("instruments", {})
    profiles = collection_config.get("profiles", {})
    validation = collection_config.get("validation", {})
    registry = Registry(sources=sources, series=series, instruments=instruments, profiles=profiles, validation=validation)
    validate_registry(registry)
    return registry


VALID_PRICE_BASES = {"raw", "split_adjusted", "total_return_adjusted", "provider_adjusted_unknown", "unknown"}
VALID_DISCREPANCY_STATUSES = {
    "match",
    "minor_difference",
    "material_difference",
    "not_comparable",
    "validation_unavailable",
}


def validate_registry(registry: Registry) -> None:
    required_profiles = {
        "core",
        "daily_market",
        "fred_macro",
        "validation",
        "future_intraday_watchlist",
        "future_realtime_quote_watchlist",
    }
    missing_profiles = required_profiles - set(registry.profiles)
    if missing_profiles:
        raise RegistryError(f"missing collection profiles: {sorted(missing_profiles)}")
    for code, source in registry.sources.items():
        for field in [
            "display_name",
            "enabled",
            "canonical_responsibilities",
            "validation_responsibilities",
            "failure_behavior",
            "future_quote_capability",
            "source_precedence",
        ]:
            if field not in source:
                raise RegistryError(f"source {code} missing {field}")
    for code, item in registry.series.items():
        for field in [
            "source",
            "source_id",
            "category",
            "frequency",
            "unit",
            "canonical_source",
            "collection_profile",
            "backfill",
            "vintage_tracking",
            "why",
        ]:
            if field not in item:
                raise RegistryError(f"series {code} missing {field}")
        if item["source"] not in registry.sources:
            raise RegistryError(f"series {code} references unknown source {item['source']}")
        if item["canonical_source"] not in registry.sources:
            raise RegistryError(f"series {code} references unknown canonical source {item['canonical_source']}")
        if item["collection_profile"] not in registry.profiles:
            raise RegistryError(f"series {code} references unknown profile {item['collection_profile']}")
    for symbol, item in registry.instruments.items():
        for field in [
            "asset_class",
            "currency",
            "collection_profiles",
            "daily",
            "future_intraday",
            "future_quote",
            "why",
        ]:
            if field not in item:
                raise RegistryError(f"instrument {symbol} missing {field}")
        for profile in item.get("collection_profiles", []):
            if profile not in registry.profiles:
                raise RegistryError(f"instrument {symbol} references unknown profile {profile}")
        if item.get("future_quote") and "future_realtime_quote_watchlist" not in registry.profiles:
            raise RegistryError(f"instrument {symbol} has future_quote without quote profile")
        if item.get("future_intraday") and "future_intraday_watchlist" not in registry.profiles:
            raise RegistryError(f"instrument {symbol} has future_intraday without intraday profile")
    for name, profile in registry.profiles.items():
        if "description" not in profile:
            raise RegistryError(f"profile {name} missing description")
        if profile.get("source") and profile["source"] not in registry.sources:
            raise RegistryError(f"profile {name} references unknown source {profile['source']}")
        if name == "daily_market" and not profile.get("canonical_source_precedence"):
            raise RegistryError("daily_market profile missing canonical_source_precedence")
        if profile.get("retention_class") and profile["retention_class"] not in {"quote", "intraday", "validation"}:
            raise RegistryError(f"profile {name} has invalid retention_class {profile['retention_class']}")
        if profile.get("retention_days") is not None and int(profile["retention_days"]) <= 0:
            raise RegistryError(f"profile {name} retention_days must be positive")
        if profile.get("canonical_source_precedence"):
            for source_code in profile["canonical_source_precedence"]:
                if source_code not in registry.sources:
                    raise RegistryError(f"profile {name} precedence references unknown source {source_code}")
        if profile.get("price_basis") and profile["price_basis"] not in VALID_PRICE_BASES:
            raise RegistryError(f"profile {name} has invalid price_basis {profile['price_basis']}")
    daily_validation = registry.validation.get("daily_bars")
    if not isinstance(daily_validation, dict):
        raise RegistryError("validation.daily_bars missing")
    for field in [
        "comparison_rule_version",
        "source_price_basis",
        "sources",
        "allowed_price_basis_pairs",
        "approved_comparison_pairs",
        "close",
        "volume",
    ]:
        if field not in daily_validation:
            raise RegistryError(f"validation.daily_bars missing {field}")
    source_basis = daily_validation["source_price_basis"]
    if not isinstance(source_basis, dict):
        raise RegistryError("validation.daily_bars.source_price_basis must be a mapping")
    for source_code, basis in source_basis.items():
        if source_code not in registry.sources:
            raise RegistryError(f"validation source_price_basis references unknown source {source_code}")
        if basis not in VALID_PRICE_BASES:
            raise RegistryError(f"validation source {source_code} has invalid price_basis {basis}")
    sources = daily_validation["sources"]
    if not isinstance(sources, dict):
        raise RegistryError("validation.daily_bars.sources must be a mapping")
    for source_code, source_cfg in sources.items():
        if source_code not in registry.sources:
            raise RegistryError(f"validation.daily_bars.sources references unknown source {source_code}")
        if source_cfg.get("declared_basis") not in VALID_PRICE_BASES:
            raise RegistryError(f"validation source {source_code} has invalid declared_basis {source_cfg.get('declared_basis')}")
        if "source_field" not in source_cfg:
            raise RegistryError(f"validation source {source_code} missing source_field")
    for pair in daily_validation["allowed_price_basis_pairs"]:
        if not isinstance(pair, list) or len(pair) != 2:
            raise RegistryError(f"validation allowed_price_basis_pairs entry must be a two-item list: {pair}")
        for basis in pair:
            if basis not in VALID_PRICE_BASES:
                raise RegistryError(f"validation allowed_price_basis_pairs has invalid basis {basis}")
    for pair in daily_validation["approved_comparison_pairs"]:
        if not isinstance(pair, dict):
            raise RegistryError(f"validation approved_comparison_pairs entry must be a mapping: {pair}")
        for key in ["primary", "validation", "field", "primary_basis", "validation_basis", "status", "reason"]:
            if key not in pair:
                raise RegistryError(f"validation approved_comparison_pairs entry missing {key}")
        if pair["primary"] not in registry.sources or pair["validation"] not in registry.sources:
            raise RegistryError(f"validation approved_comparison_pairs references unknown source: {pair}")
        if pair["primary_basis"] not in VALID_PRICE_BASES or pair["validation_basis"] not in VALID_PRICE_BASES:
            raise RegistryError(f"validation approved_comparison_pairs has invalid basis: {pair}")
        if pair["status"] != "approved_for_current_validation":
            raise RegistryError(f"validation approved_comparison_pairs has unsupported status {pair['status']}")
        if pair["field"] not in {"close", "volume"}:
            raise RegistryError(f"validation approved_comparison_pairs has unsupported field {pair['field']}")
    for field in ["close", "volume"]:
        thresholds = daily_validation[field]
        for key in ["match_percent", "minor_difference_percent", "material_difference_percent"]:
            if key not in thresholds:
                raise RegistryError(f"validation.daily_bars.{field} missing {key}")
            if float(thresholds[key]) < 0:
                raise RegistryError(f"validation.daily_bars.{field}.{key} must be non-negative")


def describe_key(registry: Registry, key: str) -> dict[str, Any]:
    if ":" in key:
        source, identifier = key.split(":", 1)
        if source.lower() == "fred" and identifier in registry.series:
            return {"type": "series", "key": identifier, **registry.series[identifier]}
        if source.lower() in {"massive", "polygon", "yahoo"} and identifier in registry.instruments:
            return {"type": "instrument", "key": identifier, **registry.instruments[identifier]}
    if key in registry.series:
        return {"type": "series", "key": key, **registry.series[key]}
    if key in registry.instruments:
        return {"type": "instrument", "key": key, **registry.instruments[key]}
    raise RegistryError(f"registry key not found: {key}")

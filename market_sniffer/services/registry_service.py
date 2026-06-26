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


class RegistryError(ValueError):
    pass


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise RegistryError(f"{path} must contain a YAML mapping")
    return data


def load_registry(config_dir: Path | None = None) -> Registry:
    root = config_dir or PROJECT_ROOT / "config"
    sources = _load_yaml(root / "source_registry.yaml").get("sources", {})
    series = _load_yaml(root / "series_registry.yaml").get("series", {})
    instruments = _load_yaml(root / "instrument_registry.yaml").get("instruments", {})
    profiles = _load_yaml(root / "collection_profiles.yaml").get("profiles", {})
    registry = Registry(sources=sources, series=series, instruments=instruments, profiles=profiles)
    validate_registry(registry)
    return registry


def validate_registry(registry: Registry) -> None:
    for code, source in registry.sources.items():
        for field in ["display_name", "enabled", "canonical_responsibilities", "failure_behavior"]:
            if field not in source:
                raise RegistryError(f"source {code} missing {field}")
    for code, item in registry.series.items():
        for field in ["source", "source_id", "category", "frequency", "unit", "canonical_source", "collection_profile", "why"]:
            if field not in item:
                raise RegistryError(f"series {code} missing {field}")
        if item["source"] not in registry.sources:
            raise RegistryError(f"series {code} references unknown source {item['source']}")
        if item["canonical_source"] != "fred":
            raise RegistryError(f"series {code} must remain FRED-canonical in v1")
    for symbol, item in registry.instruments.items():
        for field in ["asset_class", "currency", "collection_profiles", "daily", "future_quote", "why"]:
            if field not in item:
                raise RegistryError(f"instrument {symbol} missing {field}")
    for name, profile in registry.profiles.items():
        if "description" not in profile:
            raise RegistryError(f"profile {name} missing description")


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

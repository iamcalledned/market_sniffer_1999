from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from market_sniffer.collectors.base import FredObservation, MissingCredentialError, ProviderError


class FredApiClient:
    def __init__(self, api_key: str | None):
        self.api_key = api_key

    def observations(self, series_id: str, start: date, end: date) -> tuple[dict[str, Any], list[FredObservation]]:
        if not self.api_key:
            raise MissingCredentialError("FRED_API_KEY is required for real FRED collection")
        params = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
            "observation_start": start.isoformat(),
            "observation_end": end.isoformat(),
        }
        response = httpx.get("https://api.stlouisfed.org/fred/series/observations", params=params, timeout=30)
        payload = response.json()
        if response.status_code >= 400 or "error_code" in payload:
            raise ProviderError(f"FRED error for {series_id}: {payload.get('error_message', response.text)}")
        observations: list[FredObservation] = []
        for row in payload.get("observations", []):
            value = row.get("value")
            if value in {None, "."}:
                continue
            try:
                parsed = Decimal(str(value))
            except InvalidOperation as exc:
                raise ProviderError(f"Malformed FRED value for {series_id} on {row.get('date')}: {value}") from exc
            observations.append(
                FredObservation(
                    observation_date=date.fromisoformat(row["date"]),
                    value=parsed,
                    realtime_start=date.fromisoformat(row["realtime_start"]) if row.get("realtime_start") else None,
                    realtime_end=date.fromisoformat(row["realtime_end"]) if row.get("realtime_end") else None,
                    raw=row,
                )
            )
        return payload, observations


class FixtureFredClient:
    def observations(self, series_id: str, start: date, end: date) -> tuple[dict[str, Any], list[FredObservation]]:
        midpoint = start
        value = Decimal(str((sum(ord(c) for c in series_id) % 1000) / 100))
        raw = {
            "realtime_start": start.isoformat(),
            "realtime_end": end.isoformat(),
            "date": midpoint.isoformat(),
            "value": str(value),
        }
        return {"series_id": series_id, "observations": [raw], "fixture": True}, [
            FredObservation(midpoint, value, start, end, raw)
        ]

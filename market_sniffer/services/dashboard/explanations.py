from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from market_sniffer.settings import PROJECT_ROOT

METRIC_EXPLANATIONS_PATH = PROJECT_ROOT / "config" / "metric_explanations.yaml"


class MetricExplanationService:
    def __init__(self, path: Path = METRIC_EXPLANATIONS_PATH):
        self.path = path
        self.explanations = self._load_explanations()

    def _load_explanations(self) -> dict[str, dict[str, str]]:
        if not self.path.exists():
            return {}
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            return data.get("explanations", {})
        except Exception:
            return {}

    def get_explanation(self, metric_code: str) -> dict[str, str]:
        """Returns the explanation details for a metric code, falling back to defaults if not found."""
        fallback = {
            "plain_label": metric_code.split(".")[-1].replace("_", " ").title(),
            "short_description": "Persisted derived market indicator.",
            "why_it_matters": "Provides structural or historical context for market analysis.",
            "what_it_does_not_mean": "This is not a buy/sell signal or recommendation.",
            "good_to_know": "Drawn directly from canonical database records.",
        }
        return self.explanations.get(metric_code, fallback)

from __future__ import annotations

from decimal import Decimal


def format_value(value: float | Decimal | None, unit: str, show_sign: bool = False) -> str:
    """Formats numeric values to avoid long decimals and ensure correct units and signs."""
    if value is None:
        return "N/A"

    val_float = float(value)
    sign = "+" if (show_sign and val_float > 0) else ""

    if unit == "ratio":
        # Ratios (e.g., return or trend distance) are multiplied by 100
        return f"{sign}{val_float * 100.0:.2f}%"
    elif unit == "percent":
        # Percent values (e.g., high-yield spread) are already on a percentage scale
        return f"{sign}{val_float:.2f}%"
    elif unit == "percent_point":
        # Changes in percentage values
        return f"{sign}{val_float:.2f} pp"
    elif unit in ("index", "price", "index_point"):
        return f"{sign}{val_float:.2f}"
    else:
        return f"{sign}{val_float:.2f}"

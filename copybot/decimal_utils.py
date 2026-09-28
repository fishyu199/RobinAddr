"""Small Decimal helpers shared by the backtest engine."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, localcontext
from typing import Any


ZERO = Decimal("0")
ONE = Decimal("1")


def decimal_value(value: Any, *, field: str = "value", default: Decimal | None = None) -> Decimal:
    if value is None or value == "":
        if default is not None:
            return default
        raise ValueError(f"{field} is required")
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


def safe_div(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == ZERO:
        return ZERO
    with localcontext() as context:
        context.prec = 50
        return numerator / denominator


def as_number(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


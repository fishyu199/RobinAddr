"""Pure helpers for ranking GMGN wallet-discovery candidates."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def decimal_value(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(0)


def ranking_value(row: dict[str, Any], sort_by: str) -> Decimal:
    if sort_by == "pnl":
        cost = decimal_value(row.get("realized_profit_cost"))
        return decimal_value(row.get("realized_profit")) / cost if cost else Decimal(0)
    return decimal_value(row.get(sort_by))


def matches_filters(row: dict[str, Any], filters: dict[str, Any]) -> bool:
    comparisons = {
        "min_realized_profit": ("realized_profit", lambda actual, expected: actual >= expected),
        "min_total_profit": ("total_profit", lambda actual, expected: actual >= expected),
        "min_total_cost": ("total_cost", lambda actual, expected: actual >= expected),
        "min_buy": ("buy", lambda actual, expected: actual >= expected),
        "min_sell": ("sell", lambda actual, expected: actual >= expected),
        "max_buy": ("buy", lambda actual, expected: actual <= expected),
        "max_sell": ("sell", lambda actual, expected: actual <= expected),
    }
    for filter_name, raw_expected in filters.items():
        definition = comparisons.get(filter_name)
        if definition is None or raw_expected in (None, ""):
            continue
        field, comparator = definition
        if not comparator(decimal_value(row.get(field)), decimal_value(raw_expected)):
            return False
    return True

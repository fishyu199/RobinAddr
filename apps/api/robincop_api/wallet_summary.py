from __future__ import annotations

from typing import Any


SUMMARY_METRIC_KEYS = (
    "win_rate",
    "copy_loss_rate",
    "avg_profit_loss_ratio",
    "trading_days",
    "recent_20_stats",
    "tokens_traded",
    "trading_volume",
    "avg_invest_per_token",
    "median_holding_time_seconds",
    "target_daily_pnl_14d",
    "copy_daily_pnl_14d",
    "last_active",
)


def build_wallet_summary(metrics: dict[str, Any] | None) -> dict[str, Any]:
    source = metrics or {}
    return {key: source.get(key) for key in SUMMARY_METRIC_KEYS}

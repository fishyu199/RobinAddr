#!/usr/bin/env python3
"""Build compact, deployable wallet snapshots from full analysis reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
OUTPUT = ROOT / "apps" / "web" / "data" / "wallet-snapshots.json"
MAX_CHART_POINTS = 240
MAX_HISTORY_ROWS = 500
MAX_TRADE_ROWS = 200

LABELS = {
    "smart_degen": "Smart Money",
    "gmgn_go": "GMGN Go",
    "fomo": "FOMO",
    "gmgn": "GMGN",
}


def compact_address(address: str) -> str:
    return f"{address[:6]}...{address[-5:]}"


def sample(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if len(items) <= limit:
        return items
    step = (len(items) - 1) / (limit - 1)
    indexes = sorted({round(index * step) for index in range(limit)})
    return [items[index] for index in indexes]


def daily_bars(metrics: dict[str, Any], key: str) -> list[dict[str, Any]]:
    existing = metrics.get(key)
    if isinstance(existing, list) and existing:
        return existing[-14:]
    field = "actual_pnl" if key == "target_daily_pnl_14d" else "bt_copy_pnl"
    daily = metrics.get("daily_stats") or []
    ordered = sorted(daily, key=lambda row: str(row.get("date") or ""))[-14:]
    return [{"date": row.get("date", ""), "pnl": row.get(field, 0)} for row in ordered]


def snapshot(path: Path) -> dict[str, Any]:
    metrics = json.loads(path.read_text())
    address = str(metrics.get("wallet_address") or path.name.split("-")[0]).lower()
    common = (metrics.get("gmgn_stats_30d") or {}).get("common") or {}
    display_name = next(
        (
            str(value).strip()
            for value in (common.get("name"), common.get("nick_name"), common.get("twitter_name"))
            if str(value or "").strip()
        ),
        compact_address(address),
    )
    raw_labels = common.get("tags") or []
    labels = [LABELS.get(str(label), str(label).replace("_", " ").title()) for label in raw_labels]

    positions = []
    for row in metrics.get("per_token") or []:
        quantity = float(row.get("copy_ending_quantity") or 0)
        if quantity <= 0:
            continue
        target = row.get("target") or {}
        copy = row.get("copy") or {}
        positions.append(
            {
                "token_address": row.get("token_address", ""),
                "token_symbol": row.get("token_symbol", ""),
                "copy_ending_quantity": quantity,
                "copy_cost_basis_usd": copy.get("ending_cost_basis_usd"),
                "copy_market_value_usd": copy.get("market_value_usd"),
                "mark_price_usd": row.get("copy_exit_mark_price_usd") or row.get("mark_price_usd"),
                "actual_pnl": target.get("total_pnl_usd"),
                "copy_pnl": copy.get("total_pnl_usd"),
            }
        )

    scalar_keys = (
        "actual_pnl",
        "copy_backtest_pnl",
        "copy_loss_rate",
        "pnl_retention_rate",
        "extra_loss_usd",
        "token_win_rate",
        "sell_win_rate",
        "avg_profit_loss_ratio",
        "trading_days",
        "trading_volume",
        "required_starting_cash_usd",
        "copy_roi_on_required_cash",
        "tokens_traded",
        "open_token_count",
        "processed_trade_count",
        "buy_count",
        "sell_count",
        "avg_invest_per_token",
        "median_holding_time_seconds",
        "last_active",
        "analysis",
        "categories",
        "recent_20_stats",
    )
    compact_metrics = {key: metrics.get(key) for key in scalar_keys}
    compact_metrics.update(
        {
            "equity_curve": sample(metrics.get("equity_curve") or [], MAX_CHART_POINTS),
            "position_rows": positions,
            "all_tokens": (metrics.get("all_tokens") or [])[:MAX_HISTORY_ROWS],
            "trade_results": (metrics.get("trade_results") or [])[-MAX_TRADE_ROWS:],
            "target_daily_pnl_14d": daily_bars(metrics, "target_daily_pnl_14d"),
            "copy_daily_pnl_14d": daily_bars(metrics, "copy_daily_pnl_14d"),
        }
    )

    return {
        "address": address,
        "name": display_name,
        "display_name": display_name,
        "labels": labels,
        "score": metrics.get("score", 0),
        "actual_pnl": metrics.get("actual_pnl", 0),
        "copy_pnl": metrics.get("copy_backtest_pnl", 0),
        "win_rate": metrics.get("win_rate", 0),
        "copy_loss_rate": metrics.get("copy_loss_rate"),
        "pnl_ratio": metrics.get("avg_profit_loss_ratio", 0),
        "trading_days": metrics.get("trading_days", 0),
        "recent_20": metrics.get("recent_20_stats") or {},
        "tokens_traded": metrics.get("tokens_traded", 0),
        "trading_volume": metrics.get("trading_volume", 0),
        "avg_invest": metrics.get("avg_invest_per_token", 0),
        "median_holding_time_seconds": metrics.get("median_holding_time_seconds"),
        "target_daily_pnl_14d": daily_bars(metrics, "target_daily_pnl_14d"),
        "copy_daily_pnl_14d": daily_bars(metrics, "copy_daily_pnl_14d"),
        "analyzed_at": metrics.get("last_active") or None,
        "data_source": "snapshot",
        "metrics": compact_metrics,
    }


def main() -> None:
    rows = [snapshot(path) for path in sorted(REPORTS.glob("*-summary.json"))]
    qualified = [row for row in rows if int(row["score"] or 0) > 30]
    qualified.sort(key=lambda row: int(row["score"]), reverse=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(qualified, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"Wrote {len(qualified)} wallet snapshots to {OUTPUT}")


if __name__ == "__main__":
    main()

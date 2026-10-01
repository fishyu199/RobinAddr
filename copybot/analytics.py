"""Website/report analytics compatible with the legacy Polymarket payload."""

from __future__ import annotations

import math
import statistics
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from html import escape
from typing import Any, Iterable, Mapping, Sequence

from .accounting import PositionLedger
from .decimal_utils import ZERO, decimal_value
from .models import BacktestResult, Side


DEFAULT_REFERRAL_URL = "https://t.me/RobinCop_AI_Bot?start=ref_WMNE5NPY"
COPY_TRADE_URL_PREFIX = "https://t.me/RobinCop_AI_Bot?start=A_ZETLYPGS_"


def build_copy_trade_url(wallet_address: str) -> str:
    """Return the Telegram copy-trade deep link for a wallet."""
    wallet = str(wallet_address or "").strip().lower()
    return f"{COPY_TRADE_URL_PREFIX}{wallet}" if wallet else DEFAULT_REFERRAL_URL


def _number(value: Any) -> float:
    return float(value or 0)


def _token_activity(result: BacktestResult) -> dict[str, dict[str, Any]]:
    activity: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "first_buy_time_ms": 0,
            "last_buy_time_ms": 0,
            "last_sell_time_ms": 0,
            "last_timestamp_ms": 0,
            "buy_quantity": 0.0,
            "buy_notional": 0.0,
            "sell_quantity": 0.0,
            "sell_notional": 0.0,
            "buy_count": 0,
            "sell_count": 0,
            "launchpad_platform": "",
        }
    )
    for row in result.trade_results:
        address = str(row["token_address"])
        timestamp_ms = int(row["timestamp_ms"])
        item = activity[address]
        platform = str(row.get("launchpad_platform") or "")
        if platform:
            item["launchpad_platform"] = platform
        item["last_timestamp_ms"] = max(item["last_timestamp_ms"], timestamp_ms)
        quantity = _number(row.get("executed_token_amount"))
        notional = _number(row.get("target_notional_usd"))
        if row.get("side") == Side.BUY.value:
            if not item["first_buy_time_ms"]:
                item["first_buy_time_ms"] = timestamp_ms
            item["last_buy_time_ms"] = max(item["last_buy_time_ms"], timestamp_ms)
            item["buy_quantity"] += quantity
            item["buy_notional"] += notional
            item["buy_count"] += 1
        elif row.get("side") == Side.SELL.value:
            item["last_sell_time_ms"] = max(item["last_sell_time_ms"], timestamp_ms)
            item["sell_quantity"] += quantity
            item["sell_notional"] += notional
            if quantity > 0:
                item["sell_count"] += 1
    return activity


def _token_rows(result: BacktestResult) -> list[dict[str, Any]]:
    activity = _token_activity(result)
    rows: list[dict[str, Any]] = []
    for token in result.per_token:
        address = str(token["token_address"])
        stats = activity[address]
        target = token["target"]
        copy = token["copy"]
        rows.append(
            {
                "token_address": address,
                "token_symbol": str(token.get("token_symbol") or address),
                "launchpad_platform": str(
                    token.get("launchpad_platform") or stats["launchpad_platform"] or "Other"
                ),
                "actual_pnl": _number(target.get("total_pnl_usd")),
                "copy_backtest_pnl": _number(copy.get("total_pnl_usd")),
                "invested": _number(target.get("gross_buy_usd")),
                "copy_invested": _number(copy.get("gross_buy_usd")) + _number(copy.get("fees_usd")),
                "avg_buy_price": (
                    stats["buy_notional"] / stats["buy_quantity"] if stats["buy_quantity"] else 0.0
                ),
                "avg_sell_price": (
                    stats["sell_notional"] / stats["sell_quantity"] if stats["sell_quantity"] else 0.0
                ),
                "buy_count": stats["buy_count"],
                "sell_count": stats["sell_count"],
                "bought_quantity": stats["buy_quantity"],
                "sold_quantity": stats["sell_quantity"],
                "ending_quantity": _number(token.get("target_ending_quantity")),
                "first_buy_time_ms": stats["first_buy_time_ms"],
                "last_buy_time_ms": stats["last_buy_time_ms"],
                "last_sell_time_ms": stats["last_sell_time_ms"],
                "last_timestamp_ms": stats["last_timestamp_ms"],
                "mark_price_usd": _number(token.get("mark_price_usd")),
                "copy_exit_mark_price_usd": _number(token.get("copy_exit_mark_price_usd")),
                "is_closed": _number(token.get("target_ending_quantity")) <= 1e-12,
            }
        )
    return rows


def _simulate_rows(
    result: BacktestResult,
    rows: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    target_ledgers: dict[str, PositionLedger] = defaultdict(PositionLedger)
    copy_ledgers: dict[str, PositionLedger] = defaultdict(PositionLedger)
    stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "symbol": "",
            "last_timestamp_ms": 0,
            "last_buy_time_ms": 0,
            "buy_quantity": Decimal("0"),
            "buy_notional": Decimal("0"),
            "sell_quantity": Decimal("0"),
            "sell_notional": Decimal("0"),
            "buy_count": 0,
            "launchpad_platform": "",
        }
    )
    for row in rows:
        address = str(row["token_address"])
        side = Side.parse(row.get("side"))
        requested = decimal_value(row.get("requested_token_amount"), field="requested_token_amount")
        target_price = decimal_value(row.get("target_price_usd"), field="target_price_usd")
        copy_price = decimal_value(row.get("copy_price_usd"), field="copy_price_usd")
        target_fee = decimal_value(row.get("target_fee_usd"), field="target_fee_usd", default=ZERO)
        copy_fee = decimal_value(row.get("copy_fee_usd"), field="copy_fee_usd", default=ZERO)
        item = stats[address]
        item["symbol"] = str(row.get("token_symbol") or item["symbol"] or address)
        platform = str(row.get("launchpad_platform") or "")
        if platform:
            item["launchpad_platform"] = platform
        timestamp_ms = int(row["timestamp_ms"])
        item["last_timestamp_ms"] = max(item["last_timestamp_ms"], timestamp_ms)
        if side is Side.BUY:
            target_execution = target_ledgers[address].buy(requested, target_price, target_fee)
            copy_execution = copy_ledgers[address].buy(requested, copy_price, copy_fee)
            item["last_buy_time_ms"] = max(item["last_buy_time_ms"], timestamp_ms)
            item["buy_quantity"] += target_execution.executed_quantity
            item["buy_notional"] += target_execution.gross_notional_usd
            item["buy_count"] += 1
        else:
            target_execution = target_ledgers[address].sell(requested, target_price, exact_fee_usd=target_fee)
            copy_execution = copy_ledgers[address].sell(requested, copy_price, exact_fee_usd=copy_fee)
            item["sell_quantity"] += target_execution.executed_quantity
            item["sell_notional"] += target_execution.gross_notional_usd

    token_marks = {str(token["token_address"]): token for token in result.per_token}
    simulated: dict[str, dict[str, Any]] = {}
    for address in sorted(set(target_ledgers) | set(copy_ledgers)):
        token = token_marks.get(address, {})
        target_mark = decimal_value(token.get("mark_price_usd"), field="mark_price_usd", default=ZERO)
        copy_mark = decimal_value(
            token.get("copy_exit_mark_price_usd"), field="copy_exit_mark_price_usd", default=target_mark
        )
        target = target_ledgers[address].summary(target_mark)
        copy = copy_ledgers[address].summary(copy_mark)
        item = stats[address]
        simulated[address] = {
            "token_address": address,
            "token_symbol": item["symbol"],
            "launchpad_platform": item["launchpad_platform"] or "Other",
            "actual_pnl": float(target.total_pnl_usd),
            "copy_backtest_pnl": float(copy.total_pnl_usd),
            "invested": float(target.gross_buy_usd),
            "copy_invested": float(copy.gross_buy_usd + copy.fees_usd),
            "buy_count": item["buy_count"],
            "avg_buy_price": (
                float(item["buy_notional"] / item["buy_quantity"]) if item["buy_quantity"] else 0.0
            ),
            "avg_sell_price": (
                float(item["sell_notional"] / item["sell_quantity"]) if item["sell_quantity"] else 0.0
            ),
            "last_timestamp_ms": item["last_timestamp_ms"],
            "last_buy_time_ms": item["last_buy_time_ms"],
            "is_closed": target_ledgers[address].quantity <= ZERO,
        }
    return simulated


def _recent_20(result: BacktestResult) -> list[dict[str, Any]]:
    selected: list[str] = []
    cutoff_ms = 0
    for row in reversed(result.trade_results):
        if row.get("side") != Side.BUY.value:
            continue
        address = str(row["token_address"])
        if address in selected:
            continue
        selected.append(address)
        cutoff_ms = int(row["timestamp_ms"])
        if len(selected) == 20:
            break
    if not selected:
        return []
    selected_set = set(selected)
    relevant = [
        row
        for row in result.trade_results
        if str(row["token_address"]) in selected_set and int(row["timestamp_ms"]) >= cutoff_ms
    ]
    simulated = _simulate_rows(result, relevant)
    return [simulated[address] for address in selected if address in simulated]


def _last_two_day_copy_pnl(result: BacktestResult, now_ms: int) -> float:
    cutoff_ms = now_ms - 2 * 86_400_000
    recent = [row for row in result.trade_results if int(row["timestamp_ms"]) >= cutoff_ms]
    return sum(item["copy_backtest_pnl"] for item in _simulate_rows(result, recent).values())


def _daily_stats(result: BacktestResult, token_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    days: dict[str, dict[str, Any]] = {}
    for row in result.trade_results:
        day = datetime.fromtimestamp(int(row["timestamp_ms"]) / 1000, timezone.utc).strftime("%Y-%m-%d")
        item = days.setdefault(
            day,
            {"date": day, "volume": 0.0, "trades": 0, "actual_pnl": 0.0, "bt_copy_pnl": 0.0},
        )
        item["volume"] += _number(row.get("target_notional_usd"))
        item["trades"] += 1
    for token in token_rows:
        timestamp_ms = int(token.get("last_timestamp_ms") or 0)
        if not timestamp_ms:
            continue
        day = datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc).strftime("%Y-%m-%d")
        item = days.setdefault(
            day,
            {"date": day, "volume": 0.0, "trades": 0, "actual_pnl": 0.0, "bt_copy_pnl": 0.0},
        )
        item["actual_pnl"] += _number(token.get("actual_pnl"))
        item["bt_copy_pnl"] += _number(token.get("copy_backtest_pnl"))
    return [days[day] for day in sorted(days, reverse=True)]


def _daily_equity_pnl(result: BacktestResult, now_ms: int, days: int = 14) -> list[dict[str, Any]]:
    """Return fixed UTC calendar-day PnL deltas from the backtest equity curve.

    The backtest marks positions at the latest price observed at each trade event,
    so these bars are event-time mark-to-market estimates rather than historical
    exchange close prices. Missing calendar days are carried forward and emit 0.
    """
    if days <= 0:
        return []
    end_day = datetime.fromtimestamp(now_ms / 1000, timezone.utc).date()
    start_day = end_day - timedelta(days=days - 1)
    points = sorted(result.equity_curve, key=lambda row: int(row.get("timestamp_ms") or 0))
    point_index = 0
    target_close = 0.0
    copy_close = 0.0

    start_ms = int(datetime.combine(start_day, datetime.min.time(), tzinfo=timezone.utc).timestamp() * 1000)
    while point_index < len(points) and int(points[point_index].get("timestamp_ms") or 0) < start_ms:
        target_close = _number(points[point_index].get("target_pnl_usd"))
        copy_close = _number(points[point_index].get("copy_pnl_usd"))
        point_index += 1

    previous_target = target_close
    previous_copy = copy_close
    bars: list[dict[str, Any]] = []
    for offset in range(days):
        day = start_day + timedelta(days=offset)
        next_day_ms = int(
            datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc).timestamp()
            * 1000
        )
        while point_index < len(points) and int(points[point_index].get("timestamp_ms") or 0) < next_day_ms:
            target_close = _number(points[point_index].get("target_pnl_usd"))
            copy_close = _number(points[point_index].get("copy_pnl_usd"))
            point_index += 1
        bars.append(
            {
                "date": day.isoformat(),
                "actual_pnl": target_close - previous_target,
                "copy_pnl": copy_close - previous_copy,
            }
        )
        previous_target = target_close
        previous_copy = copy_close
    return bars


def _score(
    *,
    copy_pnl: float,
    recent_copy_pnl: float,
    loss_rate: float | None,
    recent_loss_rate: float | None,
    profitable_days_14d: int,
    loss_days_14d: int,
    total_pnl_14d: float,
    pnl_ratio_14d: float,
    days_since_active: float,
    win_rate: float,
    profit_loss_ratio: float,
    token_count: int,
    median_holding_time_seconds: float | None,
    last_2d_profit_share: float,
    recent_target_pnl: float,
) -> int:
    score = 0
    if copy_pnl > 10_000:
        score += 15
    elif copy_pnl > 3_000:
        score += 10
    elif copy_pnl > 500:
        score += 5
    elif copy_pnl > 0:
        score += 2

    if recent_copy_pnl > 2_000:
        score += 10
    elif recent_copy_pnl > 500:
        score += 6
    elif recent_copy_pnl > 0:
        score += 3

    if loss_rate is not None:
        if loss_rate < 10:
            score += 20
        elif loss_rate < 15:
            score += 17
        elif loss_rate < 20:
            score += 14
        elif loss_rate < 25:
            score += 11
        elif loss_rate < 30:
            score += 8
        elif loss_rate < 35:
            score += 5
        elif loss_rate < 40:
            score += 2

    if recent_loss_rate is not None:
        if recent_loss_rate < 10:
            score += 15
        elif recent_loss_rate < 15:
            score += 12
        elif recent_loss_rate < 20:
            score += 9
        elif recent_loss_rate < 25:
            score += 6
        elif recent_loss_rate < 30:
            score += 3
        elif recent_loss_rate < 35:
            score += 1

    if profitable_days_14d >= 10:
        score += 15
    elif total_pnl_14d > 0 and (loss_days_14d < 3 or pnl_ratio_14d >= 3) and profitable_days_14d >= 7:
        score += 12
    elif total_pnl_14d > 0 and (loss_days_14d < 3 or pnl_ratio_14d >= 2) and profitable_days_14d >= 5:
        score += 9
    elif profitable_days_14d >= 7:
        score += 9
    elif profitable_days_14d >= 4 and total_pnl_14d > 0:
        score += 5
    elif total_pnl_14d > 0:
        score += 2

    if days_since_active <= 5:
        score += 5
    elif days_since_active <= 10:
        score += 3
    elif days_since_active <= 20:
        score += 1
    if win_rate > 40:
        score += 10
    if profit_loss_ratio >= 2:
        score += 10
    elif profit_loss_ratio >= 1.5:
        score += 6
    elif profit_loss_ratio >= 1:
        score += 3

    if token_count < 10:
        score -= 15
    if loss_rate is not None:
        if loss_rate > 60:
            score -= 20
        elif loss_rate > 30:
            score -= 10
    if recent_loss_rate is not None and recent_target_pnl > 0 and recent_loss_rate > 30:
        score -= 10
    if days_since_active > 20:
        score -= 30
    elif days_since_active > 10:
        score -= 15
    elif days_since_active > 5:
        score -= 5
    if last_2d_profit_share < 10:
        score -= 5
    if recent_copy_pnl < 0:
        score -= 10
    if copy_pnl < 1_000:
        score -= 20
    if copy_pnl < 0:
        return 0
    return max(0, min(100, score))


def generate_pnl_svg(data_points: Sequence[float]) -> str:
    if not data_points:
        return '<div class="text-zinc-600 text-xs">-</div>'
    width, height = 300, 64
    low, high = min(data_points), max(data_points)
    spread = high - low or 1.0
    step = width / max(1, len(data_points) - 1)
    coordinates = [
        (index * step, height - ((_number(value) - low) / spread) * height)
        for index, value in enumerate(data_points)
    ]
    path = " ".join(
        ("M" if index == 0 else "L") + f"{x:.2f},{y:.2f}"
        for index, (x, y) in enumerate(coordinates)
    )
    color = "#22c55e" if data_points[-1] >= data_points[0] else "#ef4444"
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'style="overflow: visible"><path d="{path}" fill="none" stroke="{color}" '
        'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" /></svg>'
    )


def build_legacy_metrics(
    result: BacktestResult,
    *,
    wallet_address: str = "",
    profile: Mapping[str, Any] | None = None,
    include_all_tokens: bool = False,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Return old-site compatible fields plus explicit Robinhood-native fields."""
    profile = profile or {}
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    tokens = _token_rows(result)
    recent = _recent_20(result)
    daily = _daily_stats(result, tokens)
    daily_equity_14d = _daily_equity_pnl(result, now_ms, days=14)

    target_pnl = float(result.target.total_pnl_usd)
    copy_pnl = float(result.copy.total_pnl_usd)
    gap = float(result.pnl_gap_usd)
    loss_rate = max(0.0, gap / target_pnl * 100) if target_pnl > 0 else None
    retention = copy_pnl / target_pnl * 100 if target_pnl > 0 else None
    extra_loss = max(0.0, target_pnl - copy_pnl) if target_pnl <= 0 else None

    decided = [token for token in tokens if abs(token["actual_pnl"]) >= 0.005]
    wins = [token for token in decided if token["actual_pnl"] > 0]
    losses = [token for token in decided if token["actual_pnl"] < 0]
    win_rate = len(wins) / len(decided) * 100 if decided else 0.0
    copy_decided = [token for token in tokens if abs(token["copy_backtest_pnl"]) >= 0.005]
    copy_token_win_rate = (
        sum(1 for token in copy_decided if token["copy_backtest_pnl"] > 0) / len(copy_decided) * 100
        if copy_decided
        else 0.0
    )
    gross_profit = sum(token["actual_pnl"] for token in wins)
    gross_loss = abs(sum(token["actual_pnl"] for token in losses))
    profit_loss_ratio = gross_profit / gross_loss if gross_loss else (999.0 if gross_profit else 0.0)
    winning_rois = [token["actual_pnl"] / token["invested"] * 100 for token in wins if token["invested"]]
    winning_roi = sum(winning_rois) / len(winning_rois) if winning_rois else 0.0

    avg_buy_prices = [token["avg_buy_price"] for token in tokens if token["avg_buy_price"] > 0]
    avg_sell_prices = [token["avg_sell_price"] for token in tokens if token["avg_sell_price"] > 0]
    holding_times = [
        (token["last_sell_time_ms"] - token["first_buy_time_ms"]) / 1000
        for token in tokens
        if token["first_buy_time_ms"] and token["last_sell_time_ms"] > token["first_buy_time_ms"]
    ]
    median_holding = statistics.median(holding_times) if holding_times else 0.0

    recent_target = sum(token["actual_pnl"] for token in recent)
    recent_copy = sum(token["copy_backtest_pnl"] for token in recent)
    recent_gap = recent_target - recent_copy
    recent_loss_rate = max(0.0, recent_gap / recent_target * 100) if recent_target > 0 else None
    recent_extra_loss = max(0.0, recent_target - recent_copy) if recent_target <= 0 else None
    recent_decided = [token for token in recent if abs(token["actual_pnl"]) >= 0.005]
    recent_win_rate = (
        sum(1 for token in recent_decided if token["actual_pnl"] > 0) / len(recent_decided) * 100
        if recent_decided
        else 0.0
    )

    last_two_day_pnl = _last_two_day_copy_pnl(result, now_ms)
    last_two_day_share = last_two_day_pnl / copy_pnl * 100 if copy_pnl > 0 and last_two_day_pnl > 0 else 0.0
    last_active_ms = int(result.last_trade_time_ms or 0)
    last_buy_ms = max((int(row["timestamp_ms"]) for row in result.trade_results if row["side"] == "buy"), default=0)
    days_since_active = (now_ms - last_buy_ms) / 86_400_000 if last_buy_ms else math.inf

    recent_14_cutoff = now_ms - 14 * 86_400_000
    token_pnl_by_day: dict[str, float] = defaultdict(float)
    for token in tokens:
        if token["last_timestamp_ms"] >= recent_14_cutoff:
            day = datetime.fromtimestamp(token["last_timestamp_ms"] / 1000, timezone.utc).strftime("%Y-%m-%d")
            token_pnl_by_day[day] += token["actual_pnl"]
    profitable_days_14d = sum(value > 0 for value in token_pnl_by_day.values())
    loss_days_14d = sum(value < 0 for value in token_pnl_by_day.values())
    total_pnl_14d = sum(token_pnl_by_day.values())
    gross_profit_14d = sum(value for value in token_pnl_by_day.values() if value > 0)
    gross_loss_14d = abs(sum(value for value in token_pnl_by_day.values() if value < 0))
    pnl_ratio_14d = gross_profit_14d / gross_loss_14d if gross_loss_14d else (999.0 if gross_profit_14d else 0.0)

    score = _score(
        copy_pnl=copy_pnl,
        recent_copy_pnl=recent_copy,
        loss_rate=loss_rate,
        recent_loss_rate=recent_loss_rate,
        profitable_days_14d=profitable_days_14d,
        loss_days_14d=loss_days_14d,
        total_pnl_14d=total_pnl_14d,
        pnl_ratio_14d=pnl_ratio_14d,
        days_since_active=days_since_active,
        win_rate=win_rate,
        profit_loss_ratio=profit_loss_ratio,
        token_count=len(tokens),
        median_holding_time_seconds=median_holding if holding_times else None,
        last_2d_profit_share=last_two_day_share,
        recent_target_pnl=recent_target,
    )

    avg_invest = float(result.target.gross_buy_usd) / len(tokens) if tokens else 0.0
    avg_target_pnl = target_pnl / len(tokens) if tokens else 0.0
    avg_copy_pnl = copy_pnl / len(tokens) if tokens else 0.0
    sell_decided = result.copy.profitable_sell_count + result.copy.losing_sell_count
    sell_win_rate = result.copy.profitable_sell_count / sell_decided * 100 if sell_decided else 0.0
    total_volume = float(result.target.gross_buy_usd + result.target.gross_sell_usd)
    pnl_curve = [_number(row.get("copy_pnl_usd")) for row in result.equity_curve]

    platform_categories: dict[str, dict[str, int]] = {}
    for token in tokens:
        raw_platform = str(token.get("launchpad_platform") or "Other")
        platform_label = {
            "longxyz": "LongXYZ",
            "pons_v2": "Pons V2",
        }.get(raw_platform.lower(), raw_platform.replace("_", " ").title())
        category = platform_categories.setdefault(platform_label, {"total": 0, "wins": 0})
        category["total"] += 1
        if token["actual_pnl"] > 0:
            category["wins"] += 1
    platform_categories = dict(
        sorted(platform_categories.items(), key=lambda item: item[1]["total"], reverse=True)
    )

    all_tokens = [
        {
            "condition_id": token["token_address"],
            "token_address": token["token_address"],
            "title": token["token_symbol"],
            "symbol": token["token_symbol"],
            "launchpad_platform": token["launchpad_platform"],
            "actual_pnl": token["actual_pnl"],
            "bt_copy_pnl": token["copy_backtest_pnl"],
            "invested": token["invested"],
            "avg_buy_price": token["avg_buy_price"],
            "avg_sell_price": token["avg_sell_price"],
            "closed_size": token["sold_quantity"],
            "first_buy_time": token["first_buy_time_ms"] / 1000 if token["first_buy_time_ms"] else 0,
            "last_active": token["last_timestamp_ms"] / 1000 if token["last_timestamp_ms"] else 0,
            "is_closed": token["is_closed"],
        }
        for token in sorted(
            tokens,
            key=lambda item: item["first_buy_time_ms"] or item["last_timestamp_ms"],
            reverse=True,
        )
    ]
    recent_list = [
        {
            "title": token["token_symbol"],
            "token_address": token["token_address"],
            "launchpad_platform": token["launchpad_platform"],
            "time_str": (
                datetime.fromtimestamp(token["last_buy_time_ms"] / 1000, timezone.utc).strftime("%m.%d %H:%M")
                if token["last_buy_time_ms"]
                else ""
            ),
            "actual_pnl": token["actual_pnl"],
            "bt_copy_pnl": token["copy_backtest_pnl"],
            "invested": token["copy_invested"],
            "buy_count": token["buy_count"],
            "avg_buy_price": token["avg_buy_price"],
            "avg_sell_price": token["avg_sell_price"],
            "win": token["copy_backtest_pnl"] >= 0,
        }
        for token in recent
    ]

    metrics: dict[str, Any] = {
        "wallet_address": wallet_address,
        "profileImage": str(profile.get("avatar") or profile.get("profile_image") or ""),
        "xUsername": str(profile.get("twitter_username") or ""),
        "score": score,
        "actual_pnl": target_pnl,
        "copy_backtest_pnl": copy_pnl,
        "copy_loss_rate": loss_rate,
        "pnl_retention_rate": retention,
        "extra_loss_usd": extra_loss,
        "last_2d_profit_share": last_two_day_share,
        "last_2d_copy_pnl": last_two_day_pnl,
        "win_rate": win_rate,
        "target_token_win_rate": win_rate,
        "token_win_rate": copy_token_win_rate,
        "sell_win_rate": sell_win_rate,
        "avg_profit_loss_ratio": profit_loss_ratio,
        "markets_traded": len(tokens),
        "tokens_traded": len(tokens),
        "trading_volume": total_volume,
        "winning_market_roi": winning_roi,
        "winning_token_roi": winning_roi,
        "avg_buy_in_price": sum(avg_buy_prices) / len(avg_buy_prices) if avg_buy_prices else 0.0,
        "avg_sell_price": sum(avg_sell_prices) / len(avg_sell_prices) if avg_sell_prices else 0.0,
        "avg_invest_per_market": avg_invest,
        "avg_invest_per_token": avg_invest,
        "avg_pnl_per_market": avg_target_pnl,
        "avg_pnl_per_token": avg_target_pnl,
        "avg_copy_pnl_per_token": avg_copy_pnl,
        "median_holding_time_seconds": median_holding,
        "categories": platform_categories,
        "category_dimension": "launchpad_platform",
        "recent_20_stats": {
            "actual_pnl": recent_target,
            "copy_backtest_pnl": recent_copy,
            "copy_loss_rate": recent_loss_rate,
            "extra_loss_usd": recent_extra_loss,
            "win_rate": recent_win_rate,
            "last_active": (
                datetime.fromtimestamp(last_active_ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")
                if last_active_ms
                else ""
            ),
        },
        "recent_20_markets": recent_list,
        "recent_20_tokens": recent_list,
        "daily_stats": daily,
        "daily_equity_pnl_14d": daily_equity_14d,
        "target_daily_pnl_14d": [
            {"date": item["date"], "pnl": item["actual_pnl"]} for item in daily_equity_14d
        ],
        "copy_daily_pnl_14d": [
            {"date": item["date"], "pnl": item["copy_pnl"]} for item in daily_equity_14d
        ],
        "trading_days": len(daily),
        "required_starting_cash_usd": float(result.copy.required_starting_cash_usd),
        "copy_roi_on_required_cash": (
            float(result.copy.roi_on_required_cash) * 100 if result.copy.roi_on_required_cash is not None else None
        ),
        "processed_trade_count": result.processed_trade_count,
        "buy_count": result.target.buy_count,
        "sell_count": result.target.sell_count,
        "open_token_count": result.copy.open_position_count,
        "last_active": (
            datetime.fromtimestamp(last_active_ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            if last_active_ms
            else ""
        ),
        "all_pnl_data": pnl_curve,
        "pnl_svg": generate_pnl_svg(pnl_curve),
        "referral_url": build_copy_trade_url(wallet_address),
        "analysis": (
            "TOXIC: simulated copy PnL is negative; do not copy."
            if copy_pnl < 0
            else "Recent copy PnL is negative; current trades require caution."
            if recent_copy < 0
            else "Lifetime and recent copy results are positive."
        ),
        "score_inputs": {
            "profitable_days_14d": profitable_days_14d,
            "loss_days_14d": loss_days_14d,
            "total_pnl_14d": total_pnl_14d,
            "pnl_ratio_14d": pnl_ratio_14d,
            "days_since_active": days_since_active if math.isfinite(days_since_active) else None,
            "median_holding_time_seconds": median_holding if holding_times else None,
        },
        "metric_semantics": {
            "market_alias": "market fields are retained for website compatibility and mean spot token",
            "copy_loss_rate": "N/A when target PnL is non-positive; use extra_loss_usd instead",
            "daily_pnl": "token PnL attributed to the UTC date of the token's last activity",
            "daily_equity_pnl_14d": (
                "UTC calendar-day deltas from event-time mark-to-market equity; missing days are zero"
            ),
        },
    }
    if include_all_tokens:
        metrics["all_markets"] = all_tokens
        metrics["all_tokens"] = all_tokens
    return metrics

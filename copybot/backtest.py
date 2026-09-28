"""Robinhood Chain spot copy-trading backtest.

The copy account buys and sells the same token quantity as the target account.
Its buy price is worse by the configured buy penalty. Its sell price penalty is
selected from time bands measured from the token's most recent buy, with the
configured base penalty used after one minute. Prediction-market settlement
operations are not part of this model.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any, Iterable, Mapping

from .accounting import Execution, PositionLedger
from .decimal_utils import ONE, ZERO, as_number, decimal_value, safe_div
from .models import AccountSummary, BacktestConfig, BacktestResult, Side, Trade


def _prepare_trades(trades: Iterable[Trade], limit: int) -> tuple[list[Trade], dict[str, int]]:
    indexed = list(enumerate(trades))
    seen: set[tuple[Any, ...]] = set()
    unique: list[tuple[int, Trade]] = []
    for index, trade in indexed:
        if trade.unique_key in seen:
            continue
        seen.add(trade.unique_key)
        unique.append((index, trade))

    def newest_key(item: tuple[int, Trade]) -> tuple[int, int, int]:
        index, trade = item
        sequence = trade.sequence if trade.sequence is not None else -index
        return trade.timestamp_ms, sequence, -index

    selected = sorted(unique, key=newest_key, reverse=True)[:limit]
    selected.sort(key=newest_key)
    return [trade for _, trade in selected], {
        "input": len(indexed),
        "unique": len(unique),
        "duplicates_removed": len(indexed) - len(unique),
        "older_dropped": max(0, len(unique) - len(selected)),
    }


def _sum_summaries(
    summaries: Iterable[AccountSummary],
    *,
    required_starting_cash_usd: Decimal,
) -> AccountSummary:
    result = AccountSummary(required_starting_cash_usd=required_starting_cash_usd)
    decimal_fields = (
        "gross_buy_usd",
        "gross_sell_usd",
        "fees_usd",
        "realized_pnl_usd",
        "unrealized_pnl_usd",
        "total_pnl_usd",
        "market_value_usd",
        "ending_cost_basis_usd",
        "net_cash_flow_usd",
        "unmatched_sell_quantity",
        "unmatched_sell_notional_usd",
    )
    integer_fields = (
        "open_position_count",
        "buy_count",
        "sell_count",
        "profitable_sell_count",
        "losing_sell_count",
        "skipped_sell_count",
        "partial_sell_count",
    )
    for summary in summaries:
        for field_name in decimal_fields:
            setattr(result, field_name, getattr(result, field_name) + getattr(summary, field_name))
        for field_name in integer_fields:
            setattr(result, field_name, getattr(result, field_name) + getattr(summary, field_name))
    if required_starting_cash_usd > ZERO:
        result.roi_on_required_cash = safe_div(result.total_pnl_usd, required_starting_cash_usd)
    return result


def _cash_delta(side: Side, execution: Execution) -> Decimal:
    if side is Side.BUY:
        return -(execution.gross_notional_usd + execution.fee_usd)
    return execution.gross_notional_usd - execution.fee_usd


class CopyBacktester:
    def __init__(self, config: BacktestConfig | None = None) -> None:
        self.config = config or BacktestConfig()

    def run(
        self,
        trades: Iterable[Trade],
        *,
        mark_prices_usd: Mapping[str, Any] | None = None,
        normalization_quality: Mapping[str, Any] | None = None,
    ) -> BacktestResult:
        selected, selection = _prepare_trades(trades, self.config.max_trades)
        supplied_marks = {
            str(address).lower(): decimal_value(price, field=f"mark price for {address}")
            for address, price in (mark_prices_usd or {}).items()
        }
        if any(price <= ZERO for price in supplied_marks.values()):
            raise ValueError("all supplied mark prices must be positive")

        target_ledgers: dict[str, PositionLedger] = defaultdict(PositionLedger)
        copy_ledgers: dict[str, PositionLedger] = defaultdict(PositionLedger)
        symbols: dict[str, str] = {}
        platforms: dict[str, str] = {}
        latest_prices: dict[str, Decimal] = {}
        latest_buy_time_ms: dict[str, int] = {}
        target_market_by_token: dict[str, Decimal] = defaultdict(lambda: ZERO)
        copy_market_by_token: dict[str, Decimal] = defaultdict(lambda: ZERO)
        target_reported_by_token: dict[str, Decimal] = defaultdict(lambda: ZERO)
        target_reported_count_by_token: dict[str, int] = defaultdict(int)
        target_reported_total = ZERO
        target_reported_count = 0

        target_cash = ZERO
        copy_cash = ZERO
        target_min_cash = ZERO
        copy_min_cash = ZERO
        target_market_total = ZERO
        copy_market_total = ZERO
        equity_curve: list[dict[str, Any]] = []
        trade_results: list[dict[str, Any]] = []

        buy_multiplier = ONE + self.config.buy_price_penalty
        open_position_sell_multiplier = ONE - self.config.sell_price_penalty

        for ordinal, trade in enumerate(selected, start=1):
            address = trade.token_address
            symbols[address] = trade.token_symbol or symbols.get(address, "")
            platform = str(trade.metadata.get("launchpad_platform") or "")
            if platform:
                platforms[address] = platform
            target_ledger = target_ledgers[address]
            copy_ledger = copy_ledgers[address]
            target_price = trade.effective_price_usd
            latest_prices[address] = target_price

            target_fee = trade.observed_fee_usd if self.config.include_observed_target_fees else ZERO
            sell_elapsed_ms: int | None = None
            applied_sell_penalty: Decimal | None = None
            if trade.side is Side.BUY:
                target_execution = target_ledger.buy(trade.token_amount, target_price, target_fee)
                copy_price = target_price * buy_multiplier
                copy_gross = trade.token_amount * copy_price
                copy_fee = copy_gross * self.config.copy_fee_rate + self.config.copy_fixed_cost_usd
                copy_execution = copy_ledger.buy(trade.token_amount, copy_price, copy_fee)
                latest_buy_time_ms[address] = trade.timestamp_ms
            else:
                target_execution = target_ledger.sell(
                    trade.token_amount,
                    target_price,
                    exact_fee_usd=target_fee,
                )
                if address in latest_buy_time_ms:
                    sell_elapsed_ms = trade.timestamp_ms - latest_buy_time_ms[address]
                applied_sell_penalty = self.config.sell_penalty_for_elapsed_ms(sell_elapsed_ms)
                sell_multiplier = ONE - applied_sell_penalty
                copy_price = target_price * sell_multiplier
                copy_execution = copy_ledger.sell(
                    trade.token_amount,
                    copy_price,
                    fee_rate=self.config.copy_fee_rate,
                    fixed_fee_usd=self.config.copy_fixed_cost_usd,
                )
                if trade.reported_buy_cost_usd is not None:
                    reported = trade.quote_amount_usd - trade.reported_buy_cost_usd - target_fee
                    target_reported_total += reported
                    target_reported_by_token[address] += reported
                    target_reported_count_by_token[address] += 1
                    target_reported_count += 1

            target_cash += _cash_delta(trade.side, target_execution)
            copy_cash += _cash_delta(trade.side, copy_execution)
            target_min_cash = min(target_min_cash, target_cash)
            copy_min_cash = min(copy_min_cash, copy_cash)

            target_mark = target_price
            copy_mark = (
                target_price * open_position_sell_multiplier
                if self.config.value_open_positions_at_copy_exit_price
                else target_price
            )
            new_target_market = target_ledger.quantity * target_mark
            new_copy_market = copy_ledger.quantity * copy_mark
            target_market_total += new_target_market - target_market_by_token[address]
            copy_market_total += new_copy_market - copy_market_by_token[address]
            target_market_by_token[address] = new_target_market
            copy_market_by_token[address] = new_copy_market

            trade_results.append(
                {
                    "ordinal": ordinal,
                    "tx_hash": trade.tx_hash,
                    "timestamp_ms": trade.timestamp_ms,
                    "token_address": address,
                    "token_symbol": symbols[address],
                    "launchpad_platform": platforms.get(address, ""),
                    "side": trade.side.value,
                    "requested_token_amount": as_number(trade.token_amount),
                    "executed_token_amount": as_number(target_execution.executed_quantity),
                    "unmatched_token_amount": as_number(target_execution.unmatched_quantity),
                    "target_price_usd": as_number(target_price),
                    "copy_price_usd": as_number(copy_price),
                    "sell_elapsed_since_latest_buy_ms": sell_elapsed_ms,
                    "applied_sell_price_penalty": as_number(applied_sell_penalty),
                    "target_notional_usd": as_number(target_execution.gross_notional_usd),
                    "copy_notional_usd": as_number(copy_execution.gross_notional_usd),
                    "target_fee_usd": as_number(target_execution.fee_usd),
                    "copy_fee_usd": as_number(copy_execution.fee_usd),
                    "target_realized_pnl_usd": as_number(target_execution.realized_pnl_usd),
                    "copy_realized_pnl_usd": as_number(copy_execution.realized_pnl_usd),
                    "target_position_after": as_number(target_ledger.quantity),
                    "copy_position_after": as_number(copy_ledger.quantity),
                }
            )
            equity_curve.append(
                {
                    "ordinal": ordinal,
                    "timestamp_ms": trade.timestamp_ms,
                    "target_pnl_usd": as_number(target_cash + target_market_total),
                    "copy_pnl_usd": as_number(copy_cash + copy_market_total),
                }
            )

        all_addresses = sorted(set(target_ledgers) | set(copy_ledgers))
        per_token: list[dict[str, Any]] = []
        target_summaries: list[AccountSummary] = []
        copy_summaries: list[AccountSummary] = []
        for address in all_addresses:
            target_price = supplied_marks.get(address, latest_prices.get(address, ZERO))
            copy_mark = (
                target_price * open_position_sell_multiplier
                if self.config.value_open_positions_at_copy_exit_price
                else target_price
            )
            target_summary = target_ledgers[address].summary(target_price)
            copy_summary = copy_ledgers[address].summary(copy_mark)
            target_summaries.append(target_summary)
            copy_summaries.append(copy_summary)
            per_token.append(
                {
                    "token_address": address,
                    "token_symbol": symbols.get(address, ""),
                    "launchpad_platform": platforms.get(address, ""),
                    "mark_price_usd": as_number(target_price),
                    "copy_exit_mark_price_usd": as_number(copy_mark),
                    "target_ending_quantity": as_number(target_ledgers[address].quantity),
                    "copy_ending_quantity": as_number(copy_ledgers[address].quantity),
                    "target": target_summary.to_dict(),
                    "copy": copy_summary.to_dict(),
                    "target_reported_realized_pnl_usd": (
                        as_number(target_reported_by_token[address])
                        if target_reported_count_by_token[address]
                        else None
                    ),
                    "pnl_gap_usd": as_number(target_summary.total_pnl_usd - copy_summary.total_pnl_usd),
                }
            )

        target = _sum_summaries(
            target_summaries,
            required_starting_cash_usd=max(ZERO, -target_min_cash),
        )
        copy = _sum_summaries(
            copy_summaries,
            required_starting_cash_usd=max(ZERO, -copy_min_cash),
        )
        pnl_gap = target.total_pnl_usd - copy.total_pnl_usd
        retention = safe_div(copy.total_pnl_usd, target.total_pnl_usd) if target.total_pnl_usd > ZERO else None
        if equity_curve:
            equity_curve[-1] = {
                **equity_curve[-1],
                "target_pnl_usd": as_number(target.total_pnl_usd),
                "copy_pnl_usd": as_number(copy.total_pnl_usd),
                "final_valuation": True,
            }
        data_quality: dict[str, Any] = {
            "duplicates_removed": selection["duplicates_removed"],
            "window_truncated": selection["older_dropped"] > 0,
            "starting_inventory_unknown": (
                target.unmatched_sell_quantity > ZERO or copy.unmatched_sell_quantity > ZERO
            ),
            "unmatched_sells_are_ignored": True,
            "valuation_source": "supplied_mark_price_or_last_trade_price",
            "copy_open_position_valuation": (
                "mark_price_minus_sell_penalty"
                if self.config.value_open_positions_at_copy_exit_price
                else "mark_price"
            ),
            "sell_penalty_model": "time_since_latest_token_buy",
            "sell_penalty_time_bands_ms": {
                "up_to_10000": as_number(self.config.sell_price_penalty_10s),
                "up_to_30000": as_number(self.config.sell_price_penalty_30s),
                "up_to_60000": as_number(self.config.sell_price_penalty_60s),
                "after_60000": as_number(self.config.sell_price_penalty),
            },
            "prediction_market_events_supported": False,
        }
        if normalization_quality:
            data_quality["normalization"] = dict(normalization_quality)

        return BacktestResult(
            target=target,
            copy=copy,
            target_reported_realized_pnl_usd=(target_reported_total if target_reported_count else None),
            target_reported_sell_count=target_reported_count,
            pnl_gap_usd=pnl_gap,
            pnl_retention_ratio=retention,
            processed_trade_count=len(selected),
            input_trade_count=selection["input"],
            deduplicated_trade_count=selection["unique"],
            dropped_older_trade_count=selection["older_dropped"],
            first_trade_time_ms=selected[0].timestamp_ms if selected else None,
            last_trade_time_ms=selected[-1].timestamp_ms if selected else None,
            per_token=per_token,
            equity_curve=equity_curve,
            trade_results=trade_results,
            data_quality=data_quality,
            config=self.config,
        )


def run_backtest(
    trades: Iterable[Trade],
    config: BacktestConfig | None = None,
    *,
    mark_prices_usd: Mapping[str, Any] | None = None,
    normalization_quality: Mapping[str, Any] | None = None,
) -> BacktestResult:
    return CopyBacktester(config).run(
        trades,
        mark_prices_usd=mark_prices_usd,
        normalization_quality=normalization_quality,
    )

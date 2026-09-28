"""FIFO spot-position accounting used by the Robinhood Chain backtest."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import Decimal

from .decimal_utils import ZERO, safe_div
from .models import AccountSummary


@dataclass
class Lot:
    quantity: Decimal
    unit_cost_usd: Decimal


@dataclass(frozen=True)
class Execution:
    requested_quantity: Decimal
    executed_quantity: Decimal
    unmatched_quantity: Decimal
    gross_notional_usd: Decimal
    fee_usd: Decimal
    cost_basis_usd: Decimal
    realized_pnl_usd: Decimal


class PositionLedger:
    """Tracks one token using FIFO lots and exact Decimal arithmetic."""

    def __init__(self) -> None:
        self.lots: deque[Lot] = deque()
        self.quantity = ZERO
        self.gross_buy_usd = ZERO
        self.gross_sell_usd = ZERO
        self.fees_usd = ZERO
        self.realized_pnl_usd = ZERO
        self.net_cash_flow_usd = ZERO
        self.minimum_cash_flow_usd = ZERO
        self.buy_count = 0
        self.sell_count = 0
        self.profitable_sell_count = 0
        self.losing_sell_count = 0
        self.skipped_sell_count = 0
        self.partial_sell_count = 0
        self.unmatched_sell_quantity = ZERO
        self.unmatched_sell_notional_usd = ZERO

    @property
    def ending_cost_basis_usd(self) -> Decimal:
        return sum((lot.quantity * lot.unit_cost_usd for lot in self.lots), ZERO)

    @property
    def required_starting_cash_usd(self) -> Decimal:
        return max(ZERO, -self.minimum_cash_flow_usd)

    def _apply_cash_flow(self, amount_usd: Decimal) -> None:
        self.net_cash_flow_usd += amount_usd
        self.minimum_cash_flow_usd = min(self.minimum_cash_flow_usd, self.net_cash_flow_usd)

    def buy(self, quantity: Decimal, unit_price_usd: Decimal, fee_usd: Decimal = ZERO) -> Execution:
        gross = quantity * unit_price_usd
        total_cost = gross + fee_usd
        self.lots.append(Lot(quantity=quantity, unit_cost_usd=safe_div(total_cost, quantity)))
        self.quantity += quantity
        self.gross_buy_usd += gross
        self.fees_usd += fee_usd
        self.buy_count += 1
        self._apply_cash_flow(-total_cost)
        return Execution(quantity, quantity, ZERO, gross, fee_usd, total_cost, ZERO)

    def sell(
        self,
        requested_quantity: Decimal,
        unit_price_usd: Decimal,
        *,
        fee_rate: Decimal = ZERO,
        fixed_fee_usd: Decimal = ZERO,
        exact_fee_usd: Decimal | None = None,
    ) -> Execution:
        executed = min(requested_quantity, self.quantity)
        unmatched = requested_quantity - executed
        if executed <= ZERO:
            self.skipped_sell_count += 1
            self.unmatched_sell_quantity += requested_quantity
            self.unmatched_sell_notional_usd += requested_quantity * unit_price_usd
            return Execution(requested_quantity, ZERO, requested_quantity, ZERO, ZERO, ZERO, ZERO)

        if unmatched > ZERO:
            self.partial_sell_count += 1
            self.unmatched_sell_quantity += unmatched
            self.unmatched_sell_notional_usd += unmatched * unit_price_usd

        gross = executed * unit_price_usd
        if exact_fee_usd is not None:
            fee = exact_fee_usd * safe_div(executed, requested_quantity)
        else:
            fee = gross * fee_rate + fixed_fee_usd

        remaining = executed
        sold_cost_basis = ZERO
        while remaining > ZERO:
            lot = self.lots[0]
            taken = min(remaining, lot.quantity)
            sold_cost_basis += taken * lot.unit_cost_usd
            lot.quantity -= taken
            remaining -= taken
            if lot.quantity == ZERO:
                self.lots.popleft()

        self.quantity -= executed
        self.gross_sell_usd += gross
        self.fees_usd += fee
        self.sell_count += 1
        trade_pnl = gross - fee - sold_cost_basis
        self.realized_pnl_usd += trade_pnl
        if trade_pnl > ZERO:
            self.profitable_sell_count += 1
        elif trade_pnl < ZERO:
            self.losing_sell_count += 1
        self._apply_cash_flow(gross - fee)
        return Execution(requested_quantity, executed, unmatched, gross, fee, sold_cost_basis, trade_pnl)

    def summary(self, mark_price_usd: Decimal) -> AccountSummary:
        cost_basis = self.ending_cost_basis_usd
        market_value = self.quantity * mark_price_usd
        unrealized = market_value - cost_basis
        total = self.realized_pnl_usd + unrealized
        required_cash = self.required_starting_cash_usd
        roi = safe_div(total, required_cash) if required_cash > ZERO else None
        return AccountSummary(
            gross_buy_usd=self.gross_buy_usd,
            gross_sell_usd=self.gross_sell_usd,
            fees_usd=self.fees_usd,
            realized_pnl_usd=self.realized_pnl_usd,
            unrealized_pnl_usd=unrealized,
            total_pnl_usd=total,
            market_value_usd=market_value,
            ending_cost_basis_usd=cost_basis,
            net_cash_flow_usd=self.net_cash_flow_usd,
            required_starting_cash_usd=required_cash,
            roi_on_required_cash=roi,
            open_position_count=int(self.quantity > ZERO),
            buy_count=self.buy_count,
            sell_count=self.sell_count,
            profitable_sell_count=self.profitable_sell_count,
            losing_sell_count=self.losing_sell_count,
            skipped_sell_count=self.skipped_sell_count,
            partial_sell_count=self.partial_sell_count,
            unmatched_sell_quantity=self.unmatched_sell_quantity,
            unmatched_sell_notional_usd=self.unmatched_sell_notional_usd,
        )

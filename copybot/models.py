"""Public data models for normalized trades and backtest results."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping, Sequence

from .decimal_utils import ONE, ZERO, as_number, decimal_value, safe_div


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"

    @classmethod
    def parse(cls, value: Any) -> "Side":
        normalized = str(value or "").strip().lower()
        if normalized in {"buy", "b"}:
            return cls.BUY
        if normalized in {"sell", "s", "a"}:
            return cls.SELL
        raise ValueError(f"unsupported side: {value!r}")


@dataclass(frozen=True)
class Trade:
    """One normalized spot buy or sell, valued in USD at execution time."""

    tx_hash: str
    timestamp_ms: int
    token_address: str
    side: Side
    token_amount: Decimal
    quote_amount_usd: Decimal
    price_usd: Decimal
    token_symbol: str = ""
    reported_buy_cost_usd: Decimal | None = None
    observed_fee_usd: Decimal = ZERO
    sequence: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.timestamp_ms <= 0:
            raise ValueError("timestamp_ms must be positive")
        if not self.token_address:
            raise ValueError("token_address is required")
        if self.token_amount <= ZERO:
            raise ValueError("token_amount must be positive")
        if self.quote_amount_usd < ZERO:
            raise ValueError("quote_amount_usd cannot be negative")
        if self.price_usd <= ZERO:
            raise ValueError("price_usd must be positive")
        if self.observed_fee_usd < ZERO:
            raise ValueError("observed_fee_usd cannot be negative")
        if self.reported_buy_cost_usd is not None and self.reported_buy_cost_usd < ZERO:
            raise ValueError("reported_buy_cost_usd cannot be negative")

    @classmethod
    def create(
        cls,
        *,
        tx_hash: str,
        timestamp_ms: int,
        token_address: str,
        side: Side | str,
        token_amount: Any,
        quote_amount_usd: Any,
        price_usd: Any | None = None,
        token_symbol: str = "",
        reported_buy_cost_usd: Any | None = None,
        observed_fee_usd: Any = ZERO,
        sequence: int | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "Trade":
        quantity = decimal_value(token_amount, field="token_amount")
        quote = decimal_value(quote_amount_usd, field="quote_amount_usd")
        price = decimal_value(price_usd, field="price_usd", default=ZERO)
        if price <= ZERO and quantity > ZERO and quote > ZERO:
            price = safe_div(quote, quantity)
        return cls(
            tx_hash=str(tx_hash or ""),
            timestamp_ms=int(timestamp_ms),
            token_address=str(token_address).lower(),
            token_symbol=str(token_symbol or ""),
            side=Side.parse(side),
            token_amount=quantity,
            quote_amount_usd=quote,
            price_usd=price,
            reported_buy_cost_usd=(
                decimal_value(reported_buy_cost_usd, field="reported_buy_cost_usd")
                if reported_buy_cost_usd not in (None, "")
                else None
            ),
            observed_fee_usd=decimal_value(observed_fee_usd, field="observed_fee_usd", default=ZERO),
            sequence=sequence,
            metadata=dict(metadata or {}),
        )

    @property
    def effective_price_usd(self) -> Decimal:
        if self.quote_amount_usd > ZERO and self.token_amount > ZERO:
            return safe_div(self.quote_amount_usd, self.token_amount)
        return self.price_usd

    @property
    def unique_key(self) -> tuple[Any, ...]:
        if self.tx_hash:
            return (
                self.tx_hash.lower(),
                self.sequence,
                self.token_address,
                self.side.value,
                str(self.token_amount),
                str(self.quote_amount_usd),
            )
        return (
            self.timestamp_ms,
            self.sequence,
            self.token_address,
            self.side.value,
            str(self.token_amount),
            str(self.quote_amount_usd),
        )


@dataclass(frozen=True)
class BacktestConfig:
    max_trades: int = 5_000
    buy_price_penalty: Decimal = Decimal("0.025")
    sell_price_penalty: Decimal = Decimal("0.025")
    sell_price_penalty_10s: Decimal = Decimal("0.20")
    sell_price_penalty_30s: Decimal = Decimal("0.15")
    sell_price_penalty_60s: Decimal = Decimal("0.10")
    copy_fee_rate: Decimal = ZERO
    copy_fixed_cost_usd: Decimal = ZERO
    include_observed_target_fees: bool = False
    value_open_positions_at_copy_exit_price: bool = True

    def __post_init__(self) -> None:
        if self.max_trades <= 0:
            raise ValueError("max_trades must be positive")
        for field_name in (
            "buy_price_penalty",
            "sell_price_penalty",
            "sell_price_penalty_10s",
            "sell_price_penalty_30s",
            "sell_price_penalty_60s",
            "copy_fee_rate",
        ):
            value = getattr(self, field_name)
            if value < ZERO or value >= ONE:
                raise ValueError(f"{field_name} must be in [0, 1)")
        if self.copy_fixed_cost_usd < ZERO:
            raise ValueError("copy_fixed_cost_usd cannot be negative")

    @classmethod
    def create(cls, **kwargs: Any) -> "BacktestConfig":
        converted = dict(kwargs)
        for key in (
            "buy_price_penalty",
            "sell_price_penalty",
            "sell_price_penalty_10s",
            "sell_price_penalty_30s",
            "sell_price_penalty_60s",
            "copy_fee_rate",
            "copy_fixed_cost_usd",
        ):
            if key in converted:
                converted[key] = decimal_value(converted[key], field=key)
        return cls(**converted)

    def sell_penalty_for_elapsed_ms(self, elapsed_ms: int | None) -> Decimal:
        """Return the mutually exclusive sell penalty after the token's latest buy."""
        if elapsed_ms is None or elapsed_ms < 0:
            return self.sell_price_penalty
        if elapsed_ms <= 10_000:
            return self.sell_price_penalty_10s
        if elapsed_ms <= 30_000:
            return self.sell_price_penalty_30s
        if elapsed_ms <= 60_000:
            return self.sell_price_penalty_60s
        return self.sell_price_penalty


@dataclass
class AccountSummary:
    gross_buy_usd: Decimal = ZERO
    gross_sell_usd: Decimal = ZERO
    fees_usd: Decimal = ZERO
    realized_pnl_usd: Decimal = ZERO
    unrealized_pnl_usd: Decimal = ZERO
    total_pnl_usd: Decimal = ZERO
    market_value_usd: Decimal = ZERO
    ending_cost_basis_usd: Decimal = ZERO
    net_cash_flow_usd: Decimal = ZERO
    required_starting_cash_usd: Decimal = ZERO
    roi_on_required_cash: Decimal | None = None
    open_position_count: int = 0
    buy_count: int = 0
    sell_count: int = 0
    profitable_sell_count: int = 0
    losing_sell_count: int = 0
    skipped_sell_count: int = 0
    partial_sell_count: int = 0
    unmatched_sell_quantity: Decimal = ZERO
    unmatched_sell_notional_usd: Decimal = ZERO

    def to_dict(self) -> dict[str, Any]:
        decided_sells = self.profitable_sell_count + self.losing_sell_count
        return {
            "gross_buy_usd": as_number(self.gross_buy_usd),
            "gross_sell_usd": as_number(self.gross_sell_usd),
            "fees_usd": as_number(self.fees_usd),
            "realized_pnl_usd": as_number(self.realized_pnl_usd),
            "unrealized_pnl_usd": as_number(self.unrealized_pnl_usd),
            "total_pnl_usd": as_number(self.total_pnl_usd),
            "market_value_usd": as_number(self.market_value_usd),
            "ending_cost_basis_usd": as_number(self.ending_cost_basis_usd),
            "net_cash_flow_usd": as_number(self.net_cash_flow_usd),
            "required_starting_cash_usd": as_number(self.required_starting_cash_usd),
            "roi_on_required_cash": as_number(self.roi_on_required_cash),
            "open_position_count": self.open_position_count,
            "buy_count": self.buy_count,
            "sell_count": self.sell_count,
            "win_rate": (self.profitable_sell_count / decided_sells if decided_sells else None),
            "profitable_sell_count": self.profitable_sell_count,
            "losing_sell_count": self.losing_sell_count,
            "skipped_sell_count": self.skipped_sell_count,
            "partial_sell_count": self.partial_sell_count,
            "unmatched_sell_quantity": as_number(self.unmatched_sell_quantity),
            "unmatched_sell_notional_usd": as_number(self.unmatched_sell_notional_usd),
        }


@dataclass
class BacktestResult:
    target: AccountSummary
    copy: AccountSummary
    target_reported_realized_pnl_usd: Decimal | None
    target_reported_sell_count: int
    pnl_gap_usd: Decimal
    pnl_retention_ratio: Decimal | None
    processed_trade_count: int
    input_trade_count: int
    deduplicated_trade_count: int
    dropped_older_trade_count: int
    first_trade_time_ms: int | None
    last_trade_time_ms: int | None
    per_token: Sequence[Mapping[str, Any]]
    equity_curve: Sequence[Mapping[str, Any]]
    trade_results: Sequence[Mapping[str, Any]]
    data_quality: Mapping[str, Any]
    config: BacktestConfig

    def to_dict(self, *, include_trade_results: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": "ok",
            "basis": f"latest_{self.config.max_trades}_same_token_amount_configured_price_penalties",
            "target": self.target.to_dict(),
            "copy": self.copy.to_dict(),
            "target_reported_realized_pnl_usd": as_number(self.target_reported_realized_pnl_usd),
            "target_reported_sell_count": self.target_reported_sell_count,
            "pnl_gap_usd": as_number(self.pnl_gap_usd),
            "pnl_retention_ratio": as_number(self.pnl_retention_ratio),
            "processed_trade_count": self.processed_trade_count,
            "input_trade_count": self.input_trade_count,
            "deduplicated_trade_count": self.deduplicated_trade_count,
            "dropped_older_trade_count": self.dropped_older_trade_count,
            "first_trade_time_ms": self.first_trade_time_ms,
            "last_trade_time_ms": self.last_trade_time_ms,
            "per_token": list(self.per_token),
            "equity_curve": list(self.equity_curve),
            "data_quality": dict(self.data_quality),
            "config": {
                "max_trades": self.config.max_trades,
                "buy_price_penalty": as_number(self.config.buy_price_penalty),
                "sell_price_penalty": as_number(self.config.sell_price_penalty),
                "sell_price_penalty_10s": as_number(self.config.sell_price_penalty_10s),
                "sell_price_penalty_30s": as_number(self.config.sell_price_penalty_30s),
                "sell_price_penalty_60s": as_number(self.config.sell_price_penalty_60s),
                "sell_penalty_time_basis": "milliseconds_since_latest_token_buy",
                "sell_quantity_mode": "same_token_amount_capped_by_copy_balance",
                "buy_quantity_mode": "same_token_amount",
                "copy_fee_rate": as_number(self.config.copy_fee_rate),
                "copy_fixed_cost_usd": as_number(self.config.copy_fixed_cost_usd),
                "include_observed_target_fees": self.config.include_observed_target_fees,
                "value_open_positions_at_copy_exit_price": self.config.value_open_positions_at_copy_exit_price,
            },
        }
        if include_trade_results:
            payload["trade_results"] = list(self.trade_results)
        return payload

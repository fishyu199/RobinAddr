from __future__ import annotations

import unittest
from decimal import Decimal

from copybot import BacktestConfig, Trade, run_backtest


def trade(
    sequence: int,
    side: str,
    quantity: str,
    price: str,
    *,
    token: str = "0xtoken",
    timestamp_ms: int | None = None,
    tx_hash: str | None = None,
) -> Trade:
    qty = Decimal(quantity)
    px = Decimal(price)
    return Trade.create(
        tx_hash=tx_hash or f"0x{sequence}",
        timestamp_ms=timestamp_ms or 1_700_000_000_000 + sequence * 61_000,
        token_address=token,
        token_symbol="TEST",
        side=side,
        token_amount=qty,
        quote_amount_usd=qty * px,
        price_usd=px,
        sequence=sequence,
    )


class BacktestTests(unittest.TestCase):
    def test_round_trip_matches_legacy_copy_semantics(self) -> None:
        result = run_backtest(
            [trade(1, "buy", "100", "1"), trade(2, "sell", "100", "1.2")]
        )
        self.assertEqual(result.target.total_pnl_usd, Decimal("20.0"))
        self.assertEqual(result.copy.total_pnl_usd, Decimal("14.5000"))
        self.assertEqual(result.copy.gross_buy_usd, Decimal("102.500"))
        self.assertEqual(result.copy.gross_sell_usd, Decimal("117.0000"))
        self.assertEqual(result.target.open_position_count, 0)

    def test_open_position_uses_conservative_copy_exit_price(self) -> None:
        result = run_backtest(
            [trade(1, "buy", "100", "1")],
            mark_prices_usd={"0xtoken": "1.2"},
        )
        self.assertEqual(result.target.total_pnl_usd, Decimal("20.0"))
        self.assertEqual(result.copy.total_pnl_usd, Decimal("14.5000"))
        self.assertEqual(result.copy.market_value_usd, Decimal("117.0000"))

    def test_sell_slippage_uses_exclusive_time_since_latest_buy_bands(self) -> None:
        base_time = 1_700_000_000_000
        cases = (
            (10_000, Decimal("0.20"), Decimal("80.0")),
            (10_001, Decimal("0.15"), Decimal("85.0")),
            (30_000, Decimal("0.15"), Decimal("85.0")),
            (30_001, Decimal("0.10"), Decimal("90.0")),
            (60_000, Decimal("0.10"), Decimal("90.0")),
            (60_001, Decimal("0.025"), Decimal("97.500")),
        )
        for elapsed_ms, expected_penalty, expected_sell in cases:
            with self.subTest(elapsed_ms=elapsed_ms):
                result = run_backtest(
                    [
                        trade(1, "buy", "100", "1", timestamp_ms=base_time),
                        trade(2, "sell", "100", "1", timestamp_ms=base_time + elapsed_ms),
                    ]
                )
                sell = result.trade_results[1]
                self.assertEqual(Decimal(str(sell["applied_sell_price_penalty"])), expected_penalty)
                self.assertEqual(sell["sell_elapsed_since_latest_buy_ms"], elapsed_ms)
                self.assertEqual(result.copy.gross_sell_usd, expected_sell)

    def test_sell_slippage_uses_most_recent_buy_for_same_token(self) -> None:
        base_time = 1_700_000_000_000
        result = run_backtest(
            [
                trade(1, "buy", "50", "1", timestamp_ms=base_time),
                trade(2, "buy", "50", "1", timestamp_ms=base_time + 120_000),
                trade(3, "sell", "100", "1", timestamp_ms=base_time + 129_000),
            ]
        )
        sell = result.trade_results[2]
        self.assertEqual(sell["sell_elapsed_since_latest_buy_ms"], 9_000)
        self.assertEqual(Decimal(str(sell["applied_sell_price_penalty"])), Decimal("0.2"))
        self.assertEqual(result.copy.gross_sell_usd, Decimal("80.0"))

    def test_sell_is_capped_and_missing_starting_inventory_is_reported(self) -> None:
        result = run_backtest(
            [trade(1, "buy", "50", "1"), trade(2, "sell", "100", "1.2")]
        )
        self.assertEqual(result.target.gross_sell_usd, Decimal("60.0"))
        self.assertEqual(result.target.unmatched_sell_quantity, Decimal("50"))
        self.assertEqual(result.copy.unmatched_sell_quantity, Decimal("50"))
        self.assertEqual(result.target.partial_sell_count, 1)
        self.assertTrue(result.data_quality["starting_inventory_unknown"])

    def test_sell_before_any_window_buy_is_not_free_profit(self) -> None:
        result = run_backtest([trade(1, "sell", "10", "2")])
        self.assertEqual(result.target.total_pnl_usd, Decimal("0"))
        self.assertEqual(result.copy.total_pnl_usd, Decimal("0"))
        self.assertEqual(result.target.skipped_sell_count, 1)
        self.assertEqual(result.target.unmatched_sell_notional_usd, Decimal("20"))

    def test_latest_limit_is_applied_before_chronological_processing(self) -> None:
        trades = [trade(i, "buy", "1", str(i)) for i in range(1, 6)]
        result = run_backtest(trades, BacktestConfig(max_trades=3))
        self.assertEqual(result.processed_trade_count, 3)
        self.assertEqual(result.dropped_older_trade_count, 2)
        self.assertEqual([row["ordinal"] for row in result.trade_results], [1, 2, 3])
        self.assertEqual(
            [row["target_price_usd"] for row in result.trade_results],
            [3.0, 4.0, 5.0],
        )

    def test_duplicate_activity_is_removed(self) -> None:
        item = trade(1, "buy", "2", "3")
        result = run_backtest([item, item])
        self.assertEqual(result.input_trade_count, 2)
        self.assertEqual(result.deduplicated_trade_count, 1)
        self.assertEqual(result.processed_trade_count, 1)
        self.assertEqual(result.data_quality["duplicates_removed"], 1)

    def test_zero_penalties_make_target_and_copy_equal(self) -> None:
        result = run_backtest(
            [trade(1, "buy", "10", "4"), trade(2, "sell", "5", "5")],
            BacktestConfig(buy_price_penalty=Decimal("0"), sell_price_penalty=Decimal("0")),
        )
        self.assertEqual(result.target.total_pnl_usd, result.copy.total_pnl_usd)
        self.assertEqual(result.target.realized_pnl_usd, result.copy.realized_pnl_usd)

    def test_fifo_realized_and_unrealized_pnl(self) -> None:
        result = run_backtest(
            [
                trade(1, "buy", "10", "1"),
                trade(2, "buy", "10", "2"),
                trade(3, "sell", "15", "3"),
            ],
            mark_prices_usd={"0xtoken": "4"},
        )
        self.assertEqual(result.target.realized_pnl_usd, Decimal("25"))
        self.assertEqual(result.target.ending_cost_basis_usd, Decimal("10"))
        self.assertEqual(result.target.unrealized_pnl_usd, Decimal("10"))
        self.assertEqual(result.target.total_pnl_usd, Decimal("35"))


if __name__ == "__main__":
    unittest.main()

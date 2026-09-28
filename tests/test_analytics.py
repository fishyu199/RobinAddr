from __future__ import annotations

import unittest

from copybot import Trade, build_legacy_metrics, render_telegram_report, run_backtest
from copybot.analytics import _score


class AnalyticsTests(unittest.TestCase):
    def test_median_hold_does_not_affect_score(self) -> None:
        inputs = {
            "copy_pnl": 12_000,
            "recent_copy_pnl": 3_000,
            "loss_rate": 5,
            "recent_loss_rate": 5,
            "profitable_days_14d": 10,
            "loss_days_14d": 0,
            "total_pnl_14d": 5_000,
            "pnl_ratio_14d": 5,
            "days_since_active": 1,
            "win_rate": 50,
            "profit_loss_ratio": 2,
            "token_count": 20,
            "last_2d_profit_share": 20,
            "recent_target_pnl": 4_000,
        }

        for holding_seconds in (0, 59, 60, 119, 120, 299, 300, None):
            with self.subTest(holding_seconds=holding_seconds):
                self.assertEqual(
                    _score(**inputs, median_holding_time_seconds=holding_seconds),
                    100,
                )

    def test_recent_copy_loss_penalty_is_capped_at_ten_points(self) -> None:
        inputs = {
            "copy_pnl": 12_000,
            "recent_copy_pnl": 3_000,
            "loss_rate": 5,
            "profitable_days_14d": 10,
            "loss_days_14d": 0,
            "total_pnl_14d": 5_000,
            "pnl_ratio_14d": 5,
            "days_since_active": 1,
            "win_rate": 50,
            "profit_loss_ratio": 2,
            "token_count": 20,
            "median_holding_time_seconds": 0,
            "last_2d_profit_share": 20,
            "recent_target_pnl": 4_000,
        }
        for recent_loss_rate in (60.01, 75, 100):
            with self.subTest(recent_loss_rate=recent_loss_rate):
                self.assertEqual(
                    _score(**inputs, recent_loss_rate=recent_loss_rate),
                    75,
                )

    def test_negative_target_uses_extra_loss_instead_of_rates(self) -> None:
        result = run_backtest(
            [
                Trade.create(
                    tx_hash="0xb",
                    timestamp_ms=1_700_000_000_000,
                    token_address="0xtoken",
                    token_symbol="LOSS",
                    side="buy",
                    token_amount="100",
                    quote_amount_usd="100",
                    price_usd="1",
                ),
                Trade.create(
                    tx_hash="0xs",
                    timestamp_ms=1_700_000_061_000,
                    token_address="0xtoken",
                    token_symbol="LOSS",
                    side="sell",
                    token_amount="100",
                    quote_amount_usd="90",
                    price_usd="0.9",
                ),
            ]
        )
        metrics = build_legacy_metrics(result, now_ms=1_700_000_061_000)
        self.assertIsNone(result.pnl_retention_ratio)
        self.assertIsNone(metrics["copy_loss_rate"])
        self.assertIsNone(metrics["pnl_retention_rate"])
        self.assertAlmostEqual(metrics["extra_loss_usd"], 4.75)
        self.assertEqual(metrics["score"], 0)
        report = render_telegram_report(result, metrics=metrics)
        self.assertIn("跟单损耗         N/A", report)
        self.assertIn("利润保留率       N/A", report)
        self.assertIn("额外亏损金额     $4.75", report)

    def test_legacy_and_robinhood_metrics_are_both_present(self) -> None:
        result = run_backtest(
            [
                Trade.create(
                    tx_hash="0xb",
                    timestamp_ms=1_700_000_000_000,
                    token_address="0xtoken",
                    token_symbol="WIN",
                    side="buy",
                    token_amount="10",
                    quote_amount_usd="10",
                    price_usd="1",
                ),
                Trade.create(
                    tx_hash="0xs",
                    timestamp_ms=1_700_000_061_000,
                    token_address="0xtoken",
                    token_symbol="WIN",
                    side="sell",
                    token_amount="10",
                    quote_amount_usd="12",
                    price_usd="1.2",
                ),
            ]
        )
        metrics = build_legacy_metrics(result, include_all_tokens=True, now_ms=1_700_000_061_000)
        for key in (
            "score",
            "actual_pnl",
            "copy_backtest_pnl",
            "copy_loss_rate",
            "token_win_rate",
            "sell_win_rate",
            "required_starting_cash_usd",
            "copy_roi_on_required_cash",
            "recent_20_stats",
            "daily_stats",
            "target_daily_pnl_14d",
            "copy_daily_pnl_14d",
            "all_markets",
            "all_tokens",
            "pnl_svg",
            "referral_url",
        ):
            self.assertIn(key, metrics)
        self.assertNotIn("hedged_markets", metrics)
        self.assertNotIn("hedged_pct", metrics)
        self.assertNotIn("hedge_pct", metrics["all_tokens"][0])
        self.assertNotIn("hedge_pct", metrics["recent_20_tokens"][0])
        self.assertEqual(len(metrics["target_daily_pnl_14d"]), 14)
        self.assertEqual(len(metrics["copy_daily_pnl_14d"]), 14)
        self.assertAlmostEqual(sum(item["pnl"] for item in metrics["target_daily_pnl_14d"]), 2.0)
        self.assertAlmostEqual(sum(item["pnl"] for item in metrics["copy_daily_pnl_14d"]), 1.45)


if __name__ == "__main__":
    unittest.main()

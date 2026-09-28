from __future__ import annotations

import unittest

from apps.api.robincop_api.wallet_summary import build_wallet_summary


class WalletSummaryTests(unittest.TestCase):
    def test_keeps_only_leaderboard_fields(self) -> None:
        summary = build_wallet_summary({"win_rate": 55.5, "trade_results": [1, 2, 3]})
        self.assertEqual(summary["win_rate"], 55.5)
        self.assertNotIn("trade_results", summary)

    def test_handles_missing_metrics(self) -> None:
        summary = build_wallet_summary(None)
        self.assertIsNone(summary["copy_loss_rate"])


if __name__ == "__main__":
    unittest.main()

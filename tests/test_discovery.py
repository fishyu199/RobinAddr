from __future__ import annotations

import unittest

from copybot.discovery import matches_filters, ranking_value


class DiscoveryRankingTests(unittest.TestCase):
    def test_ranking_value_supports_profit_and_derived_pnl(self) -> None:
        row = {"realized_profit": "250", "realized_profit_cost": "1000"}
        self.assertEqual(str(ranking_value(row, "realized_profit")), "250")
        self.assertEqual(str(ranking_value(row, "pnl")), "0.25")

    def test_filters_are_explicit_and_decimal_safe(self) -> None:
        row = {"realized_profit": "250.50", "total_cost": "5000", "buy": 20, "sell": 10}
        self.assertTrue(
            matches_filters(row, {"min_realized_profit": 200, "min_total_cost": 4000})
        )
        self.assertFalse(matches_filters(row, {"min_buy": 21}))
        self.assertTrue(matches_filters(row, {"unknown_filter": 999999}))

if __name__ == "__main__":
    unittest.main()

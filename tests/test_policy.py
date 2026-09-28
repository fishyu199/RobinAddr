from __future__ import annotations

import unittest

from apps.api.robincop_api.config import (
    normalize_analysis_concurrency,
    normalize_discovery_interval_minutes,
)


class DiscoveryIntervalTests(unittest.TestCase):
    def test_uses_minute_setting(self) -> None:
        self.assertEqual(
            normalize_discovery_interval_minutes({"interval_minutes": 30}, default=60),
            30,
        )

    def test_converts_legacy_hours(self) -> None:
        self.assertEqual(
            normalize_discovery_interval_minutes({"interval_hours": 2}, default=30),
            120,
        )

    def test_minute_setting_wins_during_migration(self) -> None:
        self.assertEqual(
            normalize_discovery_interval_minutes(
                {"interval_minutes": 30, "interval_hours": 2}, default=60
            ),
            30,
        )

    def test_clamps_unsafe_values(self) -> None:
        self.assertEqual(
            normalize_discovery_interval_minutes({"interval_minutes": 1}, default=30),
            5,
        )


class AnalysisConcurrencyTests(unittest.TestCase):
    def test_defaults_to_one(self) -> None:
        self.assertEqual(normalize_analysis_concurrency(None), 1)

    def test_clamps_to_small_host_safe_limit(self) -> None:
        self.assertEqual(normalize_analysis_concurrency(10), 2)

    def test_handles_invalid_stored_value(self) -> None:
        self.assertEqual(normalize_analysis_concurrency("invalid"), 1)


if __name__ == "__main__":
    unittest.main()

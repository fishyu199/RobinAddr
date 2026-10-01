from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import patch

from copybot import SUPPORTED_LANGUAGES, Trade, render_telegram_report, run_backtest
from copybot.analytics import build_legacy_metrics


class TelegramReportTests(unittest.TestCase):
    @staticmethod
    def _simple_result():
        return run_backtest(
            [
                Trade.create(
                    tx_hash="0xbuy",
                    timestamp_ms=1_700_000_000_000,
                    token_address="0xtoken",
                    token_symbol="TOK",
                    side="buy",
                    token_amount="10",
                    quote_amount_usd="10",
                    price_usd="1",
                ),
                Trade.create(
                    tx_hash="0xsell",
                    timestamp_ms=1_700_000_100_000,
                    token_address="0xtoken",
                    token_symbol="TOK",
                    side="sell",
                    token_amount="10",
                    quote_amount_usd="12",
                    price_usd="1.2",
                ),
            ]
        )

    def test_supports_every_language_from_the_original_poly_script(self) -> None:
        expected_titles = {
            "en": "Copyable Wallet",
            "zh-CN": "发现可跟单钱包",
            "zh-TW": "發現可跟單錢包",
            "ja": "コピー可能なウォレット",
            "ko": "카피 트레이딩 지갑",
            "ru": "Кошелёк для копирования",
            "fr": "Portefeuille à copier",
            "ar": "محفظة قابلة للنسخ",
            "pt": "Carteira para copiar",
            "es": "Billetera para copiar",
        }
        self.assertEqual(tuple(expected_titles), SUPPORTED_LANGUAGES)
        for language, title in expected_titles.items():
            with self.subTest(language=language):
                report = render_telegram_report(
                    self._simple_result(), wallet_address="0xwallet", lang=language
                )
                self.assertIn(title, report)
                self.assertLessEqual(len(report), 4_096)

    def test_stored_metrics_render_the_same_report_without_recalculation(self) -> None:
        result = self._simple_result()
        profile = {"name": "Name <One>"}
        metrics = result.to_dict()
        metrics.update(build_legacy_metrics(result, now_ms=1_700_001_000_000))
        metrics["score"] = 77
        metrics["gmgn_stats_30d"] = {"common": profile}
        expected = render_telegram_report(result, metrics=metrics, profile=profile, wallet_address="0xwallet")
        with patch("copybot.telegram_report.build_legacy_metrics", side_effect=AssertionError("must not recalculate")):
            actual = render_telegram_report(metrics=metrics, wallet_address="0xwallet")
        self.assertEqual(actual, expected)
        self.assertIn("77/100", actual)
        self.assertIn("Name &lt;One&gt;", actual)

    def test_missing_report_input_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            render_telegram_report()

    def test_report_is_telegram_html_and_escapes_dynamic_text(self) -> None:
        trades = [
            Trade.create(
                tx_hash="0x1",
                timestamp_ms=1_700_000_000_000,
                token_address="0xtoken",
                token_symbol="A<B&C>",
                side="buy",
                token_amount="100",
                quote_amount_usd="100",
                price_usd="1",
            ),
            Trade.create(
                tx_hash="0x2",
                timestamp_ms=1_700_000_100_000,
                token_address="0xtoken",
                token_symbol="A<B&C>",
                side="sell",
                token_amount="100",
                quote_amount_usd="120",
                price_usd="1.2",
            ),
        ]
        report = render_telegram_report(
            run_backtest(trades),
            wallet_address="0xabc<unsafe>",
            lang="zh-CN",
            profile={"twitter_name": "Name <One>", "twitter_username": "test&user"},
        )
        self.assertIn("目标地址 PnL", report)
        self.assertIn("平均目标PnL", report)
        self.assertNotIn("代币平台分类", report)
        self.assertIn("+$20.00", report)
        self.assertIn("+$14.50", report)
        self.assertIn("0xabc&lt;unsafe&gt;", report)
        self.assertIn("A&lt;B&amp;C&gt;", report)
        self.assertIn("Name &lt;One&gt; (@test&amp;user)", report)
        self.assertNotIn("Polymarket", report)
        self.assertNotIn("REDEEM", report)
        self.assertLessEqual(len(report), 4_096)

    def test_copy_trade_links_use_the_current_wallet_address(self) -> None:
        wallet = "0x8BD8713D4E964EE9158363E2AA1F1746EC88C651"
        expected_url = (
            "https://t.me/RobinCop_AI_Bot?start="
            "A_ZETLYPGS_0x8bd8713d4e964ee9158363e2aa1f1746ec88c651"
        )
        report = render_telegram_report(self._simple_result(), wallet_address=wallet, lang="en")
        self.assertEqual(report.count(f'href="{expected_url}"'), 2)
        self.assertNotIn("start=ref_WMNE5NPY", report)
        expected_web_url = (
            "https://robincop.com/wallet/"
            "0x8bd8713d4e964ee9158363e2aa1f1746ec88c651"
        )
        self.assertEqual(report.count(f'href="{expected_web_url}"'), 1)
        self.assertIn(
            f'>⚡️ Copy Trade</a> / <a href="{expected_web_url}">🔗 View in Web</a>',
            report,
        )
        self.assertNotIn("Token Platform Categories", report)

    def test_recent_and_daily_tables_are_aligned_and_use_token_roi(self) -> None:
        report = render_telegram_report(self._simple_result(), wallet_address="0xwallet", lang="en")
        self.assertIn("| Token / Date   |      PNL |     Copy |     Hold |", report)
        self.assertIn("| TOK      11-14 |  +20.00% |  +14.15% |    1m ✅ |", report)
        self.assertNotIn("Token        Target      Copy        Cost", report)
        self.assertIn("| Date  |   Tx |  Volume |       PNL |      Copy |", report)

    def test_stored_legacy_token_rows_can_render_roi_and_holding_time(self) -> None:
        result = self._simple_result()
        metrics = result.to_dict()
        metrics.update(build_legacy_metrics(result, include_all_tokens=True))
        for row in metrics["recent_20_tokens"]:
            row.pop("target_invested", None)
            row.pop("copy_invested", None)
            row.pop("holding_time_seconds", None)
            row.pop("is_closed", None)
        report = render_telegram_report(metrics=metrics, wallet_address="0xwallet", lang="en")
        self.assertIn("| TOK      11-14 |  +20.00% |  +14.15% |    1m ✅ |", report)

    def test_explicit_copy_trade_link_override_is_preserved(self) -> None:
        custom_url = "https://example.com/custom-copy"
        report = render_telegram_report(
            self._simple_result(),
            wallet_address="0xwallet",
            referral_url=custom_url,
        )
        self.assertEqual(report.count(f'href="{custom_url}"'), 2)

    def test_long_report_reduces_tables_to_fit_telegram_limit(self) -> None:
        trades = []
        for index in range(40):
            token = f"0x{index:040x}"
            trades.extend(
                [
                    Trade.create(
                        tx_hash=f"0xb{index}",
                        timestamp_ms=1_700_000_000_000 + index * 86_400_000,
                        token_address=token,
                        token_symbol=f"TOKEN_{index}_LONG_NAME",
                        side="buy",
                        token_amount="10",
                        quote_amount_usd="10",
                        price_usd="1",
                    ),
                    Trade.create(
                        tx_hash=f"0xs{index}",
                        timestamp_ms=1_700_000_001_000 + index * 86_400_000,
                        token_address=token,
                        token_symbol=f"TOKEN_{index}_LONG_NAME",
                        side="sell",
                        token_amount="10",
                        quote_amount_usd="11",
                        price_usd="1.1",
                    ),
                ]
            )
        report = render_telegram_report(run_backtest(trades), wallet_address="0xwallet")
        self.assertLessEqual(len(report), 4_096)
        self.assertTrue(report.endswith("</i>"))


if __name__ == "__main__":
    unittest.main()

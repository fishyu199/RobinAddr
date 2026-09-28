from __future__ import annotations

import unittest
from decimal import Decimal

from copybot import SUPPORTED_LANGUAGES, Trade, render_telegram_report, run_backtest


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
        self.assertIn("代币平台分类", report)
        self.assertIn("+$20.00", report)
        self.assertIn("+$14.50", report)
        self.assertIn("0xabc&lt;unsafe&gt;", report)
        self.assertIn("A&lt;B&amp;C&gt;", report)
        self.assertIn("Name &lt;One&gt; (@test&amp;user)", report)
        self.assertNotIn("Polymarket", report)
        self.assertNotIn("REDEEM", report)
        self.assertLessEqual(len(report), 4_096)

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

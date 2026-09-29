from __future__ import annotations

import copy
import importlib
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException, Response
from sqlalchemy import create_engine, func, inspect, select, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from apps.api.robincop_api import backfill_reports as backfill
from apps.api.robincop_api import main
from apps.api.robincop_api.database import Base
from apps.api.robincop_api.models import AnalysisRun, PublishedWallet
from apps.api.robincop_api.services import analysis
from copybot import run_backtest
from copybot.analytics import build_legacy_metrics
from copybot.telegram_report import render_telegram_report


@compiles(JSONB, "sqlite")
def sqlite_jsonb(_type, _compiler, **_kwargs):
    return "JSON"


ADDRESS = "0x" + "1" * 40


def stored_metrics(score=75):
    result = run_backtest([])
    metrics = result.to_dict()
    metrics.update(build_legacy_metrics(result, now_ms=1_700_001_000_000))
    metrics["score"] = score
    return metrics


class WalletReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def add_wallet(self, address=ADDRESS, report=None, metrics=None):
        wallet = PublishedWallet(
            address=address, score=75, metrics=stored_metrics() if metrics is None else metrics,
            report_text=report, analyzed_at=datetime(2026, 9, 28, tzinfo=timezone.utc),
        )
        self.db.add(wallet)
        self.db.commit()
        return wallet

    def test_analysis_replaces_latest_report_and_does_not_archive_text(self) -> None:
        for score in (75, 80):
            metrics = stored_metrics(score)
            report = render_telegram_report(metrics=metrics, wallet_address=ADDRESS)
            with patch.object(analysis, "analyze_wallet", return_value={"metrics": metrics, "report_text": report}) as analyze:
                run = analysis.analyze_and_store(self.db, ADDRESS, trigger="test")
            self.assertEqual(analyze.call_args.kwargs["lang"], "zh-CN")
            self.assertEqual(run.status, "completed")
            self.assertNotIn("report_text", run.result)
            self.db.expire_all()
            wallet = self.db.get(PublishedWallet, ADDRESS)
            self.assertEqual(wallet.report_text, report)
            self.assertEqual(wallet.metrics["score"], score)
            self.assertEqual(wallet.score, score)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(PublishedWallet)), 1)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(AnalysisRun)), 2)

    def test_failed_save_preserves_previous_metrics_and_report(self) -> None:
        wallet = self.add_wallet(report="previous report")
        before = copy.deepcopy(wallet.metrics)
        with (
            patch.object(analysis, "analyze_wallet", return_value={"metrics": stored_metrics(90), "report_text": "new report"}),
            patch.object(analysis, "build_wallet_summary", side_effect=RuntimeError("summary failed")),
        ):
            with self.assertRaisesRegex(RuntimeError, "summary failed"):
                analysis.analyze_and_store(self.db, ADDRESS, trigger="test")
        self.db.expire_all()
        wallet = self.db.get(PublishedWallet, ADDRESS)
        self.assertEqual(wallet.report_text, "previous report")
        self.assertEqual(wallet.metrics, before)
        self.assertEqual(wallet.score, 75)
        self.assertEqual(self.db.scalar(select(AnalysisRun.status)), "failed")

    def test_empty_report_does_not_replace_previous_result(self) -> None:
        self.add_wallet(report="previous report")
        with patch.object(analysis, "analyze_wallet", return_value={"metrics": stored_metrics(90), "report_text": ""}):
            with self.assertRaisesRegex(ValueError, "empty report"):
                analysis.analyze_and_store(self.db, ADDRESS, trigger="test")
        self.db.expire_all()
        self.assertEqual(self.db.get(PublishedWallet, ADDRESS).report_text, "previous report")

    def test_detail_returns_stored_text_in_all_modes_without_analysis(self) -> None:
        report = "<b>中文报告</b>\n<pre>+100</pre>"
        self.add_wallet(report=report)
        with patch.object(analysis, "analyze_wallet", side_effect=AssertionError("must not analyze")):
            for compact, summary in ((False, False), (True, False), (True, True)):
                payload = main.get_wallet(ADDRESS, Response(), compact=compact, summary_only=summary, db=self.db)
                self.assertEqual(payload["report_text"], report)
        wallet = self.db.get(PublishedWallet, ADDRESS)
        self.assertNotIn("report_text", main.wallet_payload(wallet))
        self.assertNotIn("report_text", [column.key for column in main.wallet_summary_columns()])
        wallet.manual_unlisted = True
        self.db.commit()
        with self.assertRaises(HTTPException) as raised:
            main.get_wallet(ADDRESS, Response(), compact=False, summary_only=False, db=self.db)
        self.assertEqual(raised.exception.status_code, 404)

    def test_legacy_detail_returns_null_until_backfilled(self) -> None:
        self.add_wallet()
        payload = main.get_wallet(ADDRESS, Response(), compact=False, summary_only=False, db=self.db)
        self.assertIsNone(payload["report_text"])

    def test_backfill_preview_then_apply_is_idempotent_and_preserves_metrics(self) -> None:
        wallet = self.add_wallet()
        original_metrics = copy.deepcopy(wallet.metrics)
        original_time = wallet.analyzed_at
        other = "0x" + "2" * 40
        self.add_wallet(address=other, report="keep this report")
        preview = backfill.backfill_reports(self.db)
        self.assertEqual(preview["generated"], 1)
        self.assertEqual(preview["updated"], 0)
        self.db.expire_all()
        self.assertIsNone(self.db.get(PublishedWallet, ADDRESS).report_text)
        with patch.object(analysis, "analyze_wallet", side_effect=AssertionError("must not analyze")):
            counts = backfill.backfill_reports(self.db, apply=True, batch_size=1)
        self.assertEqual(counts["updated"], 1)
        self.assertEqual(counts["errors"], [])
        self.db.expire_all()
        wallet = self.db.get(PublishedWallet, ADDRESS)
        self.assertEqual(wallet.report_text, render_telegram_report(metrics=original_metrics, wallet_address=ADDRESS))
        self.assertEqual(wallet.metrics, original_metrics)
        self.assertEqual(wallet.analyzed_at, original_time)
        self.assertEqual(self.db.get(PublishedWallet, other).report_text, "keep this report")
        self.assertEqual(backfill.backfill_reports(self.db, apply=True)["scanned"], 0)

    def test_backfill_does_not_write_report_from_an_older_analysis(self) -> None:
        self.add_wallet()

        def concurrent_analysis(**_kwargs):
            self.db.execute(update(PublishedWallet).where(PublishedWallet.address == ADDRESS).values(
                analyzed_at=datetime(2026, 9, 29, tzinfo=timezone.utc), metrics=stored_metrics(90),
            ))
            return "stale report"

        with patch.object(backfill, "render_telegram_report", side_effect=concurrent_analysis):
            counts = backfill.backfill_reports(self.db, apply=True)
        self.assertEqual(counts["updated"], 0)
        self.assertEqual(counts["skipped"], 1)
        self.db.expire_all()
        self.assertIsNone(self.db.get(PublishedWallet, ADDRESS).report_text)

    def test_backfill_continues_past_incomplete_metrics(self) -> None:
        self.add_wallet(metrics={})
        second = "0x" + "2" * 40
        self.add_wallet(address=second)
        counts = backfill.backfill_reports(self.db, apply=True, batch_size=1)
        self.assertEqual(counts["updated"], 1)
        self.assertEqual(counts["errors"][0]["address"], ADDRESS)
        self.db.expire_all()
        self.assertIsNone(self.db.get(PublishedWallet, ADDRESS).report_text)
        self.assertIsNotNone(self.db.get(PublishedWallet, second).report_text)

    def test_report_migration_preserves_existing_rows_and_can_repeat(self) -> None:
        migration = importlib.import_module("apps.api.alembic.versions.0005_wallet_report_text")
        engine = create_engine("sqlite://")
        try:
            with engine.begin() as connection:
                connection.execute(text("CREATE TABLE published_wallets (address TEXT PRIMARY KEY)"))
                connection.execute(text("INSERT INTO published_wallets (address) VALUES ('existing')"))
                with patch.object(migration, "op", Operations(MigrationContext.configure(connection))):
                    migration.upgrade()
                    migration.upgrade()
                columns = {column["name"]: column for column in inspect(connection).get_columns("published_wallets")}
                self.assertTrue(columns["report_text"]["nullable"])
                self.assertEqual(connection.execute(text("SELECT address, report_text FROM published_wallets")).one(), ("existing", None))
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()

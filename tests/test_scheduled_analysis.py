from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from apps.api.robincop_api import tasks
from apps.api.robincop_api.services.discovery import select_eligible_analysis_addresses


class _FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0

    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def commit(self) -> None:
        self.commit_count += 1


class _FakeBatch:
    id = "discovery-batch-id"
    queued_count = 0


class ScheduledAnalysisTests(unittest.TestCase):
    def test_redelivered_completed_run_does_not_repeat_external_analysis(self) -> None:
        run_id = "00000000-0000-0000-0000-000000000001"
        session = MagicMock()
        session.__enter__.return_value = session
        session.__exit__.return_value = None
        session.get.return_value = SimpleNamespace(id=run_id, status="completed")

        with (
            patch.object(tasks, "SessionLocal", return_value=session),
            patch.object(tasks, "enabled") as enabled,
            patch.object(tasks, "acquire_analysis_slot") as acquire,
            patch.object(tasks, "analyze_and_store") as analyze,
        ):
            result = tasks.execute_analysis_job("0x" + "0" * 40, run_id=run_id)

        self.assertEqual(result, run_id)
        enabled.assert_not_called()
        acquire.assert_not_called()
        analyze.assert_not_called()

    def test_analysis_selection_uses_full_ranked_pool_not_display_limit(self) -> None:
        now = datetime.now(timezone.utc)
        ranked = [
            {"wallet_address": f"0x{index:040x}", "realized_profit": 1000 - index}
            for index in range(30)
        ]
        candidates = {
            row["wallet_address"]: SimpleNamespace(
                last_analyzed_at=now,
                next_eligible_at=now + timedelta(days=1),
                status="qualified",
            )
            for row in ranked[:10]
        }
        candidates.update(
            {
                row["wallet_address"]: SimpleNamespace(
                    last_analyzed_at=None,
                    next_eligible_at=None,
                    status="pending",
                )
                for row in ranked[10:]
            }
        )

        queued, eligible_count = select_eligible_analysis_addresses(
            ranked,
            candidates,
            set(),
            now=now,
            analysis_limit=20,
        )

        self.assertEqual(queued, [row["wallet_address"] for row in ranked[10:]])
        self.assertEqual(eligible_count, 20)

    def test_analysis_selection_skips_active_and_respects_cap(self) -> None:
        now = datetime.now(timezone.utc)
        ranked = [{"wallet_address": f"0x{index:040x}"} for index in range(25)]
        candidates = {
            row["wallet_address"]: SimpleNamespace(
                last_analyzed_at=None,
                next_eligible_at=None,
                status="pending",
            )
            for row in ranked
        }
        active = {ranked[0]["wallet_address"], ranked[1]["wallet_address"]}

        queued, eligible_count = select_eligible_analysis_addresses(
            ranked,
            candidates,
            active,
            now=now,
            analysis_limit=20,
        )

        self.assertEqual(queued, [row["wallet_address"] for row in ranked[2:22]])
        self.assertEqual(eligible_count, 23)

    def test_scheduled_collection_starts_single_continuous_worker_when_enabled(self) -> None:
        session = _FakeSession()
        batch = _FakeBatch()
        addresses = [f"0x{index:040x}" for index in range(20)]
        options = {
            "period": "7d",
            "requested_count": 200,
            "sort_by": "realized_profit",
            "direction": "desc",
            "filters": {},
            "analysis_limit": 20,
            "auto_analyze": True,
        }

        with (
            patch.object(tasks, "SessionLocal", return_value=session),
            patch.object(tasks, "enabled", return_value=True),
            patch.object(tasks, "discovery_options", return_value=options),
            patch.object(
                tasks,
                "collect_realtime_candidates",
                return_value=(batch, addresses),
            ) as collect,
            patch.object(
                tasks,
                "enqueue_next_eligible_analysis",
                return_value=1,
            ) as enqueue_next,
        ):
            result = tasks.discover_task.run("scheduled")

        self.assertEqual(result, "discovery-batch-id")
        enqueue_next.assert_called_once_with(session, "scheduled_collection")
        self.assertEqual(batch.queued_count, 1)
        self.assertEqual(session.commit_count, 1)
        collect.assert_called_once_with(
            session,
            trigger="scheduled",
            period="7d",
            requested_count=200,
            sort_by="realized_profit",
            direction="desc",
            filters={},
            analysis_limit=20,
        )

    def test_scheduled_collection_does_not_queue_when_disabled(self) -> None:
        session = _FakeSession()
        batch = _FakeBatch()
        options = {"analysis_limit": 20, "auto_analyze": False}

        with (
            patch.object(tasks, "SessionLocal", return_value=session),
            patch.object(tasks, "enabled", return_value=True),
            patch.object(tasks, "discovery_options", return_value=options),
            patch.object(
                tasks,
                "collect_realtime_candidates",
                return_value=(batch, ["0x" + "1" * 40]),
            ),
            patch.object(tasks, "enqueue_next_eligible_analysis") as enqueue_next,
        ):
            tasks.discover_task.run("scheduled")

        enqueue_next.assert_not_called()
        self.assertEqual(batch.queued_count, 0)

    def test_rate_limit_waits_one_hour_without_refilling_other_addresses(self) -> None:
        address = "0x" + "3" * 40
        failure = RuntimeError("GMGN request failed: HTTP 429: Too Many Requests")
        tasks.analyze_task.push_request(retries=0)
        try:
            with (
                patch.object(tasks, "execute_analysis_job", side_effect=failure),
                patch.object(tasks, "activate_gmgn_cooldown", return_value=3600) as cooldown,
                patch.object(tasks, "mark_analysis_retrying") as mark_retrying,
                patch.object(
                    tasks.analyze_task,
                    "retry",
                    side_effect=RuntimeError("retry scheduled"),
                ) as retry,
                patch.object(tasks, "request_analysis_refill") as refill,
                patch.object(tasks, "fail_analysis_run") as fail,
            ):
                with self.assertRaisesRegex(RuntimeError, "retry scheduled"):
                    tasks.analyze_task.run(address, "continuous_backlog", False, "run-id")
        finally:
            tasks.analyze_task.pop_request()

        cooldown.assert_called_once_with()
        mark_retrying.assert_called_once()
        retry.assert_called_once_with(
            exc=failure,
            countdown=3600,
            max_retries=tasks.GMGN_RATE_LIMIT_MAX_RETRIES,
        )
        refill.assert_not_called()
        fail.assert_not_called()

    def test_success_immediately_requests_next_candidate(self) -> None:
        address = "0x" + "4" * 40
        with (
            patch.object(tasks, "execute_analysis_job", return_value="run-id"),
            patch.object(tasks, "request_analysis_refill") as refill,
        ):
            result = tasks.analyze_task.run(address, "continuous_backlog", False, "run-id")

        self.assertEqual(result, "run-id")
        refill.assert_called_once_with()

    def test_analysis_failure_retries_twice_without_creating_duplicate_run(self) -> None:
        address = "0x" + "1" * 40
        tasks.analyze_task.push_request(retries=0)
        try:
            with (
                patch.object(
                    tasks,
                    "execute_analysis_job",
                    side_effect=RuntimeError("temporary upstream failure"),
                ),
                patch.object(tasks, "mark_analysis_retrying") as mark_retrying,
                patch.object(
                    tasks.analyze_task,
                    "retry",
                    side_effect=RuntimeError("retry scheduled"),
                ) as retry,
                patch.object(tasks, "fail_analysis_run") as fail,
            ):
                with self.assertRaisesRegex(RuntimeError, "retry scheduled"):
                    tasks.analyze_task.run(address, "scheduled_collection", False, "run-id")
        finally:
            tasks.analyze_task.pop_request()

        mark_retrying.assert_called_once()
        retry.assert_called_once()
        fail.assert_not_called()

    def test_analysis_final_failure_is_visible_to_celery(self) -> None:
        address = "0x" + "2" * 40
        failure = RuntimeError("permanent upstream failure")
        tasks.analyze_task.push_request(retries=tasks.ANALYSIS_MAX_RETRIES)
        try:
            with (
                patch.object(tasks, "execute_analysis_job", side_effect=failure),
                patch.object(tasks, "mark_analysis_retrying") as mark_retrying,
                patch.object(tasks, "fail_analysis_run") as fail,
            ):
                with self.assertRaisesRegex(RuntimeError, "permanent upstream failure"):
                    tasks.analyze_task.run(address, "scheduled_collection", False, "run-id")
        finally:
            tasks.analyze_task.pop_request()

        mark_retrying.assert_not_called()
        fail.assert_called_once_with(address, "run-id", failure)


if __name__ == "__main__":
    unittest.main()

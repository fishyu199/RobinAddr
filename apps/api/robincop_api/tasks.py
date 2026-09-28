from __future__ import annotations

import uuid
import time
from datetime import datetime, timedelta, timezone

from celery import chain
from redis import Redis
from sqlalchemy import and_, case, delete, func, or_, select, update

from .celery_app import celery_app
from .config import settings
from .database import SessionLocal
from .models import (
    AnalysisBatch,
    AnalysisRun,
    CandidateWallet,
    DiscoveryBatch,
    PublishedWallet,
    SystemSetting,
)
from .services.analysis import analyze_and_store, create_queued_run
from .services.discovery import collect_realtime_candidates
from .services.policy import analysis_policy, discovery_interval_minutes


ANALYSIS_SLOT_KEY = "robincop:analysis:slots"
SCHEDULED_DISCOVERY_LOCK_KEY = "robincop:discovery:scheduled-lock"
GMGN_COOLDOWN_KEY = "robincop:gmgn:cooldown"
ANALYSIS_SLOT_TTL_SECONDS = 45 * 60
ANALYSIS_SLOT_WAIT_SECONDS = 10 * 60
ANALYSIS_MAX_RETRIES = 2
GMGN_COOLDOWN_SECONDS = 60 * 60
GMGN_RATE_LIMIT_MAX_RETRIES = 1000
ANALYSIS_FAILURE_BACKOFF_SECONDS = 60 * 60
CONTINUOUS_QUEUE_TARGET = 1
DISCOVERY_MAX_RETRIES = 2
SCHEDULED_FAILURE_COOLDOWN_MINUTES = 30
STALE_QUEUED_MINUTES = 30
STALE_RUNNING_MINUTES = 35
RECOVERY_LIMIT = 20
ACQUIRE_SLOT_SCRIPT = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
if redis.call('ZCARD', KEYS[1]) < tonumber(ARGV[4]) then
  redis.call('ZADD', KEYS[1], 'NX', ARGV[2], ARGV[3])
  return 1
end
return 0
"""


class GMGNCooldownError(RuntimeError):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = max(1, retry_after)
        super().__init__(f"GMGN 限流冷却中，{self.retry_after} 秒后重试")


def gmgn_cooldown_remaining() -> int:
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    ttl = int(client.ttl(GMGN_COOLDOWN_KEY))
    return max(0, ttl)


def activate_gmgn_cooldown() -> int:
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    client.set(GMGN_COOLDOWN_KEY, "rate_limited", ex=GMGN_COOLDOWN_SECONDS)
    return GMGN_COOLDOWN_SECONDS


def is_gmgn_rate_limit(error: Exception) -> bool:
    message = str(error).lower()
    return any(
        marker in message
        for marker in ("http 429", "rate limit", "rate_limit", "too many requests", "限流")
    )


def enabled(db, key: str, default: bool = True) -> bool:
    setting = db.get(SystemSetting, key)
    return bool(setting.value.get("enabled", default)) if setting else default


def discovery_options(db) -> dict:
    configured = db.get(SystemSetting, "discovery_settings")
    value = configured.value if configured else {}
    return {
        "period": value.get("period", settings.discovery_period),
        "requested_count": int(value.get("limit", settings.discovery_limit)),
        "sort_by": value.get("sort_by", settings.discovery_sort),
        "direction": value.get("direction", "desc"),
        "filters": value.get(
            "filters", {"min_realized_profit": 0, "min_total_cost": 1000}
        ),
        # Continuous mode keeps only one task in flight; completion refills it.
        "analysis_limit": CONTINUOUS_QUEUE_TARGET,
        "auto_analyze": bool(value.get("auto_analyze", True)),
    }


def acquire_analysis_slot(db, run_id: str | None) -> tuple[Redis, str]:
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    token = f"{run_id or 'run'}:{uuid.uuid4()}"
    deadline = time.monotonic() + ANALYSIS_SLOT_WAIT_SECONDS
    while True:
        db.expire_all()
        limit = analysis_policy(db)["concurrency"]
        now = int(time.time())
        try:
            acquired = client.eval(
                ACQUIRE_SLOT_SCRIPT,
                1,
                ANALYSIS_SLOT_KEY,
                now,
                now + ANALYSIS_SLOT_TTL_SECONDS,
                token,
                limit,
            )
        except Exception as exc:
            raise RuntimeError(f"无法取得地址计算并发槽位：{exc}") from exc
        if acquired:
            return client, token
        if time.monotonic() >= deadline:
            raise RuntimeError("等待地址计算槽位超时")
        time.sleep(5)


def execute_analysis_job(
    address: str,
    trigger: str = "discovery",
    force_refresh: bool = False,
    run_id: str | None = None,
) -> str:
    with SessionLocal() as db:
        if run_id:
            existing_run = db.get(AnalysisRun, uuid.UUID(run_id))
            if existing_run is not None and existing_run.status == "completed":
                return str(existing_run.id)
        if not enabled(db, "analysis_enabled"):
            if run_id:
                run = db.get(AnalysisRun, uuid.UUID(run_id))
                if run is not None:
                    run.status = "paused"
                    run.error = "地址计算已暂停，任务未执行"
                    run.completed_at = datetime.now(timezone.utc)
                    candidate = db.scalar(
                        select(CandidateWallet).where(CandidateWallet.address == address.lower())
                    )
                    if candidate is not None:
                        candidate.status = "pending"
                    db.commit()
            return "analysis paused"
        cooldown_remaining = gmgn_cooldown_remaining()
        if cooldown_remaining:
            raise GMGNCooldownError(cooldown_remaining)
        slot_client, slot_token = acquire_analysis_slot(db, run_id)
        try:
            run = analyze_and_store(
                db,
                address,
                trigger=trigger,
                force_refresh=force_refresh,
                run_id=run_id,
            )
            return str(run.id)
        finally:
            try:
                slot_client.zrem(ANALYSIS_SLOT_KEY, slot_token)
            except Exception:
                pass


def fail_analysis_run(address: str, run_id: str | None, error: Exception) -> None:
    if not run_id:
        return
    with SessionLocal() as db:
        run = db.get(AnalysisRun, uuid.UUID(run_id))
        if run is not None:
            run.status = "failed"
            run.error = str(error)
            run.completed_at = datetime.now(timezone.utc)
        candidate = db.scalar(
            select(CandidateWallet).where(CandidateWallet.address == address.lower())
        )
        if candidate is not None:
            candidate.status = "failed"
            candidate.last_error = str(error)
            candidate.next_eligible_at = datetime.now(timezone.utc) + timedelta(
                seconds=ANALYSIS_FAILURE_BACKOFF_SECONDS
            )
        db.commit()


def mark_analysis_retrying(address: str, run_id: str | None, error: Exception) -> None:
    """Expose a retry as queued so discovery cannot create a duplicate run."""
    if not run_id:
        return
    with SessionLocal() as db:
        run = db.get(AnalysisRun, uuid.UUID(run_id))
        if run is not None:
            run.status = "queued"
            run.error = f"上次尝试失败，等待自动重试：{error}"
            run.started_at = None
            run.completed_at = None
        candidate = db.scalar(
            select(CandidateWallet).where(CandidateWallet.address == address.lower())
        )
        if candidate is not None:
            candidate.status = "queued"
            candidate.last_error = run.error if run is not None else str(error)
            candidate.next_eligible_at = None
        db.commit()


def start_analysis_batch_member(batch_id: str | None, address: str) -> None:
    if not batch_id:
        return
    with SessionLocal() as db:
        batch = db.get(AnalysisBatch, uuid.UUID(batch_id))
        if batch is None:
            return
        now = datetime.now(timezone.utc)
        batch.status = "running"
        batch.current_address = address.lower()
        batch.started_at = batch.started_at or now
        db.commit()


def finish_analysis_batch_member(batch_id: str | None, run_id: str | None) -> None:
    if not batch_id:
        return
    with SessionLocal() as db:
        batch = db.get(AnalysisBatch, uuid.UUID(batch_id))
        if batch is None:
            return
        # Derive counters from member runs so redelivery/recovery is idempotent.
        batch.completed_count = db.scalar(
            select(func.count()).select_from(AnalysisRun).where(
                AnalysisRun.batch_id == batch.id,
                AnalysisRun.status == "completed",
            )
        ) or 0
        batch.failed_count = db.scalar(
            select(func.count()).select_from(AnalysisRun).where(
                AnalysisRun.batch_id == batch.id,
                AnalysisRun.status.in_(("failed", "paused")),
            )
        ) or 0
        batch.current_address = None
        processed = batch.completed_count + batch.failed_count
        if processed >= batch.total_count:
            batch.status = "completed" if batch.failed_count == 0 else "completed_with_errors"
            batch.completed_at = datetime.now(timezone.utc)
        db.commit()


@celery_app.task(
    bind=True,
    name="robincop.analyze",
    max_retries=ANALYSIS_MAX_RETRIES,
    acks_late=True,
    reject_on_worker_lost=True,
)
def analyze_task(
    self,
    address: str,
    trigger: str = "discovery",
    force_refresh: bool = False,
    run_id: str | None = None,
) -> str:
    try:
        result = execute_analysis_job(address, trigger, force_refresh, run_id)
    except Exception as exc:
        if isinstance(exc, GMGNCooldownError) or is_gmgn_rate_limit(exc):
            retry_after = (
                exc.retry_after
                if isinstance(exc, GMGNCooldownError)
                else activate_gmgn_cooldown()
            )
            mark_analysis_retrying(address, run_id, exc)
            raise self.retry(
                exc=exc,
                countdown=retry_after,
                max_retries=GMGN_RATE_LIMIT_MAX_RETRIES,
            )
        if self.request.retries < ANALYSIS_MAX_RETRIES:
            mark_analysis_retrying(address, run_id, exc)
            countdown = 15 * (2**self.request.retries)
            raise self.retry(exc=exc, countdown=countdown)
        fail_analysis_run(address, run_id, exc)
        request_analysis_refill()
        raise
    request_analysis_refill()
    return result


@celery_app.task(
    bind=True,
    name="robincop.analyze_serial",
    max_retries=ANALYSIS_MAX_RETRIES,
    acks_late=True,
    reject_on_worker_lost=True,
)
def analyze_serial_task(
    self,
    address: str,
    trigger: str = "manual_candidate_all",
    force_refresh: bool = False,
    run_id: str | None = None,
    batch_id: str | None = None,
) -> str:
    """Run one member of a chain without aborting later members on failure."""
    finish_member = True
    try:
        start_analysis_batch_member(batch_id, address)
        return execute_analysis_job(address, trigger, force_refresh, run_id)
    except Exception as exc:
        if isinstance(exc, GMGNCooldownError) or is_gmgn_rate_limit(exc):
            finish_member = False
            retry_after = (
                exc.retry_after
                if isinstance(exc, GMGNCooldownError)
                else activate_gmgn_cooldown()
            )
            mark_analysis_retrying(address, run_id, exc)
            raise self.retry(
                exc=exc,
                countdown=retry_after,
                max_retries=GMGN_RATE_LIMIT_MAX_RETRIES,
            )
        if self.request.retries < ANALYSIS_MAX_RETRIES:
            finish_member = False
            mark_analysis_retrying(address, run_id, exc)
            countdown = 15 * (2**self.request.retries)
            raise self.retry(exc=exc, countdown=countdown)
        fail_analysis_run(address, run_id, exc)
        return f"failed: {address}"
    finally:
        if finish_member:
            try:
                finish_analysis_batch_member(batch_id, run_id)
            except Exception:
                pass


def enqueue_analysis(
    db,
    address: str,
    trigger: str,
    force_refresh: bool = False,
) -> tuple[AnalysisRun, str, bool]:
    normalized = address.lower()
    existing = db.scalar(
        select(AnalysisRun)
        .where(
            AnalysisRun.address == normalized,
            AnalysisRun.status.in_(("queued", "running")),
        )
        .order_by(AnalysisRun.created_at.desc())
        .limit(1)
    )
    if existing is not None:
        candidate = db.scalar(
            select(CandidateWallet).where(CandidateWallet.address == normalized)
        )
        if candidate is not None:
            candidate.status = existing.status
            db.commit()
        return existing, "", False

    run = create_queued_run(db, normalized, trigger=trigger)
    candidate = db.scalar(select(CandidateWallet).where(CandidateWallet.address == normalized))
    if candidate is not None:
        candidate.status = "queued"
        candidate.last_error = None
        db.commit()
    try:
        task = analyze_task.delay(normalized, trigger, force_refresh, str(run.id))
    except Exception as exc:
        run.status = "failed"
        run.error = f"任务入队失败：{exc}"
        run.completed_at = datetime.now(timezone.utc)
        if candidate is not None:
            candidate.status = "failed"
            candidate.last_error = run.error
        db.commit()
        raise
    return run, task.id, True


def enqueue_next_eligible_analysis(db, trigger: str = "continuous_backlog") -> int:
    """Keep exactly one analysis active until every eligible candidate is done."""
    if not enabled(db, "analysis_enabled"):
        return 0
    configured = discovery_options(db)
    if not configured["auto_analyze"]:
        return 0
    try:
        if gmgn_cooldown_remaining():
            return 0
    except Exception:
        # If Redis cannot be checked, the broker cannot safely accept work.
        return 0
    active_count = db.scalar(
        select(func.count()).select_from(AnalysisRun).where(
            AnalysisRun.status.in_(("queued", "running"))
        )
    ) or 0
    if active_count >= CONTINUOUS_QUEUE_TARGET:
        return 0

    now = datetime.now(timezone.utc)
    candidate = db.scalar(
        select(CandidateWallet)
        .where(
            or_(
                CandidateWallet.next_eligible_at.is_(None),
                CandidateWallet.next_eligible_at <= now,
            )
        )
        .order_by(
            case((CandidateWallet.last_score.is_(None), 0), else_=1),
            CandidateWallet.source_rank.asc().nulls_last(),
            CandidateWallet.last_seen_at.desc(),
        )
        .limit(1)
    )
    if candidate is None:
        return 0
    _, _, created = enqueue_analysis(db, candidate.address, trigger, False)
    return int(created)


def request_analysis_refill() -> None:
    try:
        refill_analysis_queue_task.delay()
    except Exception:
        # The minute-level scheduler is the fallback if this immediate signal
        # is lost during a broker restart.
        pass


@celery_app.task(name="robincop.refill_analysis_queue")
def refill_analysis_queue_task() -> int:
    with SessionLocal() as db:
        return enqueue_next_eligible_analysis(db)


def enqueue_serial_analyses(
    db,
    addresses: list[str],
    trigger: str = "manual_candidate_all",
) -> tuple[int, int, int, str, str]:
    """Prepare a candidate batch whose next task starts only after the prior task ends."""
    normalized_addresses = list(dict.fromkeys(address.lower() for address in addresses))
    active = set(
        db.scalars(
            select(AnalysisRun.address).where(
                AnalysisRun.address.in_(normalized_addresses),
                AnalysisRun.status.in_(("queued", "running")),
            )
        ).all()
    ) if normalized_addresses else set()
    batch = AnalysisBatch(
        kind="candidate_serial",
        status="queued",
        requested_count=len(normalized_addresses),
        total_count=0,
        completed_count=0,
        failed_count=0,
        skipped_count=0,
    )
    db.add(batch)
    db.flush()
    signatures = []
    prepared_runs: list[AnalysisRun] = []
    for address in normalized_addresses:
        if address in active:
            continue
        run = create_queued_run(db, address, trigger=trigger, batch_id=batch.id)
        candidate = db.scalar(select(CandidateWallet).where(CandidateWallet.address == address))
        if candidate is not None:
            candidate.status = "queued"
            candidate.last_error = None
            db.commit()
        prepared_runs.append(run)
        signatures.append(
            analyze_serial_task.si(
                address, trigger, False, str(run.id), str(batch.id)
            ).set(queue="serial_analysis")
        )

    workflow_id = ""
    batch.total_count = len(signatures)
    batch.skipped_count = len(normalized_addresses) - len(signatures)
    if not signatures:
        batch.status = "completed"
        batch.completed_at = datetime.now(timezone.utc)
    db.commit()
    if signatures:
        try:
            workflow_id = chain(*signatures).apply_async().id
        except Exception as exc:
            for run in prepared_runs:
                run.status = "failed"
                run.error = f"串行批次入队失败：{exc}"
                run.completed_at = datetime.now(timezone.utc)
            batch.status = "failed"
            batch.failed_count = batch.total_count
            batch.completed_at = datetime.now(timezone.utc)
            db.commit()
            raise
    queued = len(signatures)
    return (
        len(normalized_addresses),
        queued,
        len(normalized_addresses) - queued,
        workflow_id,
        str(batch.id),
    )


def _scheduled_discovery_client() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


@celery_app.task(
    bind=True,
    name="robincop.discover",
    max_retries=DISCOVERY_MAX_RETRIES,
    acks_late=True,
    reject_on_worker_lost=True,
)
def discover_task(self, trigger: str = "manual") -> str:
    try:
        with SessionLocal() as db:
            if trigger == "scheduled" and not enabled(db, "discovery_enabled"):
                result = "discovery paused"
            else:
                options = discovery_options(db)
                auto_analyze = options.pop("auto_analyze")
                batch, _addresses = collect_realtime_candidates(db, trigger=trigger, **options)
                queued_count = 0
                # Keep one task in flight; completion immediately asks the
                # refill task for the next candidate until the pool is empty.
                if auto_analyze:
                    queued_count = enqueue_next_eligible_analysis(
                        db, f"{trigger}_collection"
                    )
                batch.queued_count = queued_count
                db.commit()
                result = str(batch.id)
    except Exception as exc:
        if is_gmgn_rate_limit(exc):
            retry_after = activate_gmgn_cooldown()
            if trigger == "scheduled":
                _scheduled_discovery_client().set(
                    SCHEDULED_DISCOVERY_LOCK_KEY,
                    "gmgn_cooldown",
                    ex=retry_after + 10 * 60,
                )
            raise self.retry(
                exc=exc,
                countdown=retry_after,
                max_retries=GMGN_RATE_LIMIT_MAX_RETRIES,
            )
        if self.request.retries < DISCOVERY_MAX_RETRIES:
            countdown = 30 * (2**self.request.retries)
            raise self.retry(exc=exc, countdown=countdown)
        if trigger == "scheduled":
            try:
                _scheduled_discovery_client().delete(SCHEDULED_DISCOVERY_LOCK_KEY)
            except Exception:
                pass
        raise
    if trigger == "scheduled":
        try:
            _scheduled_discovery_client().delete(SCHEDULED_DISCOVERY_LOCK_KEY)
        except Exception:
            pass
    return result


@celery_app.task(name="robincop.discover_due")
def discover_due_task() -> str:
    try:
        if gmgn_cooldown_remaining():
            return "gmgn cooldown"
    except Exception:
        return "broker unavailable"
    with SessionLocal() as db:
        if not enabled(db, "discovery_enabled"):
            return "discovery paused"
        interval_minutes = discovery_interval_minutes(db)
        latest_scheduled = db.scalar(
            select(DiscoveryBatch)
            .where(DiscoveryBatch.config["trigger"].astext == "scheduled")
            .order_by(DiscoveryBatch.started_at.desc())
            .limit(1)
        )
        if (
            latest_scheduled is not None
            and latest_scheduled.status == "failed"
            and latest_scheduled.completed_at is not None
            and latest_scheduled.completed_at
            > datetime.now(timezone.utc)
            - timedelta(minutes=SCHEDULED_FAILURE_COOLDOWN_MINUTES)
        ):
            return "failure cooldown"
        last_started = db.scalar(
            select(DiscoveryBatch.started_at)
            .where(
                DiscoveryBatch.status == "completed",
                DiscoveryBatch.config["trigger"].astext == "scheduled",
            )
            .order_by(DiscoveryBatch.started_at.desc())
            .limit(1)
        )
        if last_started and last_started > datetime.now(timezone.utc) - timedelta(
            minutes=interval_minutes
        ):
            return "not due"
    client = _scheduled_discovery_client()
    lock_seconds = max(30 * 60, interval_minutes * 60)
    if not client.set(SCHEDULED_DISCOVERY_LOCK_KEY, "queued", nx=True, ex=lock_seconds):
        return "already queued"
    try:
        task = discover_task.delay("scheduled")
    except Exception:
        client.delete(SCHEDULED_DISCOVERY_LOCK_KEY)
        raise
    return str(task.id)


def _record_scheduler_heartbeat(db, recovered: int, note: str) -> None:
    setting = db.get(SystemSetting, "scheduler_heartbeat") or SystemSetting(
        key="scheduler_heartbeat"
    )
    previous = setting.value or {}
    setting.value = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "last_recovered": recovered,
        "recovered_total": int(previous.get("recovered_total", 0)) + recovered,
        "note": note,
    }
    setting.updated_at = datetime.now(timezone.utc)
    db.add(setting)


@celery_app.task(name="robincop.recover_stale_analysis")
def recover_stale_analysis_task() -> int:
    """Recover only orphaned work; never create additional analysis volume."""
    now = datetime.now(timezone.utc)
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        client.zremrangebyscore(ANALYSIS_SLOT_KEY, "-inf", int(time.time()))
        broker_depth = sum(
            int(client.llen(queue_name))
            for queue_name in ("analysis", "serial_analysis", "celery")
        )
        active_slots = int(client.zcard(ANALYSIS_SLOT_KEY))
        cooldown_remaining = max(0, int(client.ttl(GMGN_COOLDOWN_KEY)))
    except Exception as exc:
        with SessionLocal() as db:
            _record_scheduler_heartbeat(db, 0, f"队列检查失败：{exc}")
            db.commit()
        return 0

    # A non-empty broker or a live slot means the pipeline is progressing.
    # Waiting avoids duplicate external calls and keeps this watchdog local.
    if broker_depth or active_slots or cooldown_remaining:
        with SessionLocal() as db:
            _record_scheduler_heartbeat(
                db,
                0,
                (
                    f"GMGN 限流冷却中：剩余 {cooldown_remaining} 秒"
                    if cooldown_remaining
                    else f"正常：队列 {broker_depth}，计算槽 {active_slots}"
                ),
            )
            db.commit()
        return 0

    queued_cutoff = now - timedelta(minutes=STALE_QUEUED_MINUTES)
    running_cutoff = now - timedelta(minutes=STALE_RUNNING_MINUTES)
    with SessionLocal() as db:
        stale_runs = db.scalars(
            select(AnalysisRun)
            .where(
                or_(
                    and_(
                        AnalysisRun.status == "queued",
                        AnalysisRun.created_at <= queued_cutoff,
                    ),
                    and_(
                        AnalysisRun.status == "running",
                        AnalysisRun.started_at.is_not(None),
                        AnalysisRun.started_at <= running_cutoff,
                    ),
                )
            )
            .order_by(AnalysisRun.created_at.asc())
            .limit(RECOVERY_LIMIT)
        ).all()
        recovered = 0
        for run in stale_runs:
            run.status = "queued"
            run.error = "检测到任务进程中断，已自动恢复"
            run.started_at = None
            run.completed_at = None
            candidate = db.scalar(
                select(CandidateWallet).where(CandidateWallet.address == run.address)
            )
            if candidate is not None:
                candidate.status = "queued"
                candidate.last_error = run.error
            db.commit()
            try:
                if run.batch_id:
                    analyze_serial_task.delay(
                        run.address,
                        run.trigger,
                        False,
                        str(run.id),
                        str(run.batch_id),
                    )
                else:
                    analyze_task.delay(run.address, run.trigger, False, str(run.id))
                recovered += 1
            except Exception as exc:
                run.status = "failed"
                run.error = f"自动恢复入队失败：{exc}"
                run.completed_at = datetime.now(timezone.utc)
                if candidate is not None:
                    candidate.status = "failed"
                    candidate.last_error = run.error
                db.commit()
        _record_scheduler_heartbeat(
            db,
            recovered,
            f"已恢复 {recovered} 个中断任务" if recovered else "正常：没有中断任务",
        )
        db.commit()
        return recovered


@celery_app.task(name="robincop.recompute_due")
def recompute_due_task() -> int:
    with SessionLocal() as db:
        if not enabled(db, "analysis_enabled"):
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(
            days=analysis_policy(db)["reanalysis_interval_days"]
        )
        addresses = db.scalars(
            select(PublishedWallet.address).where(PublishedWallet.analyzed_at <= cutoff)
        ).all()
        queued = 0
        for address in addresses:
            _, _, created = enqueue_analysis(db, address, "scheduled_recompute", False)
            queued += int(created)
        return queued


@celery_app.task(name="robincop.prune_history")
def prune_history_task() -> dict[str, int]:
    """Bound operational history and remove legacy multi-megabyte run payloads."""
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        cleared_results = db.execute(
            update(AnalysisRun)
            .where(AnalysisRun.result.is_not(None))
            .values(result=None)
        ).rowcount or 0
        deleted_runs = db.execute(
            delete(AnalysisRun).where(
                AnalysisRun.created_at < now - timedelta(days=max(1, settings.analysis_history_days))
            )
        ).rowcount or 0
        deleted_discovery_batches = db.execute(
            delete(DiscoveryBatch).where(
                DiscoveryBatch.started_at < now - timedelta(days=max(1, settings.discovery_history_days))
            )
        ).rowcount or 0
        deleted_analysis_batches = db.execute(
            delete(AnalysisBatch).where(
                AnalysisBatch.created_at < now - timedelta(days=max(1, settings.analysis_history_days))
            )
        ).rowcount or 0
        db.commit()
    return {
        "cleared_results": cleared_results,
        "deleted_runs": deleted_runs,
        "deleted_discovery_batches": deleted_discovery_batches,
        "deleted_analysis_batches": deleted_analysis_batches,
    }

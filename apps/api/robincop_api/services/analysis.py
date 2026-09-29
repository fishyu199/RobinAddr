from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from run_robinhood import analyze_wallet

from ..config import settings
from ..models import AnalysisRun, CandidateWallet, PublishedWallet
from .discovery import normalize_labels
from .policy import analysis_policy
from ..wallet_summary import build_wallet_summary


ALGORITHM_VERSION = "robinhood-copy-v3-score-adjustment"
ANALYSIS_CONFIG = {
    "max_trades": settings.max_trades,
    "buy_penalty": 0.025,
    "sell_penalty_after_60s": 0.025,
    "sell_penalty_10s": 0.20,
    "sell_penalty_30s": 0.15,
    "sell_penalty_60s": 0.10,
    "median_hold_score_penalty": 0,
    "recent_copy_loss_max_penalty": 10,
}


def create_queued_run(
    db: Session,
    address: str,
    *,
    trigger: str,
    batch_id: uuid.UUID | None = None,
) -> AnalysisRun:
    run = AnalysisRun(
        address=address.lower(),
        batch_id=batch_id,
        trigger=trigger,
        status="queued",
        algorithm_version=ALGORITHM_VERSION,
        config=dict(ANALYSIS_CONFIG),
    )
    db.add(run)
    db.commit()
    return run


def analyze_and_store(
    db: Session,
    address: str,
    *,
    trigger: str,
    force_refresh: bool = False,
    run_id: str | uuid.UUID | None = None,
) -> AnalysisRun:
    address = address.lower()
    run = db.get(AnalysisRun, uuid.UUID(str(run_id))) if run_id else None
    if run is None:
        run = AnalysisRun(
            address=address,
            trigger=trigger,
            algorithm_version=ALGORITHM_VERSION,
            config=dict(ANALYSIS_CONFIG),
        )
        db.add(run)
    run.status = "running"
    run.started_at = datetime.now(timezone.utc)
    existing_candidate = db.scalar(select(CandidateWallet).where(CandidateWallet.address == address))
    if existing_candidate is not None:
        existing_candidate.status = "analyzing"
        existing_candidate.last_error = None
    db.commit()
    try:
        output = analyze_wallet(
            address,
            lang="zh-CN",
            client="web",
            include_all_tokens=True,
            max_trades=settings.max_trades,
            # Server-side analysis is persisted in PostgreSQL. Keeping another
            # unbounded 5,000-trade cache per wallet can exhaust the host disk.
            cache_dir=None,
        )
        metrics = output["metrics"]
        report_text = output["report_text"]
        if not isinstance(report_text, str) or not report_text.strip():
            raise ValueError("Analysis returned an empty report")
        score = int(metrics.get("score") or 0)
        policy = analysis_policy(db)
        score_threshold = policy["score_threshold"]
        profile = metrics.get("gmgn_stats_30d", {}).get("common", {})
        labels = normalize_labels(profile.get("tags") or [])
        candidate = db.scalar(select(CandidateWallet).where(CandidateWallet.address == address))
        if candidate is None:
            candidate = CandidateWallet(address=address, source="manual", status="analyzed")
            db.add(candidate)
        candidate.last_score = score
        candidate.last_analyzed_at = datetime.now(timezone.utc)
        candidate.next_eligible_at = candidate.last_analyzed_at + timedelta(
            days=policy["reanalysis_interval_days"]
        )
        candidate.status = "qualified" if score > score_threshold else "rejected"
        candidate.name = profile.get("name") or profile.get("nick_name") or None
        candidate.labels = labels
        candidate.last_error = None

        qualifies = score > score_threshold
        published = db.get(PublishedWallet, address)
        # Keep every explicitly requested analysis available to its detail
        # page. The `listed` flag still controls whether the wallet appears on
        # the public leaderboard.
        if published is None:
            published = PublishedWallet(address=address, score=score, metrics=metrics)
            db.add(published)
        published.name = profile.get("name") or profile.get("nick_name") or None
        published.twitter_name = profile.get("twitter_name") or None
        published.ens = profile.get("ens") or None
        published.labels = labels
        published.tag_ranks = profile.get("tag_rank") or {}
        published.score = score
        published.actual_pnl = float(metrics.get("actual_pnl") or 0)
        published.copy_pnl = float(metrics.get("copy_backtest_pnl") or 0)
        published.metrics = metrics
        published.report_text = report_text
        published.summary = build_wallet_summary(metrics)
        published.listed = qualifies and not published.manual_unlisted
        published.algorithm_version = ALGORITHM_VERSION
        published.analyzed_at = datetime.now(timezone.utc)
        published.updated_at = published.analyzed_at

        run.status = "completed"
        run.score = score
        run.input_trade_count = int(metrics.get("processed_trade_count") or 0)
        run.published = qualifies
        # The full payload already lives on the published wallet when needed.
        # Keep only a compact audit summary on historical runs.
        run.result = {
            "actual_pnl": metrics.get("actual_pnl"),
            "copy_backtest_pnl": metrics.get("copy_backtest_pnl"),
            "copy_loss_rate": metrics.get("copy_loss_rate"),
            "tokens_traded": metrics.get("tokens_traded"),
            "analysis_elapsed_seconds": metrics.get("analysis_elapsed_seconds"),
        }
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:
        # Preserve the previous successful metrics/report pair if this attempt
        # fails after modifying ORM objects but before the final commit.
        db.rollback()
        run.status = "failed"
        run.error = str(exc)
        run.completed_at = datetime.now(timezone.utc)
        candidate = db.scalar(select(CandidateWallet).where(CandidateWallet.address == address))
        if candidate is not None:
            candidate.status = "failed"
            candidate.last_error = str(exc)
        db.commit()
        # Let Celery see the failure so its bounded retry policy can run.
        # Persisting the failure first keeps the admin view truthful between
        # attempts and after the final attempt.
        raise
    return run

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Float, Integer, String, and_, cast, func, or_, select, update
from sqlalchemy.orm import Session

from .config import normalize_analysis_concurrency, settings
from .database import Base, engine, get_db
from .models import (
    AnalysisBatch,
    AnalysisRun,
    CandidateWallet,
    DiscoveryBatch,
    PublishedWallet,
    SystemSetting,
)
from .schemas import AnalyzeRequest, ControlUpdate, DiscoverySettings
from .security import require_admin
from .services.policy import analysis_policy, discovery_interval_minutes
from .tasks import (
    SCHEDULED_FAILURE_COOLDOWN_MINUTES,
    discover_task,
    enqueue_analysis,
    enqueue_serial_analyses,
    gmgn_cooldown_remaining,
    recompute_due_task,
)
from .wallet_summary import build_wallet_summary


app = FastAPI(title="RobinCop API", version="1.0.0", root_path=settings.api_root_path)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.public_origin.split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH"],
    allow_headers=["Content-Type", "X-Admin-Key"],
)

WALLET_ADDRESS_PATTERN = re.compile(r"^0x[a-fA-F0-9]{40}$")


@app.on_event("startup")
def create_schema_for_development() -> None:
    Base.metadata.create_all(bind=engine)


DETAIL_METRIC_KEYS = {
    "actual_pnl",
    "avg_invest_per_token",
    "avg_profit_loss_ratio",
    "buy_count",
    "copy_backtest_pnl",
    "copy_daily_pnl_14d",
    "copy_loss_rate",
    "copy_roi_on_required_cash",
    "extra_loss_usd",
    "last_active",
    "median_holding_time_seconds",
    "open_token_count",
    "pnl_retention_rate",
    "processed_trade_count",
    "required_starting_cash_usd",
    "sell_count",
    "sell_win_rate",
    "target_daily_pnl_14d",
    "token_win_rate",
    "tokens_traded",
    "trading_days",
    "trading_volume",
    "win_rate",
}


def _finite_number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed and abs(parsed) != float("inf") else None


def _sample_rows(rows: list[Any], limit: int) -> list[Any]:
    if len(rows) <= limit:
        return rows
    if limit <= 1:
        return [rows[-1]]
    indexes = {round(index * (len(rows) - 1) / (limit - 1)) for index in range(limit)}
    return [row for index, row in enumerate(rows) if index in indexes]


def compact_detail_metrics(metrics: dict[str, Any], *, summary_only: bool = False) -> dict[str, Any]:
    """Return only the data rendered by the web detail page.

    Full analysis payloads can exceed several megabytes. Keeping the original
    detail response as the default preserves API compatibility, while the web
    view can request this bounded representation.
    """
    compact = {key: metrics[key] for key in DETAIL_METRIC_KEYS if key in metrics}

    equity_curve = metrics.get("equity_curve")
    compact["equity_curve"] = _sample_rows(equity_curve, 360) if isinstance(equity_curve, list) else []

    if summary_only:
        compact["all_tokens"] = []
        compact["position_rows"] = []
        compact["trade_results"] = []
        return compact

    per_token = metrics.get("per_token")
    per_token_rows = [row for row in (per_token if isinstance(per_token, list) else []) if isinstance(row, dict)]
    per_token_by_address = {
        str(row.get("token_address") or row.get("condition_id") or "").lower(): row
        for row in per_token_rows
        if row.get("token_address") or row.get("condition_id")
    }

    def add_profit_rates(row: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(row)
        token_address = str(row.get("token_address") or row.get("condition_id") or "").lower()
        source = per_token_by_address.get(token_address, row)
        target = source.get("target") if isinstance(source.get("target"), dict) else {}
        copy = source.get("copy") if isinstance(source.get("copy"), dict) else {}
        target_roi = _finite_number(target.get("roi_on_required_cash"))
        copy_roi = _finite_number(copy.get("roi_on_required_cash"))
        enriched["actual_profit_rate"] = target_roi * 100 if target_roi is not None else None
        enriched["copy_profit_rate"] = copy_roi * 100 if copy_roi is not None else None
        return enriched

    all_tokens = metrics.get("all_tokens")
    token_rows = [add_profit_rates(row) for row in (all_tokens if isinstance(all_tokens, list) else []) if isinstance(row, dict)]
    last_activity_by_token = {
        str(row.get("token_address") or row.get("condition_id") or "").lower(): row.get("last_active")
        for row in token_rows
        if row.get("token_address") or row.get("condition_id")
    }
    token_rows.sort(key=lambda row: _finite_number(row.get("last_active")) or 0, reverse=True)
    compact["all_tokens"] = token_rows[:500]

    position_rows: list[dict[str, Any]] = []
    for row in per_token_rows:
        if not isinstance(row, dict) or (_finite_number(row.get("copy_ending_quantity")) or 0) <= 0:
            continue
        position = add_profit_rates(row)
        token_address = str(position.get("token_address") or position.get("condition_id") or "").lower()
        if position.get("last_active") is None and token_address:
            position["last_active"] = last_activity_by_token.get(token_address)
        position_rows.append(position)
    compact["position_rows"] = position_rows[:500]

    trade_results = metrics.get("trade_results")
    trade_rows = [row for row in (trade_results if isinstance(trade_results, list) else []) if isinstance(row, dict)]
    trade_rows.sort(key=lambda row: _finite_number(row.get("timestamp_ms")) or 0)
    compact["trade_results"] = trade_rows[-200:]
    return compact


def wallet_payload(
    wallet: PublishedWallet,
    *,
    detailed: bool = False,
    compact_details: bool = False,
    summary_only: bool = False,
) -> dict[str, Any]:
    metrics = wallet.metrics or {}
    summary = wallet.summary or build_wallet_summary(metrics)
    display_name = wallet.name or wallet.twitter_name or wallet.ens
    payload = {
        "address": wallet.address,
        "name": display_name,
        "display_name": display_name or f"{wallet.address[:6]}...{wallet.address[-5:]}",
        "labels": wallet.labels,
        "tag_ranks": wallet.tag_ranks,
        "score": wallet.score,
        "actual_pnl": wallet.actual_pnl,
        "copy_pnl": wallet.copy_pnl,
        "win_rate": summary.get("win_rate", 0),
        "copy_loss_rate": summary.get("copy_loss_rate"),
        "pnl_ratio": summary.get("avg_profit_loss_ratio", 0),
        "trading_days": summary.get("trading_days", 0),
        "recent_20": summary.get("recent_20_stats", {}),
        "tokens_traded": summary.get("tokens_traded", 0),
        "trading_volume": summary.get("trading_volume", 0),
        "avg_invest": summary.get("avg_invest_per_token", 0),
        "median_holding_time_seconds": summary.get("median_holding_time_seconds"),
        "target_daily_pnl_14d": summary.get("target_daily_pnl_14d", []),
        "copy_daily_pnl_14d": summary.get("copy_daily_pnl_14d", []),
        "last_active": summary.get("last_active", ""),
        "analyzed_at": wallet.analyzed_at,
    }
    if detailed:
        payload["metrics"] = compact_detail_metrics(metrics, summary_only=summary_only) if compact_details else metrics
    return payload


def wallet_summary_columns() -> tuple[Any, ...]:
    """Select only fields needed by the public leaderboard.

    The metrics JSON can be several megabytes per wallet, so loading complete
    PublishedWallet rows for the leaderboard creates avoidable memory spikes.
    """
    return (
        PublishedWallet.address.label("address"),
        PublishedWallet.name.label("name"),
        PublishedWallet.twitter_name.label("twitter_name"),
        PublishedWallet.ens.label("ens"),
        PublishedWallet.labels.label("labels"),
        PublishedWallet.tag_ranks.label("tag_ranks"),
        PublishedWallet.score.label("score"),
        PublishedWallet.actual_pnl.label("actual_pnl"),
        PublishedWallet.copy_pnl.label("copy_pnl"),
        PublishedWallet.analyzed_at.label("analyzed_at"),
        PublishedWallet.summary["win_rate"].label("win_rate"),
        PublishedWallet.summary["copy_loss_rate"].label("copy_loss_rate"),
        PublishedWallet.summary["avg_profit_loss_ratio"].label("pnl_ratio"),
        PublishedWallet.summary["trading_days"].label("trading_days"),
        PublishedWallet.summary["recent_20_stats"].label("recent_20"),
        PublishedWallet.summary["tokens_traded"].label("tokens_traded"),
        PublishedWallet.summary["trading_volume"].label("trading_volume"),
        PublishedWallet.summary["avg_invest_per_token"].label("avg_invest"),
        PublishedWallet.summary["median_holding_time_seconds"].label("median_holding_time_seconds"),
        PublishedWallet.summary["target_daily_pnl_14d"].label("target_daily_pnl_14d"),
        PublishedWallet.summary["copy_daily_pnl_14d"].label("copy_daily_pnl_14d"),
        PublishedWallet.summary["last_active"].label("last_active"),
    )


def wallet_summary_payload(row: Any) -> dict[str, Any]:
    display_name = row["name"] or row["twitter_name"] or row["ens"]
    address = row["address"]
    return {
        "address": address,
        "name": display_name,
        "display_name": display_name or f"{address[:6]}...{address[-5:]}",
        "labels": row["labels"] or [],
        "tag_ranks": row["tag_ranks"] or {},
        "score": row["score"],
        "actual_pnl": row["actual_pnl"],
        "copy_pnl": row["copy_pnl"],
        "win_rate": row["win_rate"] or 0,
        "copy_loss_rate": row["copy_loss_rate"],
        "pnl_ratio": row["pnl_ratio"] or 0,
        "trading_days": row["trading_days"] or 0,
        "recent_20": row["recent_20"] or {},
        "tokens_traded": row["tokens_traded"] or 0,
        "trading_volume": row["trading_volume"] or 0,
        "avg_invest": row["avg_invest"] or 0,
        "median_holding_time_seconds": row["median_holding_time_seconds"],
        "target_daily_pnl_14d": row["target_daily_pnl_14d"] or [],
        "copy_daily_pnl_14d": row["copy_daily_pnl_14d"] or [],
        "last_active": row["last_active"] or "",
        "analyzed_at": row["analyzed_at"],
    }


def control_enabled(db: Session, key: str) -> bool:
    value = db.get(SystemSetting, key)
    return bool(value.value.get("enabled", True)) if value else True


def normalize_wallet_address(address: str) -> str:
    if not WALLET_ADDRESS_PATTERN.fullmatch(address):
        raise HTTPException(status_code=422, detail="Invalid wallet address")
    return address.lower()


def analysis_batch_payload(batch: AnalysisBatch | None) -> dict[str, Any] | None:
    if batch is None:
        return None
    processed = batch.completed_count + batch.failed_count
    return {
        "id": str(batch.id),
        "kind": batch.kind,
        "status": batch.status,
        "requested_count": batch.requested_count,
        "total_count": batch.total_count,
        "completed_count": batch.completed_count,
        "failed_count": batch.failed_count,
        "skipped_count": batch.skipped_count,
        "processed_count": processed,
        "progress_percent": round((processed / batch.total_count) * 100, 1) if batch.total_count else 100,
        "current_address": batch.current_address,
        "created_at": batch.created_at,
        "started_at": batch.started_at,
        "completed_at": batch.completed_at,
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "robincop-api"}


@app.get("/api/v1/wallets")
def list_wallets(
    response: Response,
    search: str = "",
    tag: str = "",
    min_score: int | None = Query(
        default=None, ge=0, le=100, description="Only return wallets with a score strictly greater than this value."
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "public, max-age=30, stale-while-revalidate=120"
    score_threshold = analysis_policy(db)["score_threshold"]
    conditions = [
        PublishedWallet.listed.is_(True),
        PublishedWallet.score > score_threshold,
    ]
    if min_score is not None:
        conditions.append(PublishedWallet.score > min_score)
    if search:
        pattern = f"%{search}%"
        conditions.append(
            PublishedWallet.address.ilike(pattern)
            | PublishedWallet.name.ilike(pattern)
            | PublishedWallet.twitter_name.ilike(pattern)
            | PublishedWallet.ens.ilike(pattern)
        )
    if tag:
        conditions.append(PublishedWallet.labels.contains([tag]))
    query = (
        select(*wallet_summary_columns())
        .where(*conditions)
        .order_by(PublishedWallet.score.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = db.execute(query).mappings().all()
    labels_text = func.lower(cast(PublishedWallet.labels, String))
    count_row = db.execute(
        select(
            func.count().label("all_count"),
            func.count().filter(labels_text.like("%smart money%")).label("smart_money_count"),
            func.count().filter(or_(labels_text.like("%kol%"), labels_text.like("%vc%"))).label("kol_vc_count"),
            func.count().filter(labels_text.like("%fresh%")).label("fresh_count"),
            func.count().filter(labels_text.like("%sniper%")).label("sniper_count"),
        )
        .select_from(PublishedWallet)
        .where(*conditions)
    ).mappings().one()
    category_counts = {
        "all": int(count_row["all_count"] or 0),
        "smart-money": int(count_row["smart_money_count"] or 0),
        "kol-vc": int(count_row["kol_vc_count"] or 0),
        "fresh": int(count_row["fresh_count"] or 0),
        "sniper": int(count_row["sniper_count"] or 0),
    }
    return {
        "items": [wallet_summary_payload(row) for row in rows],
        "total": category_counts["all"],
        "category_counts": category_counts,
    }


@app.get("/api/v1/wallets/{address}")
def get_wallet(
    address: str,
    response: Response,
    compact: bool = Query(default=False),
    summary_only: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "public, max-age=30, stale-while-revalidate=120"
    wallet = db.get(PublishedWallet, normalize_wallet_address(address))
    if wallet is None or wallet.manual_unlisted:
        raise HTTPException(status_code=404, detail="Wallet not found")
    return wallet_payload(
        wallet,
        detailed=True,
        compact_details=compact,
        summary_only=summary_only,
    )


@app.post("/api/v1/wallets/{address}/analysis")
def start_wallet_analysis(
    address: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    normalized = normalize_wallet_address(address)
    wallet_row = db.execute(
        select(PublishedWallet.address, PublishedWallet.manual_unlisted).where(
            PublishedWallet.address == normalized
        )
    ).first()
    if wallet_row is not None and wallet_row.manual_unlisted:
        raise HTTPException(status_code=404, detail="Wallet not found")
    if wallet_row is not None:
        return {
            "address": normalized,
            "status": "completed",
            "run_id": None,
        }
    if not control_enabled(db, "analysis_enabled"):
        raise HTTPException(status_code=409, detail="Wallet analysis is currently paused")
    try:
        run, _, created = enqueue_analysis(db, normalized, "public_lookup", False)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Unable to start wallet analysis") from exc
    return {
        "address": normalized,
        "status": "queued" if created else run.status,
        "run_id": str(run.id),
    }


@app.get("/api/v1/wallets/{address}/analysis")
def get_wallet_analysis(
    address: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    normalized = normalize_wallet_address(address)
    wallet_row = db.execute(
        select(PublishedWallet.address, PublishedWallet.manual_unlisted).where(
            PublishedWallet.address == normalized
        )
    ).first()
    if wallet_row is not None and wallet_row.manual_unlisted:
        raise HTTPException(status_code=404, detail="Wallet analysis not found")
    if wallet_row is not None:
        return {
            "address": normalized,
            "status": "completed",
            "run_id": None,
        }
    run = db.scalar(
        select(AnalysisRun)
        .where(AnalysisRun.address == normalized)
        .order_by(AnalysisRun.created_at.desc())
        .limit(1)
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Wallet analysis not found")
    return {
        "address": normalized,
        "status": run.status,
        "run_id": str(run.id),
        "message": "Wallet analysis failed" if run.status == "failed" else None,
    }


@app.get("/api/v1/wallets/{address}/tokens/{token_address}/trades")
def get_wallet_token_trades(
    address: str,
    token_address: str,
    limit: int = Query(default=1000, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    wallet = db.get(PublishedWallet, normalize_wallet_address(address))
    if wallet is None or wallet.manual_unlisted:
        raise HTTPException(status_code=404, detail="Wallet not found")

    requested_token = token_address.lower()
    trade_results = (wallet.metrics or {}).get("trade_results")
    matches = [
        row
        for row in (trade_results if isinstance(trade_results, list) else [])
        if isinstance(row, dict)
        and str(row.get("token_address") or row.get("condition_id") or "").lower() == requested_token
    ]
    matches.sort(key=lambda row: _finite_number(row.get("timestamp_ms")) or 0, reverse=True)
    return {"items": matches[:limit], "total": len(matches)}


@app.get("/api/v1/admin/status", dependencies=[Depends(require_admin)])
def admin_status(db: Session = Depends(get_db)) -> dict[str, Any]:
    stored_discovery = db.get(SystemSetting, "discovery_settings")
    discovery_defaults = {
        "period": settings.discovery_period,
        "limit": settings.discovery_limit,
        "sort_by": settings.discovery_sort,
        "direction": "desc",
        "interval_minutes": settings.discovery_interval_minutes,
        "max_new_analyses_per_run": 20,
        "analysis_concurrency": 1,
        "score_threshold": settings.score_threshold,
        "reanalysis_interval_days": settings.reanalysis_interval_days,
        "auto_analyze": True,
        "filters": {"min_realized_profit": 0, "min_total_cost": 1000},
    }
    discovery_settings = {
        **discovery_defaults,
        **(stored_discovery.value if stored_discovery else {}),
    }
    discovery_settings["filters"] = {
        **discovery_defaults["filters"],
        **discovery_settings.get("filters", {}),
    }
    discovery_settings["interval_minutes"] = discovery_interval_minutes(db)
    discovery_settings["max_new_analyses_per_run"] = max(
        1, min(20, int(discovery_settings.get("max_new_analyses_per_run", 20)))
    )
    discovery_settings["analysis_concurrency"] = normalize_analysis_concurrency(
        discovery_settings.get("analysis_concurrency")
    )
    discovery_settings.pop("interval_hours", None)
    discovery_settings.pop("wallet_type", None)
    last_batch = db.scalar(
        select(DiscoveryBatch).order_by(DiscoveryBatch.started_at.desc()).limit(1)
    )
    last_scheduled_success = db.scalar(
        select(DiscoveryBatch)
        .where(
            DiscoveryBatch.status == "completed",
            DiscoveryBatch.config["trigger"].astext == "scheduled",
        )
        .order_by(DiscoveryBatch.started_at.desc())
        .limit(1)
    )
    last_scheduled_attempt = db.scalar(
        select(DiscoveryBatch)
        .where(DiscoveryBatch.config["trigger"].astext == "scheduled")
        .order_by(DiscoveryBatch.started_at.desc())
        .limit(1)
    )
    next_collection_at = None
    if last_scheduled_success is not None and control_enabled(db, "discovery_enabled"):
        next_collection_at = last_scheduled_success.started_at + timedelta(
            minutes=int(discovery_settings["interval_minutes"])
        )
    if (
        last_scheduled_attempt is not None
        and last_scheduled_attempt.status == "failed"
        and last_scheduled_attempt.completed_at is not None
    ):
        retry_after = last_scheduled_attempt.completed_at + timedelta(
            minutes=SCHEDULED_FAILURE_COOLDOWN_MINUTES
        )
        if next_collection_at is None or retry_after > next_collection_at:
            next_collection_at = retry_after
    latest_analysis_batch = db.scalar(
        select(AnalysisBatch).order_by(AnalysisBatch.created_at.desc()).limit(1)
    )
    heartbeat = db.get(SystemSetting, "scheduler_heartbeat")
    last_successful_analysis_at = db.scalar(
        select(func.max(AnalysisRun.completed_at)).where(AnalysisRun.status == "completed")
    )
    stale_queued_cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
    stale_running_cutoff = datetime.now(timezone.utc) - timedelta(minutes=35)
    try:
        gmgn_cooldown_seconds = gmgn_cooldown_remaining()
    except Exception:
        gmgn_cooldown_seconds = 0
    return {
        "discovery_enabled": control_enabled(db, "discovery_enabled"),
        "analysis_enabled": control_enabled(db, "analysis_enabled"),
        "candidate_count": db.scalar(
            select(func.count()).select_from(CandidateWallet).where(
                CandidateWallet.last_score.is_(None)
            )
        ) or 0,
        "unqualified_count": db.scalar(
            select(func.count()).select_from(CandidateWallet).where(
                CandidateWallet.last_score.is_not(None),
                CandidateWallet.last_score <= int(discovery_settings["score_threshold"]),
            )
        ) or 0,
        "all_candidate_count": db.scalar(select(func.count()).select_from(CandidateWallet)) or 0,
        "published_count": db.scalar(
            select(func.count()).select_from(PublishedWallet).where(
                PublishedWallet.listed.is_(True),
                PublishedWallet.score > int(discovery_settings["score_threshold"]),
            )
        ) or 0,
        "queued_count": db.scalar(
            select(func.count()).select_from(AnalysisRun).where(AnalysisRun.status == "queued")
        ) or 0,
        "running_count": db.scalar(
            select(func.count()).select_from(AnalysisRun).where(AnalysisRun.status == "running")
        ) or 0,
        "last_collection_at": last_batch.started_at if last_batch else None,
        "last_successful_collection_at": (
            last_scheduled_success.started_at if last_scheduled_success else None
        ),
        "last_successful_analysis_at": last_successful_analysis_at,
        "next_collection_at": next_collection_at,
        "scheduler_heartbeat_at": heartbeat.updated_at if heartbeat else None,
        "scheduler_heartbeat": heartbeat.value if heartbeat else {},
        "continuous_analysis": True,
        "gmgn_cooldown_seconds": gmgn_cooldown_seconds,
        "gmgn_cooldown_until": (
            datetime.now(timezone.utc) + timedelta(seconds=gmgn_cooldown_seconds)
            if gmgn_cooldown_seconds
            else None
        ),
        "stale_task_count": db.scalar(
            select(func.count()).select_from(AnalysisRun).where(
                or_(
                    and_(
                        AnalysisRun.status == "queued",
                        AnalysisRun.created_at <= stale_queued_cutoff,
                    ),
                    and_(
                        AnalysisRun.status == "running",
                        AnalysisRun.started_at.is_not(None),
                        AnalysisRun.started_at <= stale_running_cutoff,
                    ),
                )
            )
        ) or 0,
        "latest_analysis_batch": analysis_batch_payload(latest_analysis_batch),
        "discovery_settings": discovery_settings,
    }


@app.put("/api/v1/admin/control/{name}", dependencies=[Depends(require_admin)])
def update_control(name: str, update: ControlUpdate, db: Session = Depends(get_db)) -> dict[str, Any]:
    if name not in {"discovery", "analysis"}:
        raise HTTPException(status_code=400, detail="未知控制项")
    key = f"{name}_enabled"
    setting = db.get(SystemSetting, key) or SystemSetting(key=key)
    setting.value = {"enabled": update.enabled}
    setting.updated_at = datetime.now(timezone.utc)
    db.add(setting)
    db.commit()
    return {"name": name, "enabled": update.enabled}


@app.post("/api/v1/admin/discovery/run", dependencies=[Depends(require_admin)])
def run_discovery(db: Session = Depends(get_db)) -> dict[str, str]:
    task = discover_task.delay("manual")
    return {"task_id": task.id, "status": "queued"}


@app.post("/api/v1/admin/analyze", dependencies=[Depends(require_admin)])
def run_analysis(request: AnalyzeRequest, db: Session = Depends(get_db)) -> dict[str, str]:
    if not control_enabled(db, "analysis_enabled"):
        raise HTTPException(status_code=409, detail="地址计算已暂停，请先启用地址计算")
    run, task_id, created = enqueue_analysis(
        db,
        request.address.lower(),
        request.trigger,
        request.force_refresh,
    )
    return {
        "task_id": task_id,
        "run_id": str(run.id),
        "status": "queued" if created else "already_queued",
    }


@app.post("/api/v1/admin/recompute-all", dependencies=[Depends(require_admin)])
def recompute_all(db: Session = Depends(get_db)) -> dict[str, int]:
    if not control_enabled(db, "analysis_enabled"):
        raise HTTPException(status_code=409, detail="地址计算已暂停，请先启用地址计算")
    score_threshold = analysis_policy(db)["score_threshold"]
    addresses = db.scalars(
        select(PublishedWallet.address).where(
            PublishedWallet.listed.is_(True),
            PublishedWallet.score > score_threshold,
        )
    ).all()
    queued = 0
    for address in addresses:
        _, _, created = enqueue_analysis(db, address, "manual_recompute_all", True)
        queued += int(created)
    return {
        "total": len(addresses),
        "queued": queued,
        "skipped": len(addresses) - queued,
    }


@app.post("/api/v1/admin/analyze-candidates", dependencies=[Depends(require_admin)])
def analyze_all_candidates(db: Session = Depends(get_db)) -> dict[str, Any]:
    if not control_enabled(db, "analysis_enabled"):
        raise HTTPException(status_code=409, detail="地址计算已暂停，请先启用地址计算")
    addresses = db.scalars(
        select(CandidateWallet.address)
        .where(
            CandidateWallet.source_rank.is_not(None),
            CandidateWallet.last_score.is_(None),
        )
        .order_by(CandidateWallet.source_rank.asc())
    ).all()
    total, queued, skipped, task_id, batch_id = enqueue_serial_analyses(
        db, list(addresses), "manual_candidate_all"
    )
    return {
        "total": total,
        "queued": queued,
        "skipped": skipped,
        "task_id": task_id,
        "batch_id": batch_id,
        "mode": "serial",
    }


@app.post("/api/v1/admin/recompute-due", dependencies=[Depends(require_admin)])
def recompute_due(db: Session = Depends(get_db)) -> dict[str, str]:
    if not control_enabled(db, "analysis_enabled"):
        raise HTTPException(status_code=409, detail="地址计算已暂停，请先启用地址计算")
    task = recompute_due_task.delay()
    return {"task_id": task.id, "status": "queued"}


@app.get("/api/v1/admin/candidates", dependencies=[Depends(require_admin)])
def list_candidates(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sort_by: str = Query(default="source_rank"),
    direction: str = Query(default="asc", pattern="^(asc|desc)$"),
    pool: str = Query(default="pending", pattern="^(pending|unqualified|all)$"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    sort_columns = {
        "source_rank": CandidateWallet.source_rank,
        "wallet": func.coalesce(CandidateWallet.name, CandidateWallet.address),
        "labels": cast(CandidateWallet.labels, String),
        "realized_profit": cast(CandidateWallet.discovery_metrics["realized_profit"].astext, Float),
        "total_profit": cast(CandidateWallet.discovery_metrics["total_profit"].astext, Float),
        "buy": cast(CandidateWallet.discovery_metrics["buy"].astext, Integer),
        "status": CandidateWallet.status,
        "last_score": CandidateWallet.last_score,
        "last_analyzed_at": CandidateWallet.last_analyzed_at,
        "last_seen_at": CandidateWallet.last_seen_at,
    }
    sort_column = sort_columns.get(sort_by)
    if sort_column is None:
        raise HTTPException(status_code=400, detail="不支持的候选地址排序字段")
    order = sort_column.asc().nulls_last() if direction == "asc" else sort_column.desc().nulls_last()
    score_threshold = analysis_policy(db)["score_threshold"]
    conditions = []
    if pool == "pending":
        conditions.append(CandidateWallet.last_score.is_(None))
    elif pool == "unqualified":
        conditions.extend(
            (
                CandidateWallet.last_score.is_not(None),
                CandidateWallet.last_score <= score_threshold,
            )
        )
    rows = db.scalars(
        select(CandidateWallet)
        .where(*conditions)
        .order_by(order, CandidateWallet.last_seen_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    items = [
        {
            "address": row.address,
            "name": row.name,
            "labels": row.labels,
            "source": row.source,
            "source_rank": row.source_rank,
            "discovery_metrics": row.discovery_metrics,
            "status": row.status,
            "last_score": row.last_score,
            "discovered_count": row.discovered_count,
            "last_seen_at": row.last_seen_at,
            "last_analyzed_at": row.last_analyzed_at,
            "next_eligible_at": row.next_eligible_at,
            "last_error": row.last_error,
        }
        for row in rows
    ]
    total = db.scalar(
        select(func.count()).select_from(CandidateWallet).where(*conditions)
    ) or 0
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@app.get("/api/v1/admin/published-wallets", dependencies=[Depends(require_admin)])
def list_published_wallets(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sort_by: str = Query(default="score"),
    direction: str = Query(default="desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    sort_columns = {
        "wallet": func.coalesce(PublishedWallet.name, PublishedWallet.address),
        "labels": cast(PublishedWallet.labels, String),
        "score": PublishedWallet.score,
        "actual_pnl": PublishedWallet.actual_pnl,
        "copy_pnl": PublishedWallet.copy_pnl,
        "win_rate": cast(PublishedWallet.summary["win_rate"].astext, Float),
        "tokens_traded": cast(PublishedWallet.summary["tokens_traded"].astext, Integer),
        "analyzed_at": PublishedWallet.analyzed_at,
    }
    sort_column = sort_columns.get(sort_by)
    if sort_column is None:
        raise HTTPException(status_code=400, detail="不支持的正式地址排序字段")
    order = sort_column.asc().nulls_last() if direction == "asc" else sort_column.desc().nulls_last()
    score_threshold = analysis_policy(db)["score_threshold"]
    conditions = (
        PublishedWallet.listed.is_(True),
        PublishedWallet.score > score_threshold,
    )
    rows = db.execute(
        select(*wallet_summary_columns())
        .where(*conditions)
        .order_by(order, PublishedWallet.analyzed_at.desc())
        .offset(offset)
        .limit(limit)
    ).mappings().all()
    total = db.scalar(
        select(func.count()).select_from(PublishedWallet).where(*conditions)
    ) or 0
    return {
        "items": [wallet_summary_payload(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.put("/api/v1/admin/discovery-settings", dependencies=[Depends(require_admin)])
def save_discovery_settings(payload: DiscoverySettings, db: Session = Depends(get_db)) -> dict[str, Any]:
    setting = db.get(SystemSetting, "discovery_settings") or SystemSetting(key="discovery_settings")
    values = payload.model_dump()
    setting.value = values
    setting.updated_at = datetime.now(timezone.utc)
    db.add(setting)
    score_threshold = int(values["score_threshold"])
    db.execute(
        update(PublishedWallet)
        .where(
            PublishedWallet.manual_unlisted.is_(False),
            PublishedWallet.score > score_threshold,
        )
        .values(listed=True, updated_at=datetime.now(timezone.utc))
    )
    db.execute(
        update(PublishedWallet)
        .where(
            PublishedWallet.manual_unlisted.is_(False),
            PublishedWallet.score <= score_threshold,
        )
        .values(listed=False, updated_at=datetime.now(timezone.utc))
    )
    db.commit()
    return setting.value


@app.get("/api/v1/admin/runs", dependencies=[Depends(require_admin)])
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sort_by: str = Query(default="created_at"),
    direction: str = Query(default="desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    sort_columns = {
        "address": AnalysisRun.address,
        "trigger": AnalysisRun.trigger,
        "status": AnalysisRun.status,
        "input_trade_count": AnalysisRun.input_trade_count,
        "score": AnalysisRun.score,
        "published": AnalysisRun.published,
        "created_at": AnalysisRun.created_at,
    }
    sort_column = sort_columns.get(sort_by)
    if sort_column is None:
        raise HTTPException(status_code=400, detail="不支持的分析队列排序字段")
    order = sort_column.asc().nulls_last() if direction == "asc" else sort_column.desc().nulls_last()
    rows = db.scalars(
        select(AnalysisRun).order_by(order, AnalysisRun.created_at.desc()).offset(offset).limit(limit)
    ).all()
    items = [
        {
            "id": str(row.id),
            "batch_id": str(row.batch_id) if row.batch_id else None,
            "address": row.address,
            "status": row.status,
            "trigger": row.trigger,
            "score": row.score,
            "input_trade_count": row.input_trade_count,
            "published": row.published,
            "created_at": row.created_at,
            "completed_at": row.completed_at,
            "error": row.error,
        }
        for row in rows
    ]
    total = db.scalar(select(func.count()).select_from(AnalysisRun)) or 0
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@app.get("/api/v1/admin/analysis-batches", dependencies=[Depends(require_admin)])
def list_analysis_batches(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sort_by: str = Query(default="created_at"),
    direction: str = Query(default="desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    sort_columns = {
        "created_at": AnalysisBatch.created_at,
        "status": AnalysisBatch.status,
        "total_count": AnalysisBatch.total_count,
        "completed_count": AnalysisBatch.completed_count,
        "failed_count": AnalysisBatch.failed_count,
    }
    sort_column = sort_columns.get(sort_by)
    if sort_column is None:
        raise HTTPException(status_code=400, detail="不支持的计算批次排序字段")
    order = sort_column.asc().nulls_last() if direction == "asc" else sort_column.desc().nulls_last()
    rows = db.scalars(
        select(AnalysisBatch).order_by(order).offset(offset).limit(limit)
    ).all()
    total = db.scalar(select(func.count()).select_from(AnalysisBatch)) or 0
    return {
        "items": [analysis_batch_payload(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/v1/admin/discovery-batches", dependencies=[Depends(require_admin)])
def list_batches(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sort_by: str = Query(default="started_at"),
    direction: str = Query(default="desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    sort_columns = {
        "started_at": DiscoveryBatch.started_at,
        "trigger": DiscoveryBatch.config["trigger"].astext,
        "status": DiscoveryBatch.status,
        "activity": cast(DiscoveryBatch.config["feed_trade_count"].astext, Integer),
        "candidate_pool": cast(DiscoveryBatch.config["candidate_pool_size"].astext, Integer),
        "requested_count": DiscoveryBatch.requested_count,
        "new_count": DiscoveryBatch.new_count,
        "eligible_count": cast(DiscoveryBatch.config["eligible_count"].astext, Integer),
        "error": DiscoveryBatch.error,
    }
    sort_column = sort_columns.get(sort_by)
    if sort_column is None:
        raise HTTPException(status_code=400, detail="不支持的采集记录排序字段")
    order = sort_column.asc().nulls_last() if direction == "asc" else sort_column.desc().nulls_last()
    rows = db.scalars(
        select(DiscoveryBatch).order_by(order, DiscoveryBatch.started_at.desc()).offset(offset).limit(limit)
    ).all()
    items = [
        {
            "id": str(row.id),
            "status": row.status,
            "source": row.source,
            "requested_count": row.requested_count,
            "received_count": row.received_count,
            "new_count": row.new_count,
            "duplicate_count": row.duplicate_count,
            "queued_count": row.queued_count,
            "config": row.config,
            "started_at": row.started_at,
            "completed_at": row.completed_at,
            "error": row.error,
        }
        for row in rows
    ]
    total = db.scalar(select(func.count()).select_from(DiscoveryBatch)) or 0
    return {"items": items, "total": total, "limit": limit, "offset": offset}

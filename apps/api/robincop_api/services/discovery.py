from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from copybot.gmgn import GMGNClient
from copybot.discovery import matches_filters, ranking_value

from ..models import AnalysisRun, CandidateWallet, DiscoveryBatch


TAG_LABELS = {
    "smart_degen": "Smart Money",
    "pump_smart": "Pump Smart Money",
    "kol": "KOL/VC",
    "renowned": "KOL/VC",
    "fresh_wallet": "Fresh Wallet",
    "sniper": "Sniper",
    "top_tracked": "Top Tracked",
    "top_renamed": "Top Renamed",
    "live": "Live",
}

PROFIT_SORT_FIELDS = {
    "realized_profit",
    "total_profit",
    "unrealized_profit",
    "total_realized_profit",
    "total_cost",
    "pnl",
    "buy",
    "sell",
}


def normalize_labels(raw: list[str]) -> list[str]:
    return list(dict.fromkeys(TAG_LABELS.get(tag, tag.replace("_", " ").title()) for tag in raw))


def _chunks(items: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def select_eligible_analysis_addresses(
    ranked_rows: list[dict[str, Any]],
    candidates: dict[str, CandidateWallet],
    active_analysis_addresses: set[str],
    *,
    now: datetime,
    analysis_limit: int,
) -> tuple[list[str], int]:
    """Pick the highest-ranked due wallets from the complete filtered pool."""
    queued: list[str] = []
    eligible_count = 0
    for row in ranked_rows:
        address = str(row.get("wallet_address") or "").lower()
        candidate = candidates.get(address)
        if candidate is None:
            continue
        is_due = candidate.next_eligible_at is None or candidate.next_eligible_at <= now
        if not is_due or address in active_analysis_addresses:
            continue
        candidate.status = "pending"
        eligible_count += 1
        if len(queued) < analysis_limit:
            queued.append(address)
    return queued, eligible_count


def collect_realtime_candidates(
    db: Session,
    *,
    requested_count: int = 200,
    period: str = "7d",
    sort_by: str = "realized_profit",
    direction: str = "desc",
    filters: dict[str, Any] | None = None,
    analysis_limit: int = 20,
    trigger: str = "manual",
) -> tuple[DiscoveryBatch, list[str]]:
    """Collect realtime wallets, batch-query PnL, rank them, and return due wallets.

    GMGN's Robinhood activity source is a capped realtime window, not a
    leaderboard. Each run grows a persistent candidate pool. The pool is then
    queried through wallet_profits and ranked locally.
    """
    if period not in {"1d", "7d", "30d"}:
        raise ValueError("period must be one of: 1d, 7d, 30d")
    if sort_by not in PROFIT_SORT_FIELDS:
        raise ValueError(f"unsupported discovery sort: {sort_by}")
    if direction not in {"asc", "desc"}:
        raise ValueError("direction must be asc or desc")
    if not 1 <= analysis_limit <= 200:
        raise ValueError("analysis_limit must be between 1 and 200")

    selected_filters = filters or {}
    batch = DiscoveryBatch(
        source="gmgn_realtime_activity",
        requested_count=requested_count,
        config={
            "chain": "robinhood",
            "trigger": trigger,
            "period": period,
            "sort_by": sort_by,
            "direction": direction,
            "filters": selected_filters,
            "requested_count": requested_count,
            "analysis_limit": analysis_limit,
            "connector": "realtime_activity_plus_wallet_profits",
        },
    )
    db.add(batch)
    db.commit()

    queued: list[str] = []
    try:
        client = GMGNClient()
        feed_rows = client.fetch_realtime_wallet_activity(limit=100)
        profiles: dict[str, dict[str, Any]] = {}
        for row in feed_rows:
            address = str(row.get("maker") or "").lower()
            if address.startswith("0x") and len(address) == 42:
                profiles.setdefault(address, row)

        existing_candidates = db.scalars(select(CandidateWallet)).all()
        candidates = {candidate.address: candidate for candidate in existing_candidates}
        now = datetime.now(timezone.utc)
        for address, row in profiles.items():
            profile = row.get("maker_info") if isinstance(row.get("maker_info"), dict) else {}
            candidate = candidates.get(address)
            if candidate is None:
                candidate = CandidateWallet(
                    address=address,
                    source="gmgn_realtime_activity",
                    name=profile.get("name") or profile.get("twitter_name") or None,
                    labels=normalize_labels(profile.get("tags") or []),
                )
                db.add(candidate)
                candidates[address] = candidate
                batch.new_count += 1
            else:
                candidate.discovered_count += 1
                candidate.last_seen_at = now
                candidate.source = "gmgn_realtime_activity"
                candidate.name = profile.get("name") or profile.get("twitter_name") or candidate.name
                candidate.labels = normalize_labels(profile.get("tags") or candidate.labels)
                batch.duplicate_count += 1

        db.flush()
        addresses = sorted(
            address for address, candidate in candidates.items() if candidate.source != "manual"
        )
        profit_rows: list[dict[str, Any]] = []
        for chunk in _chunks(addresses, 100):
            profit_rows.extend(client.fetch_wallet_profits(chunk, period=period))

        ranked = [
            row
            for row in profit_rows
            if str(row.get("wallet_address") or "").lower() in candidates
            and matches_filters(row, selected_filters)
        ]
        ranked.sort(key=lambda row: ranking_value(row, sort_by), reverse=direction == "desc")
        selected = ranked[:requested_count]

        for candidate in candidates.values():
            candidate.source_rank = None
        active_analysis_addresses = set(
            db.scalars(
                select(AnalysisRun.address).where(
                    AnalysisRun.status.in_(("queued", "running"))
                )
            ).all()
        )
        ranked_summary: list[dict[str, Any]] = []
        for rank, row in enumerate(selected, start=1):
            address = str(row.get("wallet_address") or "").lower()
            candidate = candidates[address]
            candidate.source_rank = rank
            candidate.discovery_metrics = {
                **row,
                "period": period,
                "sort_by": sort_by,
                "ranking_value": str(ranking_value(row, sort_by)),
                "captured_at": now.isoformat(),
            }
            ranked_summary.append(
                {
                    "rank": rank,
                    "address": address,
                    "realized_profit": row.get("realized_profit"),
                    "total_profit": row.get("total_profit"),
                    "buy": row.get("buy"),
                    "sell": row.get("sell"),
                    "ranking_value": str(ranking_value(row, sort_by)),
                }
            )
        queued, eligible_count = select_eligible_analysis_addresses(
            ranked,
            candidates,
            active_analysis_addresses,
            now=now,
            analysis_limit=analysis_limit,
        )

        batch.received_count = len(selected)
        batch.queued_count = len(queued)
        batch.config = {
            **batch.config,
            "feed_trade_count": len(feed_rows),
            "feed_unique_wallets": len(profiles),
            "candidate_pool_size": len(candidates),
            "profit_rows": len(profit_rows),
            "eligible_count": eligible_count,
            "ranked_wallets": ranked_summary,
        }
        batch.status = "completed"
        batch.completed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:
        batch.status = "failed"
        batch.error = str(exc)
        batch.completed_at = datetime.now(timezone.utc)
        db.commit()
        # The collection task owns retry policy. Returning a failed batch made
        # Celery report a successful task and silently suppressed retries.
        raise
    return batch, queued

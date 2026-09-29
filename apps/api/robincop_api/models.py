from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CandidateWallet(Base):
    __tablename__ = "candidate_wallets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    address: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(40), default="gmgn_realtime_activity")
    source_rank: Mapped[int | None] = mapped_column(Integer)
    discovery_metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    name: Mapped[str | None] = mapped_column(String(200))
    labels: Mapped[list[str]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    discovered_count: Mapped[int] = mapped_column(Integer, default=1)
    last_score: Mapped[int | None] = mapped_column(Integer)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_eligible_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class PublishedWallet(Base):
    __tablename__ = "published_wallets"

    address: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(200))
    twitter_name: Mapped[str | None] = mapped_column(String(200))
    ens: Mapped[str | None] = mapped_column(String(200))
    labels: Mapped[list[str]] = mapped_column(JSONB, default=list)
    tag_ranks: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    score: Mapped[int] = mapped_column(Integer, index=True)
    actual_pnl: Mapped[float] = mapped_column(Float, default=0)
    copy_pnl: Mapped[float] = mapped_column(Float, default=0)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    report_text: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    listed: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    manual_unlisted: Mapped[bool] = mapped_column(Boolean, default=False)
    algorithm_version: Mapped[str] = mapped_column(String(40), default="v1")
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_published_list_score", "listed", "score"),)


class AnalysisBatch(Base):
    __tablename__ = "analysis_batches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(40), default="candidate_serial")
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    requested_count: Mapped[int] = mapped_column(Integer, default=0)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    current_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis_batches.id", ondelete="SET NULL"), index=True
    )
    address: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    trigger: Mapped[str] = mapped_column(String(30), default="discovery")
    algorithm_version: Mapped[str] = mapped_column(String(40), default="v1")
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    score: Mapped[int | None] = mapped_column(Integer)
    input_trade_count: Mapped[int | None] = mapped_column(Integer)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DiscoveryBatch(Base):
    __tablename__ = "discovery_batches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(30), default="running")
    source: Mapped[str] = mapped_column(String(40), default="gmgn_realtime_activity")
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    requested_count: Mapped[int] = mapped_column(Integer)
    received_count: Mapped[int] = mapped_column(Integer, default=0)
    new_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    queued_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ControlUpdate(BaseModel):
    enabled: bool


class DiscoverySettings(BaseModel):
    period: str = Field(default="7d", pattern="^(1d|7d|30d)$")
    sort_by: Literal[
        "realized_profit",
        "total_profit",
        "unrealized_profit",
        "total_realized_profit",
        "total_cost",
        "pnl",
        "buy",
        "sell",
    ] = "realized_profit"
    direction: str = Field(default="desc", pattern="^(asc|desc)$")
    limit: int = Field(default=200, ge=1, le=2000)
    interval_minutes: int = Field(default=30, ge=5, le=43200)
    # Accept legacy values when saving settings; runtime policy applies the
    # small-server safety caps.
    max_new_analyses_per_run: int = Field(default=20, ge=1, le=200)
    analysis_concurrency: int = Field(default=1, ge=1, le=10)
    score_threshold: int = Field(default=30, ge=0, le=100)
    reanalysis_interval_days: int = Field(default=7, ge=1, le=365)
    auto_analyze: bool = True
    filters: dict[str, Any] = Field(
        default_factory=lambda: {"min_realized_profit": 0, "min_total_cost": 1000}
    )


class AnalyzeRequest(BaseModel):
    address: str = Field(pattern="^0x[a-fA-F0-9]{40}$")
    force_refresh: bool = False
    trigger: str = "manual"

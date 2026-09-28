from __future__ import annotations

import os
from dataclasses import dataclass


def normalize_discovery_interval_minutes(
    value: dict | None,
    *,
    default: int,
) -> int:
    """Read the minute setting while accepting the legacy hour setting."""
    configured = value or {}
    if "interval_minutes" in configured:
        minutes = int(configured["interval_minutes"])
    elif "interval_hours" in configured:
        minutes = int(configured["interval_hours"]) * 60
    else:
        minutes = default
    return max(5, min(43_200, minutes))


def normalize_analysis_concurrency(value: object, *, default: int = 1) -> int:
    try:
        concurrency = int(value if value is not None else default)
    except (TypeError, ValueError):
        concurrency = default
    return max(1, min(2, concurrency))


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+psycopg://robincop:robincop@localhost:5432/robincop"
    )
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    admin_api_key: str = os.getenv("ADMIN_API_KEY", "change-me")
    public_origin: str = os.getenv("PUBLIC_ORIGIN", "http://localhost:3000")
    api_root_path: str = os.getenv("API_ROOT_PATH", "")
    score_threshold: int = int(os.getenv("SCORE_THRESHOLD", "30"))
    discovery_period: str = os.getenv("DISCOVERY_PERIOD", "7d")
    discovery_limit: int = int(os.getenv("DISCOVERY_LIMIT", "200"))
    discovery_sort: str = os.getenv("DISCOVERY_SORT", "realized_profit")
    discovery_interval_minutes: int = int(os.getenv("DISCOVERY_INTERVAL_MINUTES", "30"))
    reanalysis_interval_days: int = int(os.getenv("REANALYSIS_INTERVAL_DAYS", "7"))
    max_trades: int = int(os.getenv("MAX_TRADES", "5000"))
    analysis_history_days: int = int(os.getenv("ANALYSIS_HISTORY_DAYS", "30"))
    discovery_history_days: int = int(os.getenv("DISCOVERY_HISTORY_DAYS", "30"))


settings = Settings()

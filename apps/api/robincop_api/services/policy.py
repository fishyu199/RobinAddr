from __future__ import annotations

from sqlalchemy.orm import Session

from ..config import normalize_analysis_concurrency, normalize_discovery_interval_minutes, settings
from ..models import SystemSetting


def discovery_interval_minutes(db: Session) -> int:
    configured = db.get(SystemSetting, "discovery_settings")
    return normalize_discovery_interval_minutes(
        configured.value if configured else None,
        default=settings.discovery_interval_minutes,
    )


def analysis_policy(db: Session) -> dict[str, int]:
    configured = db.get(SystemSetting, "discovery_settings")
    value = configured.value if configured else {}
    return {
        "concurrency": normalize_analysis_concurrency(value.get("analysis_concurrency")),
        "score_threshold": max(
            0, min(100, int(value.get("score_threshold", settings.score_threshold)))
        ),
        "reanalysis_interval_days": max(
            1,
            min(
                365,
                int(value.get("reanalysis_interval_days", settings.reanalysis_interval_days)),
            ),
        ),
    }

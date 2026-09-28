"""Robinhood Chain copy-trading backtest engine."""

from .backtest import CopyBacktester, run_backtest
from .analytics import DEFAULT_REFERRAL_URL, build_legacy_metrics
from .models import BacktestConfig, BacktestResult, Side, Trade
from .telegram_report import SUPPORTED_LANGUAGES, render_telegram_report

__all__ = [
    "BacktestConfig",
    "BacktestResult",
    "CopyBacktester",
    "DEFAULT_REFERRAL_URL",
    "Side",
    "SUPPORTED_LANGUAGES",
    "Trade",
    "build_legacy_metrics",
    "run_backtest",
    "render_telegram_report",
]

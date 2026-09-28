#!/usr/bin/env python3
"""Robinhood Chain equivalent of the Polymarket run_poly script.

Usage:
    GMGN_API_KEY=gmgn_... python run_robinhood.py 0xWallet zh-CN

The public ``analyze_wallet`` function intentionally mirrors the old script's
return shape: ``{"report_text": ..., "metrics": ...}``.
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from copybot import (
    SUPPORTED_LANGUAGES,
    BacktestConfig,
    build_legacy_metrics,
    render_telegram_report,
    run_backtest,
)
from copybot.gmgn import GMGNClient, normalize_gmgn_payload


def analyze_wallet(
    wallet_address: str,
    lang: str = "zh-CN",
    ref_code: str = "",
    bot_name: str = "",
    client: str = "tg",
    include_all_tokens: bool = False,
    skip_db: bool = True,
    *,
    max_trades: int = 5_000,
    buy_price_penalty: str = "0.025",
    sell_price_penalty: str = "0.025",
    include_target_fees: bool = False,
    cache_dir: str | None = ".cache/gmgn",
    gmgn_client: GMGNClient | None = None,
) -> dict[str, Any]:
    """Fetch one wallet, run the spot copy backtest, and build its TG report.

    ``ref_code``, ``bot_name`` and ``skip_db`` are accepted for call-site
    compatibility with the Polymarket script. No database write is performed.
    """
    del ref_code, bot_name, skip_db
    analysis_started = time.perf_counter()
    api = gmgn_client or GMGNClient()
    cache_path = (
        Path(cache_dir) / f"robinhood-{wallet_address.lower()}-{max_trades}.json"
        if cache_dir
        else None
    )
    gmgn_stats: dict[str, Any] = {}
    gmgn_stats_error = ""
    # Wallet stats has no dependency on the activity cursor chain, so overlap
    # it with the BUY/SELL activity fetch for a small but safe latency win.
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="gmgn-wallet") as executor:
        activity_future = executor.submit(
            api.fetch_wallet_activities,
            wallet_address,
            limit=max_trades,
            cache_path=cache_path,
        )
        stats_future = executor.submit(api.fetch_wallet_stats, wallet_address, period="30d")
        payload = activity_future.result()
        trades, quality = normalize_gmgn_payload(payload)
        config = BacktestConfig.create(
            max_trades=max_trades,
            buy_price_penalty=buy_price_penalty,
            sell_price_penalty=sell_price_penalty,
            include_observed_target_fees=include_target_fees,
        )
        result = run_backtest(trades, config, normalization_quality=quality)
        try:
            gmgn_stats = stats_future.result()
        except Exception as exc:
            gmgn_stats_error = str(exc)
    profile = gmgn_stats.get("common") if isinstance(gmgn_stats.get("common"), dict) else {}
    legacy_metrics = build_legacy_metrics(
        result,
        wallet_address=wallet_address,
        profile=profile,
        include_all_tokens=include_all_tokens,
    )
    report_text = render_telegram_report(
        result,
        wallet_address=wallet_address,
        lang=lang,
        profile=profile,
        metrics=legacy_metrics,
    )
    metrics = result.to_dict(include_trade_results=(client == "web" and include_all_tokens))
    metrics.update(legacy_metrics)
    if gmgn_stats:
        metrics["gmgn_stats_30d"] = gmgn_stats
    if gmgn_stats_error:
        metrics["gmgn_stats_error"] = gmgn_stats_error
    metrics["analysis_elapsed_seconds"] = round(time.perf_counter() - analysis_started, 3)
    return {"report_text": report_text, "metrics": metrics}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze a Robinhood Chain wallet for copy trading")
    parser.add_argument("wallet")
    parser.add_argument("lang", nargs="?", choices=SUPPORTED_LANGUAGES, default="zh-CN")
    parser.add_argument("--max-trades", type=int, default=5_000)
    parser.add_argument("--json", action="store_true", help="print report and metrics as JSON")
    parser.add_argument("--include-target-fees", action="store_true")
    parser.add_argument("--no-cache", action="store_true", help="disable the activity checkpoint cache")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output = analyze_wallet(
        args.wallet,
        lang=args.lang,
        max_trades=args.max_trades,
        include_target_fees=args.include_target_fees,
        cache_dir=None if args.no_cache else ".cache/gmgn",
        include_all_tokens=args.json,
        client="web" if args.json else "tg",
    )
    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(output["report_text"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

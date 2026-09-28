"""Command-line entry point for a GMGN/Robinhood copy backtest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .backtest import run_backtest
from .gmgn import GMGNClient, infer_wallet_address, normalize_gmgn_payload
from .models import BacktestConfig
from .telegram_report import SUPPORTED_LANGUAGES, render_telegram_report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backtest a Robinhood Chain wallet copy strategy")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="saved GMGN wallet_activity JSON")
    source.add_argument("--wallet", help="Robinhood Chain wallet address to fetch from GMGN")
    parser.add_argument("--output", type=Path, help="write result JSON here; defaults to stdout")
    parser.add_argument("--format", choices=("json", "telegram"), default="json")
    parser.add_argument("--lang", choices=SUPPORTED_LANGUAGES, default="zh-CN")
    parser.add_argument("--wallet-address", help="wallet label when reading a saved JSON payload")
    parser.add_argument("--max-trades", type=int, default=5_000)
    parser.add_argument("--buy-penalty", default="0.025")
    parser.add_argument("--sell-penalty", default="0.025")
    parser.add_argument("--copy-fee-rate", default="0")
    parser.add_argument("--copy-fixed-cost-usd", default="0")
    parser.add_argument("--include-target-fees", action="store_true")
    parser.add_argument(
        "--mark-open-at-spot",
        action="store_true",
        help="do not apply the sell penalty to still-open copy positions",
    )
    parser.add_argument("--summary-only", action="store_true", help="omit per-trade results")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.input:
        payload: Any = json.loads(args.input.read_text(encoding="utf-8"))
    else:
        payload = GMGNClient().fetch_wallet_activities(args.wallet, limit=args.max_trades)

    trades, quality = normalize_gmgn_payload(payload)
    config = BacktestConfig.create(
        max_trades=args.max_trades,
        buy_price_penalty=args.buy_penalty,
        sell_price_penalty=args.sell_penalty,
        copy_fee_rate=args.copy_fee_rate,
        copy_fixed_cost_usd=args.copy_fixed_cost_usd,
        include_observed_target_fees=args.include_target_fees,
        value_open_positions_at_copy_exit_price=not args.mark_open_at_spot,
    )
    result = run_backtest(trades, config, normalization_quality=quality)
    if args.format == "telegram":
        wallet_address = args.wallet or args.wallet_address or infer_wallet_address(payload)
        rendered = render_telegram_report(result, wallet_address=wallet_address, lang=args.lang)
    else:
        rendered = json.dumps(
            result.to_dict(include_trade_results=not args.summary_only),
            ensure_ascii=False,
            indent=2,
        )
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        sys.stdout.write(rendered + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

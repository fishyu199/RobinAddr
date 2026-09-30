"""Generate stored reports from persisted metrics; never fetch GMGN data."""

from __future__ import annotations

import argparse
import json
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from copybot.telegram_report import SUPPORTED_LANGUAGES, render_telegram_report

from .database import SessionLocal
from .models import PublishedWallet


def backfill_reports(
    db: Session,
    *,
    address: str | None = None,
    apply: bool = False,
    batch_size: int = 20,
    lang: str = "en",
    overwrite: bool = False,
) -> dict[str, Any]:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if lang not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported language: {lang}")
    counts: dict[str, Any] = {"scanned": 0, "generated": 0, "updated": 0, "skipped": 0, "errors": []}
    cursor = ""
    while True:
        query = select(
            PublishedWallet.address,
            PublishedWallet.metrics,
            PublishedWallet.analyzed_at,
            PublishedWallet.report_text,
        ).where(PublishedWallet.address > cursor)
        if not overwrite:
            query = query.where(PublishedWallet.report_text.is_(None))
        if address:
            query = query.where(PublishedWallet.address == address.lower())
        rows = db.execute(query.order_by(PublishedWallet.address).limit(batch_size)).all()
        if not rows:
            break
        for row in rows:
            cursor = row.address
            counts["scanned"] += 1
            try:
                report = render_telegram_report(metrics=row.metrics, wallet_address=row.address, lang=lang)
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                counts["errors"].append({"address": row.address, "error": str(exc)})
                continue
            counts["generated"] += 1
            if apply:
                # Do not overwrite a report or newer analysis written since this row was read.
                report_unchanged = (
                    PublishedWallet.report_text.is_(None)
                    if row.report_text is None
                    else PublishedWallet.report_text == row.report_text
                )
                updated = db.execute(
                    update(PublishedWallet).where(
                        PublishedWallet.address == row.address,
                        report_unchanged,
                        PublishedWallet.analyzed_at == row.analyzed_at,
                    ).values(report_text=report)
                ).rowcount
                counts["updated"] += updated
                counts["skipped"] += int(updated == 0)
        if apply:
            db.commit()
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", help="only backfill this wallet")
    parser.add_argument("--apply", action="store_true", help="persist reports; default is a read-only preview")
    parser.add_argument("--lang", choices=SUPPORTED_LANGUAGES, default="en", help="stored report language")
    parser.add_argument("--overwrite", action="store_true", help="rewrite existing reports as well as filling nulls")
    args = parser.parse_args()
    with SessionLocal() as db:
        counts = backfill_reports(
            db,
            address=args.address,
            apply=args.apply,
            lang=args.lang,
            overwrite=args.overwrite,
        )
    print(json.dumps({
        "mode": "apply" if args.apply else "preview",
        "language": args.lang,
        "overwrite": args.overwrite,
        **counts,
    }, ensure_ascii=False, indent=2))
    return int(bool(counts["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())

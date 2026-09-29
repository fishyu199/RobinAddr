"""Fill missing latest reports from persisted metrics; never fetch GMGN data."""

from __future__ import annotations

import argparse
import json
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from copybot.telegram_report import render_telegram_report

from .database import SessionLocal
from .models import PublishedWallet


def backfill_reports(
    db: Session, *, address: str | None = None, apply: bool = False, batch_size: int = 20
) -> dict[str, Any]:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    counts: dict[str, Any] = {"scanned": 0, "generated": 0, "updated": 0, "skipped": 0, "errors": []}
    cursor = ""
    while True:
        query = select(
            PublishedWallet.address, PublishedWallet.metrics, PublishedWallet.analyzed_at
        ).where(PublishedWallet.report_text.is_(None), PublishedWallet.address > cursor)
        if address:
            query = query.where(PublishedWallet.address == address.lower())
        rows = db.execute(query.order_by(PublishedWallet.address).limit(batch_size)).all()
        if not rows:
            break
        for row in rows:
            cursor = row.address
            counts["scanned"] += 1
            try:
                report = render_telegram_report(metrics=row.metrics, wallet_address=row.address, lang="zh-CN")
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                counts["errors"].append({"address": row.address, "error": str(exc)})
                continue
            counts["generated"] += 1
            if apply:
                # Do not overwrite a report or newer analysis written since the read.
                updated = db.execute(
                    update(PublishedWallet).where(
                        PublishedWallet.address == row.address,
                        PublishedWallet.report_text.is_(None),
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
    args = parser.parse_args()
    with SessionLocal() as db:
        counts = backfill_reports(db, address=args.address, apply=args.apply)
    print(json.dumps({"mode": "apply" if args.apply else "preview", **counts}, ensure_ascii=False, indent=2))
    return int(bool(counts["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())

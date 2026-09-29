from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.robincop_api import main
from apps.api.robincop_api.models import PublishedWallet


@compiles(JSONB, "sqlite")
def sqlite_jsonb(_type, _compiler, **_kwargs):
    return "JSON"


class WalletFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
        )
        PublishedWallet.__table__.create(self.engine)
        with Session(self.engine) as db:
            for score in (30, 31, 50, 51, 75, 90, 100):
                db.add(PublishedWallet(
                    address=f"0x{score:040x}",
                    name="Alpha" if score in (51, 75) else "Other",
                    score=score,
                    listed=score != 90,
                    labels=["Smart Money"] if score in (51, 100) else ["Sniper"],
                    metrics={},
                    summary={},
                ))
            db.commit()

        def database():
            with Session(self.engine) as db:
                yield db

        main.app.dependency_overrides[main.get_db] = database
        self.policy = patch.object(main, "analysis_policy", return_value={"score_threshold": 30})
        self.mock_policy = self.policy.start()

    def tearDown(self) -> None:
        self.policy.stop()
        main.app.dependency_overrides.pop(main.get_db)
        self.engine.dispose()

    def request(self, **params):
        # Exercise FastAPI validation and the real SQL queries without starting
        # production database/worker services or requiring an HTTP test client.
        async def run():
            messages = []

            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}

            async def send(message):
                messages.append(message)

            await main.app({
                "type": "http", "asgi": {"version": "3.0"},
                "http_version": "1.1", "method": "GET", "scheme": "http",
                "path": "/api/v1/wallets", "raw_path": b"/api/v1/wallets",
                "root_path": "", "query_string": urlencode(params).encode(),
                "headers": [], "server": ("testserver", 80), "client": ("127.0.0.1", 1),
            }, receive, send)
            status = next(m["status"] for m in messages if m["type"] == "http.response.start")
            body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
            return status, json.loads(body)

        return asyncio.run(run())

    def test_default_and_low_minimum_preserve_publication_rules(self) -> None:
        for params in ({}, {"min_score": 0}):
            with self.subTest(params=params):
                status, body = self.request(**params)
                self.assertEqual(status, 200)
                self.assertEqual([w["score"] for w in body["items"]], [100, 75, 51, 50, 31])
                self.assertEqual(body["total"], 5)

    def test_strict_minimum_applies_before_pagination_and_counts(self) -> None:
        status, body = self.request(min_score=50, limit=1, offset=1)
        self.assertEqual(status, 200)
        self.assertEqual([w["score"] for w in body["items"]], [75])
        self.assertEqual(body["total"], 3)
        self.assertEqual(body["category_counts"], {
            "all": 3, "smart-money": 2, "kol-vc": 0, "fresh": 0, "sniper": 1,
        })

    def test_minimum_combines_with_search(self) -> None:
        status, body = self.request(min_score=50, search="ALPHA")
        self.assertEqual(status, 200)
        self.assertEqual([w["score"] for w in body["items"]], [75, 51])
        self.assertEqual(body["total"], 2)

    def test_higher_publication_threshold_is_still_enforced(self) -> None:
        self.mock_policy.return_value = {"score_threshold": 75}
        status, body = self.request(min_score=50)
        self.assertEqual(status, 200)
        self.assertEqual([w["score"] for w in body["items"]], [100])

    def test_maximum_boundary_returns_empty_result(self) -> None:
        status, body = self.request(min_score=100)
        self.assertEqual(status, 200)
        self.assertEqual(body["items"], [])
        self.assertEqual(body["total"], 0)
        self.assertTrue(all(count == 0 for count in body["category_counts"].values()))

    def test_invalid_minimum_is_rejected(self) -> None:
        for value in (-1, 101, "abc", "50.5"):
            with self.subTest(value=value):
                status, _ = self.request(min_score=value)
                self.assertEqual(status, 422)


if __name__ == "__main__":
    unittest.main()

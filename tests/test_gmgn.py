from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from copybot.gmgn import GMGNClient, normalize_gmgn_payload


class GMGNNormalizationTests(unittest.TestCase):
    def test_smart_money_discovery_extracts_list(self) -> None:
        client = GMGNClient(api_key="test-key")
        with patch.object(
            client,
            "_get",
            return_value={"list": [{"maker": "0xabc", "maker_info": {"tags": ["smart_degen"]}}]},
        ) as request:
            rows = client.fetch_smart_money_activity(limit=100)
        self.assertEqual(rows[0]["maker"], "0xabc")
        self.assertEqual(request.call_args.args[0], "/v1/user/smartmoney")

    def test_kol_discovery_uses_kol_feed(self) -> None:
        client = GMGNClient(api_key="test-key")
        with patch.object(client, "_get", return_value={"list": [{"maker": "0xabc"}]}) as request:
            rows = client.fetch_tracked_wallet_activity(wallet_type="kol", limit=100)
        self.assertEqual(rows[0]["maker"], "0xabc")
        self.assertEqual(request.call_args.args[0], "/v1/user/kol")

    def test_realtime_discovery_uses_fixed_robinhood_activity_source(self) -> None:
        client = GMGNClient(api_key="test-key")
        with patch.object(
            client,
            "_get",
            return_value={"list": [{"maker": "0xabc"}]},
        ) as request:
            rows = client.fetch_realtime_wallet_activity(limit=100)
        self.assertEqual(rows[0]["maker"], "0xabc")
        self.assertEqual(request.call_args.args[0], "/v1/user/smartmoney")
        self.assertEqual(request.call_args.args[1]["chain"], "robinhood")

    def test_wallet_profits_batches_addresses_in_post_body(self) -> None:
        client = GMGNClient(api_key="test-key")
        with patch.object(
            client,
            "_post",
            return_value={"list": [{"wallet_address": "0xabc", "realized_profit": "12"}]},
        ) as request:
            rows = client.fetch_wallet_profits(["0xABC", "0xabc"], period="7d")
        self.assertEqual(len(rows), 1)
        self.assertEqual(request.call_args.args[0], "/v1/user/wallet_profits")
        self.assertEqual(request.call_args.args[2]["wallet_addresses"], ["0xabc"])

    def test_normalizes_buy_and_sell_and_ignores_prediction_events(self) -> None:
        payload = {
            "code": 0,
            "data": {
                "fetch_mode": "parallel_buy_sell_keepalive_gzip",
                "network_request_count": 4,
                "network_elapsed_seconds": 0.42,
                "activities": [
                    {
                        "chain": "robinhood",
                        "tx_hash": "0xbuy",
                        "timestamp": 1_700_000_000,
                        "event_type": "buy",
                        "token": {"address": "0xABC", "symbol": "ABC"},
                        "token_amount": "10",
                        "cost_usd": "25",
                        "price_usd": "2.5",
                        "gas_usd": "0.1",
                        "dex_usd": "0.2",
                    },
                    {
                        "chain": "robinhood",
                        "tx_hash": "0xredeem",
                        "timestamp": 1_700_000_001,
                        "event_type": "redeem",
                        "token": {"address": "0xABC", "symbol": "ABC"},
                        "token_amount": "10",
                        "cost_usd": "30",
                        "price_usd": "3",
                    },
                    {
                        "chain": "robinhood",
                        "tx_hash": "0xsell",
                        "timestamp": 1_700_000_002,
                        "event_type": "sell",
                        "token": {"address": "0xABC", "symbol": "ABC"},
                        "token_amount": "10",
                        "cost_usd": "30",
                        "price_usd": "3",
                        "buy_cost_usd": "25",
                    },
                ]
            },
        }
        trades, quality = normalize_gmgn_payload(payload)
        self.assertEqual(len(trades), 2)
        self.assertEqual(trades[0].timestamp_ms, 1_700_000_000_000)
        self.assertEqual(str(trades[0].observed_fee_usd), "0.3")
        self.assertEqual(trades[0].token_address, "0xabc")
        self.assertEqual(quality["skipped_by_reason"], {"unsupported_event:redeem": 1})
        self.assertEqual(quality["network_request_count"], 4)
        self.assertEqual(quality["network_elapsed_seconds"], 0.42)

    def test_derives_missing_price_from_cost_and_quantity(self) -> None:
        trades, _ = normalize_gmgn_payload(
            [
                {
                    "tx_hash": "0x1",
                    "timestamp": 1_700_000_000,
                    "event_type": "buy",
                    "token": {"address": "0x1"},
                    "token_amount": "4",
                    "cost_usd": "10",
                }
            ]
        )
        self.assertEqual(str(trades[0].price_usd), "2.5")

    def test_accepts_gmgn_smartmoney_aliases(self) -> None:
        trades, _ = normalize_gmgn_payload(
            {
                "data": {
                    "list": [
                        {
                            "transaction_hash": "0xsmart",
                            "timestamp": 1_700_000_000,
                            "side": "buy",
                            "base_address": "0xTOKEN",
                            "base_token": {"symbol": "TOK"},
                            "base_amount": "20",
                            "amount_usd": "50",
                            "price_usd": "2.5",
                        }
                    ]
                }
            }
        )
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].tx_hash, "0xsmart")
        self.assertEqual(str(trades[0].quote_amount_usd), "50")
        self.assertEqual(trades[0].token_symbol, "TOK")

    def test_client_uses_parallel_50_row_side_streams_and_unique_client_ids(self) -> None:
        client = GMGNClient(api_key="test-key")
        calls = []

        def fake_get(path, params):
            calls.append(dict(params))
            count = params["limit"]
            side = params["type"]
            start = 2_000 if side == "buy" else 1_999
            return {
                "data": {
                    "activities": [
                        {
                            "tx_hash": f"0x{side}-{i}",
                            "event_type": side,
                            "timestamp": start - i,
                        }
                        for i in range(count)
                    ],
                    "next": f"cursor-{side}",
                }
            }

        with patch.object(client, "_get", side_effect=fake_get):
            payload = client.fetch_wallet_activities("0xwallet", limit=60)

        self.assertEqual(len(payload["data"]["activities"]), 60)
        self.assertEqual(sorted(call["limit"] for call in calls), [50, 50])
        self.assertEqual({call["type"] for call in calls}, {"buy", "sell"})
        self.assertNotEqual(calls[0]["client_id"], calls[1]["client_id"])

    def test_completed_activity_cache_avoids_repeat_fetch(self) -> None:
        client = GMGNClient(api_key="test-key")
        calls = []

        def fake_get(path, params):
            calls.append(dict(params))
            side = params["type"]
            return {
                "data": {
                    "activities": [
                        {
                            "tx_hash": f"0x{side}-{i}",
                            "event_type": side,
                            "timestamp": 2_000 - i,
                        }
                        for i in range(params["limit"])
                    ],
                    "next": f"next-{side}",
                }
            }

        with TemporaryDirectory() as directory, patch.object(client, "_get", side_effect=fake_get):
            cache = Path(directory) / "wallet.json"
            first = client.fetch_wallet_activities("0xwallet", limit=3, cache_path=cache)
            second = client.fetch_wallet_activities("0xwallet", limit=3, cache_path=cache)

        self.assertEqual(len(calls), 2)
        self.assertFalse(first["data"]["cache_hit"])
        self.assertTrue(second["data"]["cache_hit"])

    def test_expired_complete_cache_refreshes_only_first_page_per_side(self) -> None:
        client = GMGNClient(api_key="test-key")
        calls = []

        def fake_get(path, params):
            calls.append(dict(params))
            side = params["type"]
            return {
                "data": {
                    "activities": [
                        {
                            "tx_hash": f"0x{side}-{i}",
                            "event_type": side,
                            "timestamp": 2_000 - i,
                        }
                        for i in range(params["limit"])
                    ],
                    "next": f"next-{side}",
                }
            }

        with TemporaryDirectory() as directory, patch.object(client, "_get", side_effect=fake_get):
            cache = Path(directory) / "wallet.json"
            client.fetch_wallet_activities("0xwallet", limit=60, cache_path=cache)
            refreshed = client.fetch_wallet_activities(
                "0xwallet", limit=60, cache_path=cache, cache_ttl_seconds=-1
            )

        self.assertEqual(len(calls), 4)
        self.assertEqual(refreshed["data"]["fetch_mode"], "incremental_buy_sell_refresh")
        self.assertEqual(refreshed["data"]["refresh_rows_fetched"], 100)
        self.assertEqual(len(refreshed["data"]["activities"]), 60)


if __name__ == "__main__":
    unittest.main()

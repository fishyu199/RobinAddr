"""Normalize GMGN Robinhood Chain wallet activities into spot trades."""

from __future__ import annotations

import gzip
import http.client
import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlencode, urlsplit

from .decimal_utils import ZERO, decimal_value
from .models import Side, Trade


DEFAULT_BASE_URL = "https://openapi.gmgn.ai"


class _RequestRateLimiter:
    """Process-wide evenly-spaced limiter for the threaded GMGN worker."""

    def __init__(self, requests_per_second: float) -> None:
        self.interval = 1.0 / max(requests_per_second, 1.0)
        self._lock = threading.Lock()
        self._next_slot = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_slot)
            self._next_slot = slot + self.interval
        delay = slot - now
        if delay > 0:
            time.sleep(delay)


# Leave a small safety margin below the user's 50-weight/s GMGN plan.
_GLOBAL_RATE_LIMITER = _RequestRateLimiter(float(os.getenv("GMGN_RATE_LIMIT_RPS", "48")))


def _configured_api_key() -> str | None:
    if os.environ.get("GMGN_API_KEY"):
        return os.environ["GMGN_API_KEY"]
    config_path = Path.home() / ".config" / "gmgn" / ".env"
    try:
        for raw_line in config_path.read_text(encoding="utf-8").splitlines():
            key, separator, value = raw_line.partition("=")
            if separator and key.strip() == "GMGN_API_KEY":
                return value.strip().strip("\"").strip("'") or None
    except OSError:
        pass
    return None


def _activities_from_payload(payload: Any) -> Sequence[Mapping[str, Any]]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, Mapping):
        raise ValueError("GMGN payload must be an object or an activity list")
    data = payload.get("data", payload)
    if isinstance(data, list):
        return data
    if isinstance(data, Mapping):
        activities = data.get("activities", data.get("list", []))
        if isinstance(activities, list):
            return activities
    raise ValueError("cannot find GMGN activities in payload")


def _optional_decimal(value: Any, *, field: str) -> Decimal | None:
    if value in (None, ""):
        return None
    return decimal_value(value, field=field)


def normalize_gmgn_payload(payload: Any) -> tuple[list[Trade], dict[str, Any]]:
    activities = _activities_from_payload(payload)
    payload_data = payload.get("data", {}) if isinstance(payload, Mapping) else {}
    trades: list[Trade] = []
    skipped_by_reason: dict[str, int] = {}

    def skip(reason: str) -> None:
        skipped_by_reason[reason] = skipped_by_reason.get(reason, 0) + 1

    for index, activity in enumerate(activities):
        if not isinstance(activity, Mapping):
            skip("not_an_object")
            continue
        event_type = str(
            activity.get("event_type") or activity.get("type") or activity.get("side") or ""
        ).lower()
        if event_type not in {Side.BUY.value, Side.SELL.value}:
            skip(f"unsupported_event:{event_type or 'missing'}")
            continue
        token = activity.get("token") if isinstance(activity.get("token"), Mapping) else {}
        if not token and isinstance(activity.get("base_token"), Mapping):
            token = activity["base_token"]
        token_address = str(
            token.get("address")
            or activity.get("token_address")
            or activity.get("base_address")
            or ""
        )
        if not token_address:
            skip("missing_token_address")
            continue
        try:
            quantity = decimal_value(
                activity.get("token_amount", activity.get("base_amount")),
                field="token_amount",
            )
            price = decimal_value(activity.get("price_usd"), field="price_usd", default=ZERO)
            quote = decimal_value(
                activity.get("cost_usd", activity.get("amount_usd")),
                field="cost_usd",
                default=ZERO,
            )
            if quote <= ZERO and price > ZERO:
                quote = quantity * price
            if price <= ZERO and quantity > ZERO and quote > ZERO:
                price = quote / quantity
            timestamp = int(activity.get("timestamp") or activity.get("time") or 0)
            timestamp_ms = timestamp * 1000 if timestamp < 1_000_000_000_000 else timestamp
            gas = decimal_value(activity.get("gas_usd"), field="gas_usd", default=ZERO)
            dex = decimal_value(activity.get("dex_usd"), field="dex_usd", default=ZERO)
            sequence_raw = activity.get("event_index", activity.get("log_index"))
            sequence = int(sequence_raw) if sequence_raw not in (None, "") else None
            trades.append(
                Trade.create(
                    tx_hash=str(
                        activity.get("tx_hash")
                        or activity.get("transaction_hash")
                        or activity.get("hash")
                        or ""
                    ),
                    timestamp_ms=timestamp_ms,
                    token_address=token_address,
                    token_symbol=str(token.get("symbol") or activity.get("symbol") or ""),
                    side=event_type,
                    token_amount=quantity,
                    quote_amount_usd=quote,
                    price_usd=price,
                    reported_buy_cost_usd=_optional_decimal(
                        activity.get("buy_cost_usd"), field="buy_cost_usd"
                    ),
                    observed_fee_usd=gas + dex,
                    sequence=sequence,
                    metadata={
                        "source_index": index,
                        "chain": activity.get("chain"),
                        "launchpad_platform": (
                            activity.get("launchpad_platform") or activity.get("launchpad") or ""
                        ),
                    },
                )
            )
        except (TypeError, ValueError, ArithmeticError):
            skip("invalid_trade_fields")

    quality = {
        "source": "gmgn_wallet_activity",
        "input_activity_count": len(activities),
        "normalized_trade_count": len(trades),
        "skipped_activity_count": len(activities) - len(trades),
        "skipped_by_reason": skipped_by_reason,
    }
    if isinstance(payload_data, Mapping):
        for key in (
            "fetch_mode",
            "cache_hit",
            "network_request_count",
            "network_elapsed_seconds",
            "configured_rate_limit_rps",
            "buy_rows_fetched",
            "sell_rows_fetched",
            "refresh_rows_fetched",
        ):
            if key in payload_data:
                quality[key] = payload_data[key]
    return trades, quality


def infer_wallet_address(payload: Any) -> str:
    """Return the first wallet address present in a GMGN activity payload."""
    for activity in _activities_from_payload(payload):
        if not isinstance(activity, Mapping):
            continue
        wallet = activity.get("wallet") or activity.get("maker") or activity.get("wallet_address")
        if wallet:
            return str(wallet)
    return ""


class GMGNClient:
    """Minimal read-only client for GMGN's Robinhood wallet activity endpoint."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 30,
        client_id: str | None = None,
    ) -> None:
        self.api_key = api_key or _configured_api_key()
        if not self.api_key:
            raise ValueError("GMGN_API_KEY is required for live wallet fetching")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._initial_client_id = client_id
        parsed = urlsplit(self.base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("GMGN base_url must be an https URL")
        self._host = parsed.hostname
        self._port = parsed.port
        self._base_path = parsed.path.rstrip("/")
        self._thread_local = threading.local()
        self._client_id_lock = threading.Lock()
        self._metrics_lock = threading.Lock()
        self._request_count = 0
        self._request_elapsed_seconds = 0.0

    def _record_request(self, elapsed_seconds: float) -> None:
        with self._metrics_lock:
            self._request_count += 1
            self._request_elapsed_seconds += elapsed_seconds

    def request_metrics(self) -> tuple[int, float]:
        with self._metrics_lock:
            return self._request_count, self._request_elapsed_seconds

    def _next_client_id(self) -> str:
        with self._client_id_lock:
            if self._initial_client_id:
                client_id = self._initial_client_id
                self._initial_client_id = None
                return client_id
        return str(uuid.uuid4())

    def _connection(self) -> http.client.HTTPSConnection:
        connection = getattr(self._thread_local, "connection", None)
        if connection is None:
            connection = http.client.HTTPSConnection(
                self._host,
                port=self._port,
                timeout=self.timeout_seconds,
            )
            self._thread_local.connection = connection
        return connection

    def _close_connection(self) -> None:
        connection = getattr(self._thread_local, "connection", None)
        if connection is not None:
            try:
                connection.close()
            finally:
                self._thread_local.connection = None

    def _request(
        self,
        method: str,
        path: str,
        params: Mapping[str, Any],
        body: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        """Request JSON through a thread-local keep-alive connection with gzip."""
        current_params = dict(params)
        payload: Any = None
        last_error: BaseException | None = None
        for attempt in range(5):
            target = f"{self._base_path}{path}?{urlencode(current_params, doseq=True)}"
            try:
                _GLOBAL_RATE_LIMITER.acquire()
                connection = self._connection()
                request_started = time.monotonic()
                encoded_body = (
                    json.dumps(body, ensure_ascii=False, separators=(",", ":"))
                    if body is not None
                    else None
                )
                connection.request(
                    method,
                    target,
                    body=encoded_body,
                    headers={
                        "Accept": "application/json",
                        "Accept-Encoding": "gzip",
                        "Content-Type": "application/json",
                        "Connection": "keep-alive",
                        "User-Agent": "gmgn-cli/1.6.6",
                        "X-APIKEY": self.api_key,
                    },
                )
                response = connection.getresponse()
                raw = response.read()
                self._record_request(time.monotonic() - request_started)
                if response.getheader("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                try:
                    response_payload = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    response_payload = {}
                if 200 <= response.status < 300:
                    payload = response_payload
                    break
                if response.status == 429 and attempt < 4:
                    reset_raw = response.getheader("X-RateLimit-Reset") or response_payload.get("reset_at")
                    try:
                        reset_at = int(reset_raw)
                    except (TypeError, ValueError):
                        reset_at = 0
                    wait_seconds = max(0.0, reset_at - time.time()) + 0.1
                    time.sleep(wait_seconds if reset_at and wait_seconds <= 5.0 else min(2**attempt, 5))
                    current_params["timestamp"] = int(time.time())
                    current_params["client_id"] = self._next_client_id()
                    continue
                message = (
                    response_payload.get("message")
                    or response_payload.get("error")
                    or response.reason
                )
                raise RuntimeError(f"GMGN request failed: HTTP {response.status}: {message}")
            except RuntimeError:
                raise
            except (TimeoutError, ConnectionError, OSError, http.client.HTTPException) as exc:
                last_error = exc
                self._close_connection()
                if attempt >= 4:
                    break
                time.sleep(min(0.5 * (2**attempt), 4.0))
                current_params["timestamp"] = int(time.time())
                current_params["client_id"] = self._next_client_id()
        if payload is None:
            raise RuntimeError(f"GMGN request failed after transient-error retries: {last_error}") from last_error
        if not isinstance(payload, Mapping):
            raise RuntimeError("GMGN returned a non-object response")
        if payload.get("code") not in (None, 0, "0"):
            raise RuntimeError(f"GMGN error: {payload.get('message') or payload.get('msg') or payload}")
        return payload

    def _get(self, path: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._request("GET", path, params)

    def _post(
        self,
        path: str,
        params: Mapping[str, Any],
        body: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return self._request("POST", path, params, body)

    def fetch_wallet_activities(
        self,
        wallet_address: str,
        *,
        limit: int = 5_000,
        cache_path: str | Path | None = None,
        cache_ttl_seconds: int = 300,
        resume_ttl_seconds: int = 86_400,
    ) -> dict[str, Any]:
        """Fetch exact latest trades; refresh completed caches from their newest overlap."""
        if limit <= 0:
            raise ValueError("limit must be positive")
        request_count_start, request_elapsed_start = self.request_metrics()

        def request_diagnostics() -> dict[str, Any]:
            request_count, request_elapsed = self.request_metrics()
            return {
                "network_request_count": request_count - request_count_start,
                "network_elapsed_seconds": round(request_elapsed - request_elapsed_start, 3),
                "configured_rate_limit_rps": float(os.getenv("GMGN_RATE_LIMIT_RPS", "48")),
            }
        cache_file = Path(cache_path) if cache_path else None
        now = time.time()
        streams: dict[str, dict[str, Any]] = {
            "buy": {"activities": [], "cursor": None, "exhausted": False},
            "sell": {"activities": [], "cursor": None, "exhausted": False},
        }
        refresh_complete_cache = False

        def activity_timestamp(item: Mapping[str, Any]) -> int:
            try:
                return int(item.get("timestamp") or item.get("time") or 0)
            except (TypeError, ValueError):
                return 0

        def activity_key(item: Mapping[str, Any]) -> tuple[Any, ...]:
            token = item.get("token") if isinstance(item.get("token"), Mapping) else {}
            return (
                item.get("tx_hash") or item.get("transaction_hash") or item.get("hash"),
                item.get("event_index", item.get("log_index")),
                item.get("event_type") or item.get("type") or item.get("side"),
                token.get("address") or item.get("token_address") or item.get("base_address"),
                item.get("token_amount", item.get("base_amount")),
                activity_timestamp(item),
            )

        def merged_activities() -> list[Mapping[str, Any]]:
            seen: set[tuple[Any, ...]] = set()
            merged: list[Mapping[str, Any]] = []
            for side in ("buy", "sell"):
                for item in streams[side]["activities"]:
                    if not isinstance(item, Mapping):
                        continue
                    key = activity_key(item)
                    if key in seen:
                        continue
                    seen.add(key)
                    merged.append(item)
            merged.sort(
                key=lambda item: (
                    activity_timestamp(item),
                    int(item.get("event_index") or item.get("log_index") or -1),
                ),
                reverse=True,
            )
            return merged

        if cache_file and cache_file.exists():
            try:
                cached = json.loads(cache_file.read_text(encoding="utf-8"))
                cache_age = now - float(cached.get("saved_at", 0))
                cache_matches = (
                    str(cached.get("wallet_address", "")).lower() == wallet_address.lower()
                    and int(cached.get("limit", 0)) == limit
                    and isinstance(cached.get("activities"), list)
                )
                if cache_matches and cached.get("complete") and cache_age <= cache_ttl_seconds:
                    return {
                        "code": 0,
                        "data": {
                            "activities": cached["activities"][:limit],
                            "next": cached.get("cursor"),
                            "cache_hit": True,
                            "fetch_mode": cached.get("fetch_mode", "cached"),
                            **request_diagnostics(),
                        },
                    }
                cached_streams = cached.get("streams")
                if cache_matches and cached.get("complete") and isinstance(cached_streams, Mapping):
                    cached_states: dict[str, dict[str, Any]] = {}
                    for side in ("buy", "sell"):
                        state = cached_streams.get(side)
                        if not isinstance(state, Mapping):
                            cached_states = {}
                            break
                        cached_states[side] = {
                            "activities": [
                                item for item in state.get("activities", []) if isinstance(item, Mapping)
                            ],
                            "cursor": state.get("cursor"),
                            "exhausted": bool(state.get("exhausted")),
                        }
                    if len(cached_states) == 2:
                        streams.update(cached_states)
                        refresh_complete_cache = True
                if (
                    cache_matches
                    and not cached.get("complete")
                    and cache_age <= resume_ttl_seconds
                    and isinstance(cached_streams, Mapping)
                ):
                    for side in ("buy", "sell"):
                        state = cached_streams.get(side)
                        if not isinstance(state, Mapping):
                            continue
                        streams[side] = {
                            "activities": [
                                item for item in state.get("activities", []) if isinstance(item, Mapping)
                            ],
                            "cursor": state.get("cursor"),
                            "exhausted": bool(state.get("exhausted")),
                        }
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                pass

        def save_cache(*, complete: bool, fetch_mode: str = "parallel_buy_sell_keepalive_gzip") -> None:
            if not cache_file:
                return
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = cache_file.with_suffix(cache_file.suffix + ".tmp")
            merged = merged_activities()
            temporary.write_text(
                json.dumps(
                    {
                        "wallet_address": wallet_address.lower(),
                        "limit": limit,
                        "saved_at": time.time(),
                        "complete": complete,
                        "fetch_mode": fetch_mode,
                        "cursor": None,
                        "activities": merged[:limit] if complete else merged,
                        "streams": streams,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            temporary.replace(cache_file)

        def request_page(
            side: str, cursor: Any = None
        ) -> tuple[str, list[Mapping[str, Any]], Any, bool]:
            params: dict[str, Any] = {
                "chain": "robinhood",
                "wallet_address": wallet_address,
                "type": side,
                "limit": 50,
                "timestamp": int(time.time()),
                "client_id": self._next_client_id(),
            }
            if cursor not in (None, ""):
                params["cursor"] = cursor
            page = self._get("/v1/user/wallet_activity", params)
            data = page.get("data", page)
            batch = data.get("activities") if isinstance(data, Mapping) else []
            valid_batch = [item for item in batch if isinstance(item, Mapping)] if isinstance(batch, list) else []
            next_cursor = data.get("next") if isinstance(data, Mapping) else None
            exhausted = not valid_batch or not next_cursor or next_cursor == cursor
            return side, valid_batch, next_cursor, exhausted

        def fetch_page(side: str) -> tuple[str, list[Mapping[str, Any]], Any, bool]:
            return request_page(side, streams[side]["cursor"])

        if refresh_complete_cache:
            def refresh_side(side: str) -> tuple[str, list[Mapping[str, Any]], Any, bool, int]:
                previous = streams[side]
                previous_rows = previous["activities"]
                previous_keys = {activity_key(item) for item in previous_rows}
                fresh_rows: list[Mapping[str, Any]] = []
                cursor: Any = None
                exhausted = False
                fetched_rows = 0

                while True:
                    _, batch, next_cursor, exhausted = request_page(side, cursor)
                    fetched_rows += len(batch)
                    fresh_rows.extend(batch)
                    if previous_keys.intersection(activity_key(item) for item in batch):
                        break
                    if exhausted or len(fresh_rows) >= limit:
                        break
                    cursor = next_cursor

                combined: list[Mapping[str, Any]] = []
                seen: set[tuple[Any, ...]] = set()
                for item in fresh_rows + previous_rows:
                    key = activity_key(item)
                    if key in seen:
                        continue
                    seen.add(key)
                    combined.append(item)
                combined.sort(
                    key=lambda item: (
                        activity_timestamp(item),
                        int(item.get("event_index") or item.get("log_index") or -1),
                    ),
                    reverse=True,
                )
                return side, combined[:limit], next_cursor, exhausted, fetched_rows

            refreshed_rows = 0
            with ThreadPoolExecutor(max_workers=2, thread_name_prefix="gmgn-refresh") as executor:
                futures = [executor.submit(refresh_side, side) for side in ("buy", "sell")]
                for future in futures:
                    side, rows, next_cursor, exhausted, fetched = future.result()
                    streams[side] = {
                        "activities": rows,
                        "cursor": next_cursor,
                        "exhausted": exhausted,
                    }
                    refreshed_rows += fetched

            activities = merged_activities()[:limit]
            save_cache(complete=True, fetch_mode="incremental_buy_sell_refresh")
            return {
                "code": 0,
                "data": {
                    "activities": activities,
                    "next": None,
                    "cache_hit": False,
                    "fetch_mode": "incremental_buy_sell_refresh",
                    "refresh_rows_fetched": refreshed_rows,
                    "buy_rows_cached": len(streams["buy"]["activities"]),
                    "sell_rows_cached": len(streams["sell"]["activities"]),
                    **request_diagnostics(),
                },
            }

        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="gmgn-activity") as executor:
            while True:
                merged = merged_activities()
                if len(merged) < limit:
                    needed = [side for side in ("buy", "sell") if not streams[side]["exhausted"]]
                else:
                    cutoff = activity_timestamp(merged[limit - 1])
                    needed = []
                    for side in ("buy", "sell"):
                        state = streams[side]
                        if state["exhausted"]:
                            continue
                        side_rows = state["activities"]
                        if not side_rows or min(activity_timestamp(item) for item in side_rows) >= cutoff:
                            needed.append(side)
                if not needed:
                    break

                futures = [executor.submit(fetch_page, side) for side in needed]
                for future in futures:
                    side, batch, next_cursor, exhausted = future.result()
                    streams[side]["activities"].extend(batch)
                    streams[side]["cursor"] = next_cursor
                    streams[side]["exhausted"] = exhausted
                save_cache(complete=False)

        activities = merged_activities()[:limit]
        save_cache(complete=True)
        return {
            "code": 0,
            "data": {
                "activities": activities,
                "next": None,
                "cache_hit": False,
                "fetch_mode": "parallel_buy_sell_keepalive_gzip",
                "buy_rows_fetched": len(streams["buy"]["activities"]),
                "sell_rows_fetched": len(streams["sell"]["activities"]),
                **request_diagnostics(),
            },
        }

    def fetch_wallet_stats(self, wallet_address: str, *, period: str = "30d") -> dict[str, Any]:
        if period not in {"7d", "30d"}:
            raise ValueError("period must be '7d' or '30d'")
        payload = self._get(
            "/v1/user/wallet_stats",
            {
                "chain": "robinhood",
                "wallet_address": wallet_address,
                "period": period,
                "timestamp": int(time.time()),
                "client_id": self._next_client_id(),
            },
        )
        data = payload.get("data", payload)
        return dict(data) if isinstance(data, Mapping) else {}

    def fetch_wallet_profits(
        self,
        wallet_addresses: Sequence[str],
        *,
        period: str = "7d",
    ) -> list[dict[str, Any]]:
        """Fetch GMGN PnL rows for up to 100 wallets in one weighted request."""
        if period not in {"1d", "7d", "30d", "all"}:
            raise ValueError("period must be one of: 1d, 7d, 30d, all")
        addresses = list(dict.fromkeys(address.lower() for address in wallet_addresses if address))
        if not 1 <= len(addresses) <= 100:
            raise ValueError("wallet_addresses must contain between 1 and 100 addresses")
        payload = self._post(
            "/v1/user/wallet_profits",
            {
                "timestamp": int(time.time()),
                "client_id": self._next_client_id(),
            },
            {
                "chain": "robinhood",
                "period": period,
                "wallet_addresses": addresses,
            },
        )
        data = payload.get("data", payload)
        rows = data.get("list") if isinstance(data, Mapping) else None
        return [dict(row) for row in rows or [] if isinstance(row, Mapping)]

    def fetch_tracked_wallet_activity(
        self,
        *,
        wallet_type: str = "smart_degen",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch a public Robinhood Smart Money or KOL activity feed.

        GMGN currently caps these feeds at 100 records and exposes no cursor.
        They are candidate sources; wallet PnL must be fetched and ranked
        separately.
        """
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        endpoint = {
            "smart_degen": "/v1/user/smartmoney",
            "kol": "/v1/user/kol",
            "renowned": "/v1/user/kol",
        }.get(wallet_type)
        if endpoint is None:
            raise ValueError("wallet_type must be one of: smart_degen, kol, renowned")
        payload = self._get(
            endpoint,
            {
                "chain": "robinhood",
                "limit": limit,
                "timestamp": int(time.time()),
                "client_id": self._next_client_id(),
            },
        )
        rows = payload.get("list")
        if rows is None and isinstance(payload.get("data"), Mapping):
            rows = payload["data"].get("list")
        return [dict(row) for row in rows or [] if isinstance(row, Mapping)]

    def fetch_smart_money_activity(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Backward-compatible Smart Money feed helper."""
        return self.fetch_tracked_wallet_activity(wallet_type="smart_degen", limit=limit)

    def fetch_realtime_wallet_activity(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Fetch the fixed Robinhood realtime activity source used for discovery.

        The API exposes only its latest activity window, capped at 100 rows and
        without cursor pagination. Callers must persist and deduplicate wallets.
        """
        return self.fetch_tracked_wallet_activity(wallet_type="smart_degen", limit=limit)

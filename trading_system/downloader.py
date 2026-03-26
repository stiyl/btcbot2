from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import requests

EXCHANGE_URL = "https://api.exchange.coinbase.com/products/{product_id}"
VALID_GRANULARITIES = {60, 300, 900, 3600, 21600, 86400}
DEFAULT_CACHE_DIR = Path("data_cache")
DEFAULT_TIMEOUT = 30


def _iso_utc(ts_value: int) -> str:
    return pd.Timestamp.fromtimestamp(ts_value, tz="UTC").isoformat()


def _product_url(product_id: str, suffix: str) -> str:
    product = str(product_id).strip().upper()
    return f"{EXCHANGE_URL.format(product_id=product)}{suffix}"


def fetch_coinbase_candles(product_id: str, granularity: int, start_ts: int, end_ts: int, timeout: int = DEFAULT_TIMEOUT) -> pd.DataFrame:
    if granularity not in VALID_GRANULARITIES:
        raise ValueError(f"Invalid Coinbase granularity: {granularity}. Use one of {sorted(VALID_GRANULARITIES)}")

    params = {
        "start": _iso_utc(start_ts),
        "end": _iso_utc(end_ts),
        "granularity": granularity,
    }
    response = requests.get(_product_url(product_id, "/candles"), params=params, timeout=timeout)
    response.raise_for_status()
    data = response.json()

    if not isinstance(data, list) or not data:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    frame = pd.DataFrame(data, columns=["timestamp", "low", "high", "open", "close", "volume"])
    frame = frame[["timestamp", "open", "high", "low", "close", "volume"]]
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="s", utc=True, errors="coerce")
    for col in ["open", "high", "low", "close", "volume"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close"]).copy()
    frame["volume"] = frame["volume"].fillna(0.0)
    return frame.sort_values("timestamp").reset_index(drop=True)


def fetch_coinbase_ticker(product_id: str, timeout: int = DEFAULT_TIMEOUT) -> dict[str, float | str | None]:
    response = requests.get(_product_url(product_id, "/ticker"), timeout=timeout)
    response.raise_for_status()
    payload = response.json() or {}
    return {
        "product_id": str(product_id).strip().upper(),
        "price": _safe_float(payload.get("price")),
        "bid": _safe_float(payload.get("bid")),
        "ask": _safe_float(payload.get("ask")),
        "volume": _safe_float(payload.get("volume")),
        "trade_id": payload.get("trade_id"),
        "time": payload.get("time"),
    }


def fetch_coinbase_stats(product_id: str, timeout: int = DEFAULT_TIMEOUT) -> dict[str, float | str | None]:
    response = requests.get(_product_url(product_id, "/stats"), timeout=timeout)
    response.raise_for_status()
    payload = response.json() or {}
    return {
        "product_id": str(product_id).strip().upper(),
        "open_24h": _safe_float(payload.get("open")),
        "high_24h": _safe_float(payload.get("high")),
        "low_24h": _safe_float(payload.get("low")),
        "volume_24h": _safe_float(payload.get("volume")),
        "volume_usd_24h": _safe_float(payload.get("volume_30day")),
        "last": _safe_float(payload.get("last")),
    }


def fetch_coinbase_live_snapshot(product_id: str, timeout: int = DEFAULT_TIMEOUT) -> dict[str, float | str | None]:
    ticker = fetch_coinbase_ticker(product_id=product_id, timeout=timeout)
    stats = fetch_coinbase_stats(product_id=product_id, timeout=timeout)
    price = _coalesce_float(ticker.get("price"), stats.get("last"))
    open_24h = _safe_float(stats.get("open_24h"))
    pct_change_24h = None
    if price is not None and open_24h not in (None, 0):
        pct_change_24h = ((price / open_24h) - 1.0) * 100.0
    return {
        **ticker,
        **stats,
        "price": price,
        "pct_change_24h": pct_change_24h,
        "spread": _spread_value(ticker.get("bid"), ticker.get("ask")),
    }


def default_download_path(product_id: str, granularity: int, days: int, cache_dir: str | Path = DEFAULT_CACHE_DIR) -> Path:
    safe_product = str(product_id).strip().upper().replace("-", "_").replace("/", "_")
    return Path(cache_dir) / f"{safe_product}_{granularity}s_{days}d.csv"


def download_coinbase_history(
    product_id: str = "BTC-USD",
    granularity: int = 3600,
    days: int = 180,
    out_path: str | Path | None = None,
    pause_seconds: float = 0.25,
) -> Path:
    if days <= 0:
        raise ValueError("days must be > 0")
    if granularity not in VALID_GRANULARITIES:
        raise ValueError(f"Invalid Coinbase granularity: {granularity}. Use one of {sorted(VALID_GRANULARITIES)}")

    now_ts = int(time.time())
    start_ts = now_ts - int(days * 86400)
    chunk_seconds = granularity * 300

    frames: list[pd.DataFrame] = []
    cursor = start_ts
    while cursor < now_ts:
        chunk_end = min(cursor + chunk_seconds, now_ts)
        frame = fetch_coinbase_candles(product_id, granularity, cursor, chunk_end)
        if not frame.empty:
            frames.append(frame)
        cursor = chunk_end
        if cursor < now_ts and pause_seconds > 0:
            time.sleep(pause_seconds)

    if not frames:
        raise RuntimeError(f"No candles returned from Coinbase for {product_id}.")

    candles_df = pd.concat(frames, ignore_index=True)
    candles_df = candles_df.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last").reset_index(drop=True)

    final_path = Path(out_path) if out_path is not None else default_download_path(product_id, granularity, days)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    candles_df.to_csv(final_path, index=False)
    return final_path


def _safe_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coalesce_float(*values) -> float | None:
    for value in values:
        safe = _safe_float(value)
        if safe is not None:
            return safe
    return None


def _spread_value(bid, ask) -> float | None:
    bid_v = _safe_float(bid)
    ask_v = _safe_float(ask)
    if bid_v is None or ask_v is None:
        return None
    return max(0.0, ask_v - bid_v)

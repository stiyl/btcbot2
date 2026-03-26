from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import requests

EXCHANGE_URL = "https://api.exchange.coinbase.com/products/{product_id}/candles"
VALID_GRANULARITIES = {60, 300, 900, 3600, 21600, 86400}


def _iso_utc(ts_value: int) -> str:
    return pd.Timestamp.fromtimestamp(ts_value, tz="UTC").isoformat()


def fetch_coinbase_candles(product_id: str, granularity: int, start_ts: int, end_ts: int, timeout: int = 30) -> pd.DataFrame:
    if granularity not in VALID_GRANULARITIES:
        raise ValueError(f"Invalid Coinbase granularity: {granularity}. Use one of {sorted(VALID_GRANULARITIES)}")

    url = EXCHANGE_URL.format(product_id=product_id)
    params = {
        "start": _iso_utc(start_ts),
        "end": _iso_utc(end_ts),
        "granularity": granularity,
    }
    response = requests.get(url, params=params, timeout=timeout)
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

    if out_path is None:
        safe_product = product_id.replace("-", "_").replace("/", "_")
        out_path = Path(f"{safe_product}_{granularity}s_{days}d.csv")
    else:
        out_path = Path(out_path)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    candles_df.to_csv(out_path, index=False)
    return out_path

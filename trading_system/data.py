from __future__ import annotations

from pathlib import Path
import pandas as pd


REQUIRED_COLUMNS = ['timestamp', 'open', 'high', 'low', 'close', 'volume']

COLUMN_ALIASES = {
    'date': 'timestamp',
    'datetime': 'timestamp',
    'time': 'timestamp',
    'timestamp utc': 'timestamp',
    'open time': 'timestamp',
    'close time': 'timestamp',
    'o': 'open',
    'h': 'high',
    'l': 'low',
    'c': 'close',
    'v': 'volume',
    'vol': 'volume',
    'openprice': 'open',
    'highprice': 'high',
    'lowprice': 'low',
    'closeprice': 'close',
    'tradecount': 'trade_count',
}


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    frame = df.copy()
    normalized = {}
    for col in frame.columns:
        key = str(col).strip().lower().replace('_', ' ')
        key = ' '.join(key.split())
        normalized[col] = COLUMN_ALIASES.get(key, key.replace(' ', '_'))
    return frame.rename(columns=normalized)


def _maybe_promote_unix_timestamp(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors='coerce')
    if numeric.notna().mean() < 0.8:
        return pd.to_datetime(series, utc=True, errors='coerce')

    median_value = numeric.dropna().median()
    if pd.isna(median_value):
        return pd.to_datetime(series, utc=True, errors='coerce')
    if median_value > 1e14:
        return pd.to_datetime(numeric, unit='ns', utc=True, errors='coerce')
    if median_value > 1e11:
        return pd.to_datetime(numeric, unit='ms', utc=True, errors='coerce')
    if median_value > 1e9:
        return pd.to_datetime(numeric, unit='s', utc=True, errors='coerce')
    return pd.to_datetime(series, utc=True, errors='coerce')


def ensure_ohlcv_schema(df: pd.DataFrame) -> pd.DataFrame:
    frame = _normalize_columns(df)

    missing = [col for col in REQUIRED_COLUMNS if col not in frame.columns]
    if missing:
        raise ValueError(
            f"Missing required OHLCV columns: {missing}. "
            f"Found columns: {list(frame.columns)}"
        )

    frame['timestamp'] = _maybe_promote_unix_timestamp(frame['timestamp'])
    frame = frame.dropna(subset=['timestamp']).copy()

    for col in ['open', 'high', 'low', 'close', 'volume']:
        frame[col] = pd.to_numeric(frame[col], errors='coerce')
    frame = frame.dropna(subset=['open', 'high', 'low', 'close']).copy()
    frame['volume'] = frame['volume'].fillna(0.0)

    frame = frame.sort_values('timestamp').drop_duplicates(subset=['timestamp'], keep='last')
    frame = frame.reset_index(drop=True)
    return frame[REQUIRED_COLUMNS].copy()



def load_ohlcv_csv(path: str | Path) -> pd.DataFrame:
    return ensure_ohlcv_schema(pd.read_csv(Path(path)))

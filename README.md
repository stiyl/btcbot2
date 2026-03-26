# Crypto Trading Refactor

This package turns the original monolithic scanner into a cleaner research project with separate modules for data loading, indicators, strategy logic, backtesting, dashboarding, and now built-in historical data download support.

## What changed

- **Cleaner modular architecture**
  - `trading_system/config.py`: typed settings
  - `trading_system/data.py`: OHLCV loading and schema normalization
  - `trading_system/downloader.py`: Coinbase candle downloader
  - `trading_system/indicators.py`: reusable indicator math
  - `trading_system/strategy.py`: improved signal model
  - `trading_system/backtest.py`: fast backtest engine
  - `trading_system/dashboard.py`: web UI
- **Strategy edge improvements**
  - multi-factor scoring instead of one-off triggers
  - trend alignment with fast / slow / long EMAs
  - breakout confirmation with Donchian channels
  - volatility filter using ATR percent
  - volume confirmation using rolling z-score
  - time stop + ATR stop + trailing stop
- **Faster research loop**
  - vectorized feature engineering in pandas / numpy
  - only the stateful execution step loops row-by-row
- **Easier first run**
  - no CSV required anymore
  - CLI can download Coinbase data automatically
  - dashboard can download candles directly from the sidebar
  - loader now accepts more common OHLCV column names and unix timestamps

## Quick start

```bash
pip install -r requirements.txt
python run_backtest.py --download BTC-USD --days 180 --granularity 3600 --export-trades trades.csv --export-equity equity.csv
streamlit run run_dashboard.py
```

## Use your own CSV

```bash
python run_backtest.py my_data.csv
```

Expected columns after normalization:

- `timestamp`
- `open`
- `high`
- `low`
- `close`
- `volume`

Common aliases like `time`, `datetime`, `date`, `o`, `h`, `l`, `c`, `v`, and unix timestamps are normalized automatically.

## Coinbase download examples

```bash
python run_backtest.py --download BTC-USD --days 180 --granularity 3600
python run_backtest.py --download ETH-USD --days 90 --granularity 900
```

Supported granularities:

- `60`
- `300`
- `900`
- `3600`
- `21600`
- `86400`

## Notes

This is a refactor-and-research package, not a drop-in replacement for every function in the original `btc1.py`. The original file mixes live Coinbase connectivity, websocket state, paper accounting, exports, and terminal UI in one file. This package separates those concerns so you can iterate faster and test strategy ideas safely.

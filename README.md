# Crypto Trading Refactor

This package turns the original monolithic scanner into a cleaner research project with separate modules for data loading, indicators, strategy logic, backtesting, live market snapshots, and a Streamlit dashboard.

## What changed

- **Cleaner modular architecture**
  - `trading_system/config.py`: typed settings
  - `trading_system/data.py`: OHLCV loading and schema normalization
  - `trading_system/indicators.py`: reusable indicator math
  - `trading_system/strategy.py`: improved signal model and alert snapshots
  - `trading_system/backtest.py`: fast backtest engine
  - `trading_system/downloader.py`: Coinbase history + live price snapshot helpers
  - `trading_system/dashboard.py`: web UI with auto-download, live prices, and signal alerts
- **Strategy edge improvements**
  - multi-factor scoring instead of one-off triggers
  - trend alignment with fast / slow / long EMAs
  - breakout confirmation with Donchian channels
  - volatility filter using ATR percent
  - volume confirmation using rolling z-score
  - time stop + ATR stop + trailing stop
- **Dashboard upgrades**
  - auto-downloads BTC-USD history by default
  - live Coinbase price, spread, and 24h range cards
  - alert banner for BUY, SELL, WATCH, or HOLD based on the latest signal bar
  - optional auto-refresh for quasi real-time monitoring

## Quick start

```bash
pip install -r requirements.txt
python run_backtest.py --download BTC-USD --days 180 --granularity 3600 --export-trades trades.csv --export-equity equity.csv
python -m streamlit run run_dashboard.py
```

## Expected CSV columns

- `timestamp`
- `open`
- `high`
- `low`
- `close`
- `volume`

Common aliases like `time`, `datetime`, and `date` are normalized automatically.

## Notes

This is still a **research / paper-trading dashboard**. The live section only reads public Coinbase market data. It does **not** place trades or send exchange orders.

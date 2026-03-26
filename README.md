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
  - `trading_system/dashboard.py`: web UI with auto-download, live prices, signal alerts, and a session-based live paper trader
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
  - session-based live paper trader with simulated entries, exits, PnL, and a trade blotter
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

This is still a **research / paper-trading dashboard**. The live section only reads public Coinbase market data and places simulated paper trades inside the Streamlit session. It does **not** place real exchange orders or use real money.


## Always-on live paper bot

You can also run an always-on live paper trading bot that listens to Coinbase public WebSocket ticker data, rolls candles in real time, evaluates each newly closed bar, and maintains a persistent virtual account.

```bash
python run_live_paper_bot.py --product BTC-USD --granularity 3600 --days 30
```

What it does:
- downloads a seed history window from Coinbase
- subscribes to the public Coinbase Exchange ticker feed
- builds the active candle tick-by-tick
- evaluates the latest closed bar once per candle close
- manages a persistent paper account with stops, trailing stops, take-profit, and trade logging
- writes state and trade logs to `data_cache/`

Important:
- this is still paper only
- it does not send authenticated or real orders
- it needs the process to keep running on your machine or server

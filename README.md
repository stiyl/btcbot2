# BTCBot2 Refactor

This refactor turns the project into a cleaner research and monitoring app with three main parts:

- a modular backtest engine
- a live Coinbase paper-trading bot
- a deploy-ready Streamlit dashboard

## What is now included

### Architecture
- `trading_system/config.py` — typed config objects
- `trading_system/data.py` — OHLCV normalization and loading
- `trading_system/indicators.py` — EMA, RSI, ATR, z-score, Bollinger Bands
- `trading_system/strategy.py` — signal generation and latest-signal snapshot
- `trading_system/backtest.py` — historical simulation engine
- `trading_system/paper.py` — paper account, position management, stops, take profit, trailing stop
- `trading_system/storage.py` — persistent JSON/CSV state for dashboard and live paper trading
- `trading_system/downloader.py` — Coinbase history and live snapshot fetchers
- `trading_system/live_bot.py` — always-on websocket paper trader
- `trading_system/dashboard.py` — Streamlit UI

### UI upgrades
- cleaner dark dashboard layout
- deploy-friendly `app.py` entrypoint
- live Coinbase price cards
- strategy snapshot banner
- backtest metrics and charts
- persistent live paper trader inside Streamlit
- optional auto-refresh

### Paper-trading upgrades
- live mark-to-market updates
- ATR stop loss, take profit, and trailing stop logic
- persistent account state across app reruns
- persistent paper equity history and trade log
- reset controls from the sidebar

## Quick start

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Run a backtest

```bash
python run_backtest.py --download BTC-USD --days 180 --granularity 3600 --export-trades trades.csv --export-equity equity.csv
```

## Run the always-on live paper bot

```bash
python run_live_paper_bot.py --product BTC-USD --granularity 3600 --days 30
```

What it does:
- downloads a seed candle set from Coinbase
- subscribes to the Coinbase public websocket ticker
- rolls live candles in real time
- evaluates each newly closed bar
- updates a persistent paper account and trade log

## Streamlit deployment

This repo is ready for Streamlit Community Cloud.

1. Push the repo to GitHub.
2. Create a new Streamlit app.
3. Choose `app.py` as the main file.
4. Let Streamlit install from `requirements.txt`.

The app includes `.streamlit/config.toml` for theme defaults.

## Notes

- This project is paper trading only.
- No real exchange orders are sent.
- Coinbase public market data is used for history and live snapshots.
- Dashboard persistence writes to `data_cache/`.

## Recommended next upgrades

- Telegram or Discord alerts
- multi-asset watchlist view
- strategy parameter controls in the UI
- richer analytics like exposure, expectancy, and rolling drawdown
- optional exchange abstraction for future broker integrations


## Autonomous paper trading, stops, and alerts

This build adds:
- automatic paper-trade execution on each dashboard refresh when **Auto execute latest signal** is enabled
- ATR-based stop loss, take profit, trailing stop, and max holding bars controls in the Streamlit sidebar
- optional Discord and Telegram alerts for signal, entry, and exit events
- alert logging to `data_cache/alerts_log.jsonl`

Run the always-on bot locally:

```bash
python run_live_paper_bot.py --product BTC-USD --granularity 3600 --days 30 --alerts-enabled
```

Optional alert flags:

```bash
python run_live_paper_bot.py \
  --product BTC-USD \
  --alerts-enabled \
  --discord-webhook-url "YOUR_WEBHOOK" \
  --telegram-bot-token "YOUR_TOKEN" \
  --telegram-chat-id "YOUR_CHAT_ID"
```

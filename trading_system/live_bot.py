from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd
import websocket

from .config import BacktestConfig
from .data import ensure_ohlcv_schema
from .downloader import (
    DEFAULT_CACHE_DIR,
    VALID_GRANULARITIES,
    default_download_path,
    download_coinbase_history,
)
from .paper import (
    PaperAccount,
    PaperPosition,
    create_paper_account,
    paper_account_snapshot,
    process_live_price,
    process_paper_signal,
)
from .strategy import build_latest_signal_snapshot, compute_strategy_frame

WS_URL = "wss://ws-feed.exchange.coinbase.com"


def setup_logger(log_path: Path | None = None) -> logging.Logger:
    logger = logging.getLogger("live_paper_bot")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    return logger


def granularity_to_pandas_freq(granularity: int) -> str:
    if granularity == 60:
        return "1min"
    if granularity == 300:
        return "5min"
    if granularity == 900:
        return "15min"
    if granularity == 3600:
        return "1h"
    if granularity == 21600:
        return "6h"
    if granularity == 86400:
        return "1d"
    raise ValueError(f"Unsupported granularity {granularity}")


class LivePaperTrader:
    def __init__(
        self,
        product_id: str,
        granularity: int,
        days: int,
        cfg: BacktestConfig,
        state_path: Path,
        trades_csv: Path,
        candles_csv: Path | None = None,
        log_path: Path | None = None,
    ):
        self.product_id = str(product_id).strip().upper()
        self.granularity = int(granularity)
        self.days = int(days)
        self.cfg = cfg
        self.state_path = Path(state_path)
        self.trades_csv = Path(trades_csv)
        self.candles_csv = Path(candles_csv) if candles_csv else default_download_path(self.product_id, self.granularity, self.days)
        self.logger = setup_logger(log_path)
        self.df = self._load_seed_data()
        self.frame = compute_strategy_frame(self.df, self.cfg.strategy)
        self.account = self._load_or_create_account()
        self.current_candle: dict[str, Any] | None = None
        self.last_price: float | None = None
        self.last_signal_bar: str | None = self.account.last_signal_bar
        self.ws_app: websocket.WebSocketApp | None = None

    def _load_seed_data(self) -> pd.DataFrame:
        path = download_coinbase_history(
            product_id=self.product_id,
            granularity=self.granularity,
            days=self.days,
            out_path=self.candles_csv,
        )
        df = ensure_ohlcv_schema(pd.read_csv(path))
        self.logger.info("Loaded %s candles from %s", len(df), path)
        return df

    def _load_or_create_account(self) -> PaperAccount:
        if not self.state_path.exists():
            self.logger.info("Creating new paper account with $%.2f", self.cfg.starting_cash)
            return create_paper_account(self.cfg.starting_cash)
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            account = paper_account_from_dict(payload)
            self.logger.info("Loaded paper account from %s", self.state_path)
            return account
        except Exception as exc:
            self.logger.warning("Could not load existing state (%s). Starting fresh.", exc)
            return create_paper_account(self.cfg.starting_cash)

    def persist_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(paper_account_to_dict(self.account), indent=2), encoding="utf-8")
        if self.account.trades:
            self.trades_csv.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(self.account.trades).to_csv(self.trades_csv, index=False)
        self.df.tail(1000).to_csv(self.candles_csv, index=False)

    def _bucket_start(self, ts: pd.Timestamp) -> pd.Timestamp:
        secs = int(ts.timestamp())
        bucket = secs - (secs % self.granularity)
        return pd.Timestamp(bucket, unit="s", tz="UTC")

    def _start_candle(self, ts: pd.Timestamp, price: float, size: float) -> dict[str, Any]:
        return {
            "timestamp": self._bucket_start(ts),
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": max(0.0, size),
        }

    def _update_candle(self, price: float, size: float) -> None:
        if self.current_candle is None:
            return
        self.current_candle["high"] = max(float(self.current_candle["high"]), price)
        self.current_candle["low"] = min(float(self.current_candle["low"]), price)
        self.current_candle["close"] = price
        self.current_candle["volume"] = float(self.current_candle["volume"]) + max(0.0, size)

    def _close_current_candle(self) -> None:
        if self.current_candle is None:
            return
        candle_df = pd.DataFrame([self.current_candle])
        self.df = (
            pd.concat([self.df, candle_df], ignore_index=True)
            .sort_values("timestamp")
            .drop_duplicates(subset=["timestamp"], keep="last")
            .reset_index(drop=True)
        )
        self.frame = compute_strategy_frame(self.df, self.cfg.strategy)
        signal_row = self.frame.iloc[-1]
        close_price = float(signal_row["close"])
        pre_trade_count = len(self.account.trades)
        prev_position = self.account.position.side if self.account.position else "FLAT"
        process_paper_signal(self.account, signal_row, close_price, self.cfg)
        self.last_signal_bar = self.account.last_signal_bar
        latest = build_latest_signal_snapshot(self.frame, self.cfg.strategy)
        self.logger.info(
            "Closed candle %s | close=%.2f | signal=%s | score=%.2f | alert=%s",
            pd.to_datetime(signal_row['timestamp']).isoformat(),
            close_price,
            latest.get("signal"),
            float(latest.get("score") or 0.0),
            latest.get("alert_level"),
        )
        if len(self.account.trades) > pre_trade_count:
            trade = self.account.trades[-1]
            self.logger.info(
                "EXIT %s qty=%.6f entry=%.2f exit=%.2f pnl=%.2f reason=%s",
                trade["side"],
                float(trade["qty"]),
                float(trade["entry_price"]),
                float(trade["exit_price"]),
                float(trade["pnl"]),
                trade["exit_reason"],
            )
        new_position = self.account.position.side if self.account.position else "FLAT"
        if prev_position != new_position and self.account.position is not None:
            pos = self.account.position
            self.logger.info(
                "ENTRY %s qty=%.6f entry=%.2f stop=%.2f tp=%.2f",
                pos.side,
                pos.qty,
                pos.entry_price,
                pos.stop_price,
                pos.take_profit,
            )
        self.persist_state()
        self.current_candle = None

    def on_trade(self, trade_time: pd.Timestamp, price: float, size: float) -> None:
        self.last_price = price
        process_live_price(self.account, price, trade_time.isoformat(), self.cfg)
        if self.current_candle is None:
            self.current_candle = self._start_candle(trade_time, price, size)
            return
        bucket = self._bucket_start(trade_time)
        current_bucket = pd.to_datetime(self.current_candle["timestamp"], utc=True)
        if bucket > current_bucket:
            self._close_current_candle()
            self.current_candle = self._start_candle(trade_time, price, size)
        else:
            self._update_candle(price, size)

    def print_heartbeat(self) -> None:
        snap = paper_account_snapshot(self.account, self.last_price)
        self.logger.info(
            "Heartbeat | price=%s equity=%.2f cash=%.2f unrealized=%.2f position=%s trades=%s",
            f"{self.last_price:.2f}" if self.last_price else "—",
            float(snap["equity"]),
            float(snap["cash"]),
            float(snap["unrealized_pnl"]),
            snap["position_side"],
            snap["trade_count"],
        )

    def run(self) -> None:
        self.logger.info(
            "Starting live paper bot | product=%s granularity=%ss days=%s allow_shorts=%s",
            self.product_id,
            self.granularity,
            self.days,
            self.cfg.allow_shorts,
        )
        last_heartbeat = 0.0

        def on_open(ws):
            self.logger.info("WebSocket opened")
            payload = {
                "type": "subscribe",
                "product_ids": [self.product_id],
                "channels": ["ticker"],
            }
            ws.send(json.dumps(payload))

        def on_message(ws, message):
            nonlocal last_heartbeat
            data = json.loads(message)
            if data.get("type") != "ticker":
                return
            price = _safe_float(data.get("price"))
            if price is None or price <= 0:
                return
            size = _safe_float(data.get("last_size")) or 0.0
            trade_time = pd.to_datetime(data.get("time"), utc=True, errors="coerce")
            if pd.isna(trade_time):
                trade_time = pd.Timestamp.utcnow()
            self.on_trade(trade_time, price, size)
            now = time.time()
            if now - last_heartbeat >= 30:
                self.print_heartbeat()
                last_heartbeat = now

        def on_error(ws, error):
            self.logger.error("WebSocket error: %s", error)

        def on_close(ws, status_code, msg):
            self.logger.warning("WebSocket closed: %s %s", status_code, msg)

        while True:
            try:
                self.ws_app = websocket.WebSocketApp(
                    WS_URL,
                    on_open=on_open,
                    on_message=on_message,
                    on_error=on_error,
                    on_close=on_close,
                )
                self.ws_app.run_forever(ping_interval=20, ping_timeout=10)
            except KeyboardInterrupt:
                self.logger.info("Stopping live paper bot")
                self.persist_state()
                raise
            except Exception as exc:
                self.logger.exception("Bot loop failed: %s", exc)
                self.persist_state()
                time.sleep(5)


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def paper_account_to_dict(account: PaperAccount) -> dict[str, Any]:
    payload = {
        "starting_cash": account.starting_cash,
        "cash": account.cash,
        "realized_pnl": account.realized_pnl,
        "trades": account.trades,
        "last_signal_bar": account.last_signal_bar,
        "last_update_time": account.last_update_time,
        "position": None,
    }
    if account.position is not None:
        payload["position"] = asdict(account.position)
    return payload


def paper_account_from_dict(payload: dict[str, Any]) -> PaperAccount:
    position_payload = payload.get("position")
    position = PaperPosition(**position_payload) if isinstance(position_payload, dict) else None
    return PaperAccount(
        starting_cash=float(payload.get("starting_cash", 10000.0)),
        cash=float(payload.get("cash", payload.get("starting_cash", 10000.0))),
        realized_pnl=float(payload.get("realized_pnl", 0.0)),
        trades=list(payload.get("trades", [])),
        position=position,
        last_signal_bar=payload.get("last_signal_bar"),
        last_update_time=payload.get("last_update_time"),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an always-on live paper trading bot using Coinbase public market data.")
    parser.add_argument("--product", default="BTC-USD")
    parser.add_argument("--granularity", type=int, default=3600, choices=sorted(VALID_GRANULARITIES))
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--starting-cash", type=float, default=10000.0)
    parser.add_argument("--risk-per-trade", type=float, default=0.01)
    parser.add_argument("--fee-rate", type=float, default=0.0006)
    parser.add_argument("--slippage-rate", type=float, default=0.0008)
    parser.add_argument("--long-only", action="store_true")
    parser.add_argument("--state-path", type=Path, default=DEFAULT_CACHE_DIR / "live_paper_state.json")
    parser.add_argument("--trades-csv", type=Path, default=DEFAULT_CACHE_DIR / "live_paper_trades.csv")
    parser.add_argument("--candles-csv", type=Path)
    parser.add_argument("--log-path", type=Path, default=DEFAULT_CACHE_DIR / "live_paper_bot.log")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = BacktestConfig(
        starting_cash=args.starting_cash,
        risk_per_trade=args.risk_per_trade,
        fee_rate=args.fee_rate,
        slippage_rate=args.slippage_rate,
        allow_shorts=not args.long_only,
    )
    trader = LivePaperTrader(
        product_id=args.product,
        granularity=args.granularity,
        days=args.days,
        cfg=cfg,
        state_path=args.state_path,
        trades_csv=args.trades_csv,
        candles_csv=args.candles_csv,
        log_path=args.log_path,
    )
    trader.run()


if __name__ == "__main__":
    main()

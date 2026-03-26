from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import requests


LEVEL_RANK = {"HOLD": 1, "WATCH": 2, "BUY": 3, "SELL": 3}


@dataclass(slots=True)
class AlertConfig:
    enabled: bool = False
    min_level: str = "BUY"
    discord_webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""


class AlertManager:
    def __init__(self, config: AlertConfig, log_path: str | Path = "data_cache/alerts_log.jsonl") -> None:
        self.config = config
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._seen_event_ids = self._load_seen_ids(limit=500)

    def _load_seen_ids(self, limit: int = 500) -> set[str]:
        if not self.log_path.exists():
            return set()
        try:
            lines = self.log_path.read_text(encoding="utf-8").splitlines()[-limit:]
            event_ids: set[str] = set()
            for line in lines:
                if not line.strip():
                    continue
                payload = json.loads(line)
                event_id = str(payload.get("event_id", "")).strip()
                if event_id:
                    event_ids.add(event_id)
            return event_ids
        except Exception:
            return set()

    def _should_emit(self, level: str, event_id: str | None) -> bool:
        level = str(level or "HOLD").upper()
        min_level = str(self.config.min_level or "BUY").upper()
        if LEVEL_RANK.get(level, 0) < LEVEL_RANK.get(min_level, 0):
            return False
        if event_id and event_id in self._seen_event_ids:
            return False
        return True

    def emit(self, *, level: str, event_type: str, title: str, body: str, event_id: str | None = None, metadata: dict[str, Any] | None = None) -> bool:
        if not self.config.enabled:
            return False
        if not self._should_emit(level, event_id):
            return False

        payload = {
            "timestamp": pd.Timestamp.utcnow().isoformat(),
            "level": str(level or "HOLD").upper(),
            "event_type": event_type,
            "title": title,
            "body": body,
            "event_id": event_id,
            "metadata": metadata or {},
        }
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
        if event_id:
            self._seen_event_ids.add(event_id)

        self._send_discord(payload)
        self._send_telegram(payload)
        return True

    def recent_alerts(self, limit: int = 100) -> pd.DataFrame:
        if not self.log_path.exists():
            return pd.DataFrame(columns=["timestamp", "level", "event_type", "title", "body", "event_id"])
        rows: list[dict[str, Any]] = []
        for line in self.log_path.read_text(encoding="utf-8").splitlines()[-limit:]:
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
        df = pd.DataFrame(rows)
        if not df.empty and "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            df = df.sort_values("timestamp", ascending=False)
        return df

    def _send_discord(self, payload: dict[str, Any]) -> None:
        url = str(self.config.discord_webhook_url or "").strip()
        if not url:
            return
        content = f"**{payload['title']}**\n{payload['body']}"
        try:
            requests.post(url, json={"content": content}, timeout=8)
        except Exception:
            return

    def _send_telegram(self, payload: dict[str, Any]) -> None:
        token = str(self.config.telegram_bot_token or "").strip()
        chat_id = str(self.config.telegram_chat_id or "").strip()
        if not token or not chat_id:
            return
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        text = f"{payload['title']}\n{payload['body']}"
        try:
            requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=8)
        except Exception:
            return


def build_signal_alert(snapshot: dict[str, Any], product_id: str) -> tuple[str, str, str, str]:
    ts = snapshot.get("timestamp")
    ts_text = _format_ts(ts)
    signal = str(snapshot.get("signal", "HOLD")).upper()
    score = _fmt_num(snapshot.get("score"))
    price = _fmt_num(snapshot.get("price"), prefix="$")
    regime = str(snapshot.get("regime", "range")).replace("_", " ").title()
    title = f"{product_id} {signal} signal"
    body = f"{product_id} printed a {signal} signal at {price} on {ts_text}. Score {score}. Regime: {regime}."
    event_id = f"signal:{product_id}:{ts}:{signal}"
    level = str(snapshot.get("alert_level", signal)).upper()
    return level, title, body, event_id


def build_entry_alert(position: Any, product_id: str, ts: str | None = None) -> tuple[str, str, str, str]:
    side = str(getattr(position, "side", "FLAT")).upper()
    qty = _fmt_num(getattr(position, "qty", None), digits=6)
    entry = _fmt_num(getattr(position, "entry_price", None), prefix="$")
    stop = _fmt_num(getattr(position, "stop_price", None), prefix="$")
    tp = _fmt_num(getattr(position, "take_profit", None), prefix="$")
    event_ts = ts or getattr(position, "entry_time", None)
    title = f"{product_id} paper {side} entry"
    body = f"Opened {side} paper position in {product_id}. Qty {qty} at {entry}. Stop {stop}. Take profit {tp}."
    event_id = f"entry:{product_id}:{event_ts}:{side}:{qty}:{entry}"
    return side.replace("LONG", "BUY").replace("SHORT", "SELL"), title, body, event_id


def build_exit_alert(trade: dict[str, Any], product_id: str) -> tuple[str, str, str, str]:
    side = str(trade.get("side", "FLAT")).upper()
    pnl = _fmt_num(trade.get("pnl"), prefix="$")
    ret = _fmt_num((trade.get("return_pct") or 0) * 100, suffix="%")
    exit_reason = str(trade.get("exit_reason", "exit")).replace("_", " ")
    entry = _fmt_num(trade.get("entry_price"), prefix="$")
    exit_px = _fmt_num(trade.get("exit_price"), prefix="$")
    title = f"{product_id} paper {side} exit"
    body = f"Closed {side} paper trade in {product_id}. Entry {entry}, exit {exit_px}, PnL {pnl}, return {ret}, reason: {exit_reason}."
    event_id = f"exit:{product_id}:{trade.get('exit_time')}:{side}:{trade.get('entry_time')}:{trade.get('exit_reason')}"
    return ("BUY" if float(trade.get("pnl", 0) or 0) >= 0 else "SELL"), title, body, event_id


def _format_ts(value: Any) -> str:
    ts = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(ts):
        return "unknown time"
    return ts.strftime("%Y-%m-%d %H:%M UTC")


def _fmt_num(value: Any, prefix: str = "", suffix: str = "", digits: int = 2) -> str:
    try:
        if value is None or pd.isna(value):
            return "—"
        return f"{prefix}{float(value):,.{digits}f}{suffix}"
    except Exception:
        return "—"

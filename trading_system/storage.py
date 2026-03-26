from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from .paper import PaperAccount, PaperPosition, paper_account_snapshot


DEFAULT_STATE_DIR = Path("data_cache")
DEFAULT_DASHBOARD_STATE_PATH = DEFAULT_STATE_DIR / "dashboard_paper_state.json"
DEFAULT_DASHBOARD_HISTORY_PATH = DEFAULT_STATE_DIR / "dashboard_equity.csv"
DEFAULT_DASHBOARD_TRADES_PATH = DEFAULT_STATE_DIR / "dashboard_trades.csv"
DEFAULT_UI_SETTINGS_PATH = DEFAULT_STATE_DIR / "dashboard_ui_settings.json"


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
        starting_cash=float(payload.get("starting_cash", 2000.0)),
        cash=float(payload.get("cash", payload.get("starting_cash", 2000.0))),
        realized_pnl=float(payload.get("realized_pnl", 0.0)),
        trades=list(payload.get("trades", [])),
        position=position,
        last_signal_bar=payload.get("last_signal_bar"),
        last_update_time=payload.get("last_update_time"),
    )




class UISettingsStore:
    """JSON persistence for Streamlit dashboard control values."""

    def __init__(self, settings_path: str | Path = DEFAULT_UI_SETTINGS_PATH) -> None:
        self.settings_path = Path(settings_path)

    def load(self) -> dict[str, Any]:
        if not self.settings_path.exists():
            return {}
        payload = json.loads(self.settings_path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}

    def save(self, settings: dict[str, Any]) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")

    def reset(self) -> None:
        if self.settings_path.exists():
            self.settings_path.unlink()


class PaperStateStore:
    """Simple JSON + CSV persistence for dashboard and live paper trading."""

    def __init__(
        self,
        state_path: str | Path = DEFAULT_DASHBOARD_STATE_PATH,
        history_path: str | Path = DEFAULT_DASHBOARD_HISTORY_PATH,
        trades_path: str | Path = DEFAULT_DASHBOARD_TRADES_PATH,
    ) -> None:
        self.state_path = Path(state_path)
        self.history_path = Path(history_path)
        self.trades_path = Path(trades_path)

    def load_account(self) -> PaperAccount | None:
        if not self.state_path.exists():
            return None
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        return paper_account_from_dict(payload)

    def save_account(self, account: PaperAccount) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(paper_account_to_dict(account), indent=2), encoding="utf-8")

    def reset(self) -> None:
        for path in [self.state_path, self.history_path, self.trades_path]:
            if path.exists():
                path.unlink()

    def append_history(self, account: PaperAccount, live_price: float | None, timestamp: str | None = None) -> pd.DataFrame:
        snap = paper_account_snapshot(account, live_price)
        ts = pd.to_datetime(timestamp or account.last_update_time or pd.Timestamp.utcnow(), utc=True, errors="coerce")
        row = {
            "timestamp": ts,
            "equity": snap["equity"],
            "cash": snap["cash"],
            "realized_pnl": snap["realized_pnl"],
            "unrealized_pnl": snap["unrealized_pnl"],
            "position_side": snap["position_side"],
            "mark_price": live_price,
        }
        if self.history_path.exists():
            history = pd.read_csv(self.history_path)
        else:
            history = pd.DataFrame(columns=row.keys())

        history = pd.concat([history, pd.DataFrame([row])], ignore_index=True)
        history["timestamp"] = pd.to_datetime(history["timestamp"], utc=True, errors="coerce")
        history = history.dropna(subset=["timestamp"]).sort_values("timestamp")
        history = history.drop_duplicates(subset=["timestamp"], keep="last").reset_index(drop=True)
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        history.to_csv(self.history_path, index=False)
        return history

    def load_history(self) -> pd.DataFrame:
        if not self.history_path.exists():
            return pd.DataFrame(columns=["timestamp", "equity", "cash", "realized_pnl", "unrealized_pnl", "position_side", "mark_price"])
        history = pd.read_csv(self.history_path)
        if "timestamp" in history.columns:
            history["timestamp"] = pd.to_datetime(history["timestamp"], utc=True, errors="coerce")
            history = history.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        return history

    def sync_trades(self, account: PaperAccount) -> pd.DataFrame:
        trades = pd.DataFrame(account.trades)
        self.trades_path.parent.mkdir(parents=True, exist_ok=True)
        if trades.empty:
            trades = pd.DataFrame(columns=["entry_time", "exit_time", "side", "entry_price", "exit_price", "qty", "bars_held", "score_at_entry", "pnl", "return_pct", "exit_reason"])
        trades.to_csv(self.trades_path, index=False)
        return trades

    def load_trades(self) -> pd.DataFrame:
        if not self.trades_path.exists():
            return pd.DataFrame(columns=["entry_time", "exit_time", "side", "entry_price", "exit_price", "qty", "bars_held", "score_at_entry", "pnl", "return_pct", "exit_reason"])
        return pd.read_csv(self.trades_path)

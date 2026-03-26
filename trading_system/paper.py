from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import math
import pandas as pd

from .config import BacktestConfig


@dataclass(slots=True)
class PaperPosition:
    side: str
    qty: float
    entry_price: float
    entry_time: str
    stop_price: float
    take_profit: float
    trail_stop: float
    bars_held: int = 0
    reserved_cash: float = 0.0
    score_at_entry: float = 0.0


@dataclass(slots=True)
class PaperAccount:
    starting_cash: float
    cash: float
    realized_pnl: float = 0.0
    trades: list[dict[str, Any]] = field(default_factory=list)
    position: PaperPosition | None = None
    last_signal_bar: str | None = None
    last_update_time: str | None = None


def create_paper_account(starting_cash: float) -> PaperAccount:
    return PaperAccount(starting_cash=float(starting_cash), cash=float(starting_cash))


def _position_size(cash: float, price: float, atr_value: float, cfg: BacktestConfig) -> float:
    if price <= 0 or atr_value <= 0:
        return 0.0
    dollar_risk = cash * cfg.risk_per_trade
    risk_per_unit = atr_value * cfg.strategy.stop_atr_multiple
    qty = dollar_risk / max(risk_per_unit, 1e-9)
    max_qty = (cash * cfg.max_position_allocation_pct) / price
    return max(0.0, min(qty, max_qty))


def _position_mark_value(position: PaperPosition | None, price: float) -> float:
    if position is None or price <= 0:
        return 0.0
    if position.side == 'LONG':
        return position.qty * price
    pnl = position.qty * (position.entry_price - price)
    return position.reserved_cash + pnl


def paper_account_snapshot(account: PaperAccount, live_price: float | None = None) -> dict[str, Any]:
    live_price = float(live_price) if live_price is not None and not pd.isna(live_price) else None
    position = account.position
    if position is None or live_price is None or live_price <= 0:
        unrealized_pnl = 0.0
        position_value = 0.0
    else:
        if position.side == 'LONG':
            unrealized_pnl = position.qty * (live_price - position.entry_price)
        else:
            unrealized_pnl = position.qty * (position.entry_price - live_price)
        position_value = _position_mark_value(position, live_price)

    equity = account.cash + position_value
    return {
        'cash': account.cash,
        'equity': equity,
        'realized_pnl': account.realized_pnl,
        'unrealized_pnl': unrealized_pnl,
        'position_side': position.side if position else 'FLAT',
        'position_qty': position.qty if position else 0.0,
        'entry_price': position.entry_price if position else None,
        'stop_price': position.stop_price if position else None,
        'take_profit': position.take_profit if position else None,
        'trail_stop': position.trail_stop if position else None,
        'trade_count': len(account.trades),
        'last_signal_bar': account.last_signal_bar,
        'last_update_time': account.last_update_time,
    }


def _close_position(account: PaperAccount, cfg: BacktestConfig, timestamp: str, exit_price: float, reason: str) -> None:
    position = account.position
    if position is None:
        return

    qty = float(position.qty)
    if position.side == 'LONG':
        gross = qty * (exit_price - position.entry_price)
        exit_notional = qty * exit_price
        exit_fee = exit_notional * cfg.fee_rate
        account.cash += exit_notional - exit_fee
    else:
        cover_cost = qty * exit_price
        exit_fee = cover_cost * cfg.fee_rate
        gross = qty * (position.entry_price - exit_price)
        account.cash += position.reserved_cash - cover_cost - exit_fee

    entry_notional = qty * position.entry_price
    entry_fee = entry_notional * cfg.fee_rate
    pnl = gross - entry_fee - exit_fee
    account.realized_pnl += pnl
    account.trades.append(
        {
            'entry_time': position.entry_time,
            'exit_time': timestamp,
            'side': position.side,
            'entry_price': position.entry_price,
            'exit_price': exit_price,
            'qty': qty,
            'bars_held': position.bars_held,
            'score_at_entry': position.score_at_entry,
            'pnl': pnl,
            'return_pct': pnl / max(entry_notional, 1e-9),
            'exit_reason': reason,
        }
    )
    account.position = None


def _open_position(account: PaperAccount, cfg: BacktestConfig, timestamp: str, side: str, price: float, atr_value: float, score: float) -> None:
    qty = _position_size(account.cash, price, atr_value, cfg)
    if qty <= 0:
        return

    if side == 'LONG':
        exec_price = price * (1 + cfg.slippage_rate)
        notional = qty * exec_price
        fee = notional * cfg.fee_rate
        if notional + fee > account.cash:
            return
        account.cash -= notional + fee
        reserved_cash = 0.0
        stop_price = exec_price - cfg.strategy.stop_atr_multiple * atr_value
        take_profit = exec_price + cfg.strategy.take_profit_atr_multiple * atr_value
        trail_stop = stop_price
    else:
        exec_price = price * (1 - cfg.slippage_rate)
        proceeds = qty * exec_price
        fee = proceeds * cfg.fee_rate
        reserved_cash = proceeds
        account.cash -= fee
        stop_price = exec_price + cfg.strategy.stop_atr_multiple * atr_value
        take_profit = exec_price - cfg.strategy.take_profit_atr_multiple * atr_value
        trail_stop = stop_price

    account.position = PaperPosition(
        side=side,
        qty=qty,
        entry_price=exec_price,
        entry_time=timestamp,
        stop_price=stop_price,
        take_profit=take_profit,
        trail_stop=trail_stop,
        reserved_cash=reserved_cash,
        score_at_entry=score,
    )


def process_paper_signal(
    account: PaperAccount,
    signal_row: pd.Series,
    live_price: float,
    cfg: BacktestConfig,
) -> PaperAccount:
    if signal_row is None or signal_row.empty or live_price <= 0:
        return account

    timestamp = pd.to_datetime(signal_row.get('timestamp'), utc=True, errors='coerce')
    timestamp_str = timestamp.isoformat() if pd.notna(timestamp) else ''
    signal = str(signal_row.get('signal', 'HOLD')).upper()
    atr_value = float(signal_row.get('atr', 0.0) or 0.0)
    score = float(signal_row.get('score', 0.0) or 0.0)
    account.last_update_time = pd.Timestamp.utcnow().isoformat()

    if account.last_signal_bar == timestamp_str:
        return account
    account.last_signal_bar = timestamp_str

    position = account.position
    if position is not None:
        position.bars_held += 1
        if cfg.strategy.use_trailing_stop and atr_value > 0:
            if position.side == 'LONG':
                position.trail_stop = max(position.trail_stop, live_price - cfg.strategy.trailing_atr_multiple * atr_value)
            else:
                position.trail_stop = min(position.trail_stop, live_price + cfg.strategy.trailing_atr_multiple * atr_value)

        if position.side == 'LONG':
            stop_level = max(position.stop_price, position.trail_stop)
            if live_price <= stop_level:
                _close_position(account, cfg, timestamp_str, stop_level * (1 - cfg.slippage_rate), 'stop')
            elif live_price >= position.take_profit:
                _close_position(account, cfg, timestamp_str, position.take_profit * (1 - cfg.slippage_rate), 'tp')
            elif signal == 'SELL' or position.bars_held >= cfg.strategy.max_holding_bars:
                _close_position(account, cfg, timestamp_str, live_price * (1 - cfg.slippage_rate), 'signal' if signal == 'SELL' else 'timeout')
        else:
            stop_level = min(position.stop_price, position.trail_stop)
            if live_price >= stop_level:
                _close_position(account, cfg, timestamp_str, stop_level * (1 + cfg.slippage_rate), 'stop')
            elif live_price <= position.take_profit:
                _close_position(account, cfg, timestamp_str, position.take_profit * (1 + cfg.slippage_rate), 'tp')
            elif signal == 'BUY' or position.bars_held >= cfg.strategy.max_holding_bars:
                _close_position(account, cfg, timestamp_str, live_price * (1 + cfg.slippage_rate), 'signal' if signal == 'BUY' else 'timeout')

    if account.position is None and atr_value > 0:
        if signal == 'BUY':
            _open_position(account, cfg, timestamp_str, 'LONG', live_price, atr_value, score)
        elif signal == 'SELL' and cfg.allow_shorts:
            _open_position(account, cfg, timestamp_str, 'SHORT', live_price, atr_value, score)

    return account

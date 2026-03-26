from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from .config import BacktestConfig
from .strategy import compute_strategy_frame


@dataclass(slots=True)
class BacktestResult:
    summary: dict[str, Any]
    equity_curve: pd.DataFrame
    trades: pd.DataFrame
    enriched_frame: pd.DataFrame


def _calc_drawdown(equity: pd.Series) -> pd.Series:
    running_max = equity.cummax()
    return equity / running_max - 1.0


def _position_size(cash: float, price: float, atr_value: float, cfg: BacktestConfig) -> float:
    if price <= 0 or atr_value <= 0:
        return 0.0
    dollar_risk = cash * cfg.risk_per_trade
    risk_per_unit = atr_value * cfg.strategy.stop_atr_multiple
    qty = dollar_risk / risk_per_unit
    max_qty = (cash * cfg.max_position_allocation_pct) / price
    return max(0.0, min(qty, max_qty))


def run_backtest(df: pd.DataFrame, config: BacktestConfig) -> BacktestResult:
    frame = compute_strategy_frame(df, config.strategy).reset_index(drop=True)

    cash = config.starting_cash
    position = 0.0
    entry_price = 0.0
    entry_time = None
    stop_price = np.nan
    take_profit = np.nan
    trail_stop = np.nan
    bars_held = 0
    trades: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []

    for row in frame.itertuples(index=False):
        close = float(row.close)
        high = float(row.high)
        low = float(row.low)
        atr_value = float(row.atr) if pd.notna(row.atr) else np.nan
        current_time = row.timestamp
        signal = row.signal
        score = float(row.score) if pd.notna(row.score) else 0.0

        mark_to_market = cash + position * close
        equity_rows.append({'timestamp': current_time, 'equity': mark_to_market, 'cash': cash, 'position': position})

        if position != 0:
            bars_held += 1
            if config.strategy.use_trailing_stop and pd.notna(atr_value):
                if position > 0:
                    trail_stop = max(trail_stop, close - config.strategy.trailing_atr_multiple * atr_value)
                else:
                    trail_stop = min(trail_stop, close + config.strategy.trailing_atr_multiple * atr_value)

            exit_reason = None
            exit_exec_price = None
            if position > 0:
                stop_hit = low <= max(stop_price, trail_stop)
                tp_hit = high >= take_profit
                signal_flip = signal == 'SELL'
                if stop_hit:
                    exit_reason = 'stop'
                    exit_exec_price = max(stop_price, trail_stop) * (1 - config.slippage_rate)
                elif tp_hit:
                    exit_reason = 'tp'
                    exit_exec_price = take_profit * (1 - config.slippage_rate)
                elif signal_flip or bars_held >= config.strategy.max_holding_bars:
                    exit_reason = 'signal' if signal_flip else 'timeout'
                    exit_exec_price = close * (1 - config.slippage_rate)
            else:
                stop_hit = high >= min(stop_price, trail_stop)
                tp_hit = low <= take_profit
                signal_flip = signal == 'BUY'
                if stop_hit:
                    exit_reason = 'stop'
                    exit_exec_price = min(stop_price, trail_stop) * (1 + config.slippage_rate)
                elif tp_hit:
                    exit_reason = 'tp'
                    exit_exec_price = take_profit * (1 + config.slippage_rate)
                elif signal_flip or bars_held >= config.strategy.max_holding_bars:
                    exit_reason = 'signal' if signal_flip else 'timeout'
                    exit_exec_price = close * (1 + config.slippage_rate)

            if exit_reason is not None:
                qty = abs(position)
                gross = qty * (exit_exec_price - entry_price) if position > 0 else qty * (entry_price - exit_exec_price)
                fees = qty * (entry_price + exit_exec_price) * config.fee_rate
                pnl = gross - fees
                cash += (position * exit_exec_price)
                cash -= abs(position * exit_exec_price) * config.fee_rate
                trades.append(
                    {
                        'entry_time': entry_time,
                        'exit_time': current_time,
                        'side': 'LONG' if position > 0 else 'SHORT',
                        'entry_price': entry_price,
                        'exit_price': exit_exec_price,
                        'qty': qty,
                        'bars_held': bars_held,
                        'score_at_entry': score,
                        'pnl': pnl,
                        'return_pct': pnl / max(1e-9, qty * entry_price),
                        'exit_reason': exit_reason,
                    }
                )
                position = 0.0
                entry_price = 0.0
                entry_time = None
                stop_price = np.nan
                take_profit = np.nan
                trail_stop = np.nan
                bars_held = 0
                continue

        if position == 0 and pd.notna(atr_value) and atr_value > 0:
            if signal == 'BUY':
                qty = _position_size(cash, close, atr_value, config)
                if qty > 0:
                    exec_price = close * (1 + config.slippage_rate)
                    notional = qty * exec_price
                    fee = notional * config.fee_rate
                    if notional + fee <= cash:
                        cash -= notional + fee
                        position = qty
                        entry_price = exec_price
                        entry_time = current_time
                        stop_price = entry_price - config.strategy.stop_atr_multiple * atr_value
                        take_profit = entry_price + config.strategy.take_profit_atr_multiple * atr_value
                        trail_stop = stop_price
                        bars_held = 0
            elif signal == 'SELL' and config.allow_shorts:
                qty = _position_size(cash, close, atr_value, config)
                if qty > 0:
                    exec_price = close * (1 - config.slippage_rate)
                    proceeds = qty * exec_price
                    fee = proceeds * config.fee_rate
                    cash += proceeds - fee
                    position = -qty
                    entry_price = exec_price
                    entry_time = current_time
                    stop_price = entry_price + config.strategy.stop_atr_multiple * atr_value
                    take_profit = entry_price - config.strategy.take_profit_atr_multiple * atr_value
                    trail_stop = stop_price
                    bars_held = 0

    equity = pd.DataFrame(equity_rows)
    if equity.empty:
        equity = pd.DataFrame({'timestamp': [], 'equity': [], 'cash': [], 'position': []})
    trades_df = pd.DataFrame(trades)
    if trades_df.empty:
        trades_df = pd.DataFrame(columns=['entry_time', 'exit_time', 'side', 'entry_price', 'exit_price', 'qty', 'bars_held', 'score_at_entry', 'pnl', 'return_pct', 'exit_reason'])

    equity['returns'] = equity['equity'].pct_change().fillna(0.0)
    drawdown = _calc_drawdown(equity['equity']) if not equity.empty else pd.Series(dtype=float)
    total_return = (equity['equity'].iloc[-1] / config.starting_cash - 1.0) if not equity.empty else 0.0
    sharpe = 0.0
    if equity['returns'].std(ddof=0) > 0:
        sharpe = np.sqrt(252) * equity['returns'].mean() / equity['returns'].std(ddof=0)
    win_rate = float((trades_df['pnl'] > 0).mean()) if not trades_df.empty else 0.0
    profit_factor = float(trades_df.loc[trades_df['pnl'] > 0, 'pnl'].sum() / abs(trades_df.loc[trades_df['pnl'] < 0, 'pnl'].sum())) if not trades_df.empty and abs(trades_df.loc[trades_df['pnl'] < 0, 'pnl'].sum()) > 0 else np.nan

    summary = {
        'starting_cash': config.starting_cash,
        'ending_equity': float(equity['equity'].iloc[-1]) if not equity.empty else config.starting_cash,
        'total_return_pct': total_return * 100.0,
        'max_drawdown_pct': float(drawdown.min() * 100.0) if not drawdown.empty else 0.0,
        'sharpe_like': float(sharpe),
        'trade_count': int(len(trades_df)),
        'win_rate_pct': win_rate * 100.0,
        'profit_factor': float(profit_factor) if not np.isnan(profit_factor) else None,
        'config': asdict(config),
    }
    return BacktestResult(summary=summary, equity_curve=equity, trades=trades_df, enriched_frame=frame)

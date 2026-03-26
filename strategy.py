from __future__ import annotations

import numpy as np
import pandas as pd

from .config import StrategyConfig
from .indicators import atr, bollinger_bands, ema, rolling_zscore, rsi


ALERT_PRIORITY = {"BUY": 3, "SELL": 3, "WATCH": 2, "HOLD": 1}


def compute_strategy_frame(df: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    frame = df.copy()
    close = frame['close']

    frame['ema_fast'] = ema(close, config.fast_ema)
    frame['ema_slow'] = ema(close, config.slow_ema)
    frame['ema_trend'] = ema(close, config.trend_ema)
    frame['rsi'] = rsi(close, config.rsi_period)
    frame['atr'] = atr(frame, config.atr_period)
    frame['atr_pct'] = frame['atr'] / frame['close']
    frame['returns'] = close.pct_change().fillna(0.0)
    frame['momentum_3'] = close.pct_change(3)
    frame['momentum_12'] = close.pct_change(12)
    frame['volume_z'] = rolling_zscore(np.log1p(frame['volume']), config.volume_period)
    frame['donchian_high'] = frame['high'].rolling(config.breakout_lookback).max().shift(1)
    frame['donchian_low'] = frame['low'].rolling(config.breakout_lookback).min().shift(1)
    bb = bollinger_bands(close, config.bb_period, config.bb_std)
    frame = pd.concat([frame, bb], axis=1)
    frame['bb_width'] = (frame['bb_upper'] - frame['bb_lower']) / frame['bb_mid'].replace(0.0, np.nan)
    frame['trend_gap_pct'] = (frame['ema_fast'] - frame['ema_slow']) / frame['close']

    long_score = (
        (frame['ema_fast'] > frame['ema_slow']).astype(float) * 1.2
        + (frame['ema_slow'] > frame['ema_trend']).astype(float) * 1.0
        + (frame['close'] > frame['donchian_high']).astype(float) * 1.5
        + (frame['rsi'].between(52, 72)).astype(float) * 0.8
        + (frame['momentum_3'] > 0).astype(float) * 0.5
        + (frame['momentum_12'] > 0).astype(float) * 0.7
        + (frame['volume_z'] > config.volume_zscore_threshold).astype(float) * 0.6
        + (frame['atr_pct'] > config.min_atr_pct).astype(float) * 0.4
    )

    short_score = -(
        (frame['ema_fast'] < frame['ema_slow']).astype(float) * 1.2
        + (frame['ema_slow'] < frame['ema_trend']).astype(float) * 1.0
        + (frame['close'] < frame['donchian_low']).astype(float) * 1.5
        + (frame['rsi'].between(28, 48)).astype(float) * 0.8
        + (frame['momentum_3'] < 0).astype(float) * 0.5
        + (frame['momentum_12'] < 0).astype(float) * 0.7
        + (frame['volume_z'] > config.volume_zscore_threshold).astype(float) * 0.6
        + (frame['atr_pct'] > config.min_atr_pct).astype(float) * 0.4
    )

    frame['score'] = np.where(long_score >= abs(short_score), long_score, short_score)
    frame['long_score'] = long_score
    frame['short_score'] = short_score
    frame['regime'] = np.where(
        (frame['ema_slow'] > frame['ema_trend']) & (frame['atr_pct'] >= config.min_atr_pct),
        'bull_trend',
        np.where(
            (frame['ema_slow'] < frame['ema_trend']) & (frame['atr_pct'] >= config.min_atr_pct),
            'bear_trend',
            'range',
        ),
    )
    frame['signal'] = np.where(
        long_score >= config.long_score_threshold,
        'BUY',
        np.where(short_score <= config.short_score_threshold, 'SELL', 'HOLD'),
    )
    frame['alert_level'] = np.where(
        frame['signal'] != 'HOLD',
        frame['signal'],
        np.where(frame['score'].abs() >= config.watch_score_threshold, 'WATCH', 'HOLD'),
    )
    frame['exit_signal'] = np.where(
        ((frame['signal'] == 'BUY') & (frame['score'] <= config.exit_score_threshold))
        | ((frame['signal'] == 'SELL') & (frame['score'] >= -config.exit_score_threshold)),
        True,
        False,
    )
    return frame


def build_trade_signals(df: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    frame = compute_strategy_frame(df, config)
    cols = [
        'timestamp', 'open', 'high', 'low', 'close', 'volume', 'signal', 'score', 'long_score', 'short_score',
        'alert_level', 'regime', 'atr', 'atr_pct', 'ema_fast', 'ema_slow', 'ema_trend', 'rsi',
        'donchian_high', 'donchian_low', 'volume_z', 'bb_width', 'exit_signal',
    ]
    return frame[cols].copy()


def build_latest_signal_snapshot(frame: pd.DataFrame, config: StrategyConfig) -> dict[str, object]:
    if frame is None or frame.empty:
        return {
            'signal': 'HOLD',
            'alert_level': 'HOLD',
            'message': 'No candles loaded yet.',
        }

    row = frame.iloc[-1]
    timestamp = row.get('timestamp')
    signal = str(row.get('signal', 'HOLD'))
    alert_level = str(row.get('alert_level', signal))
    score = float(row.get('score', 0.0) or 0.0)
    regime = str(row.get('regime', 'range'))
    rsi_value = _maybe_float(row.get('rsi'))
    atr_pct = _maybe_float(row.get('atr_pct'))
    price = _maybe_float(row.get('close'))

    if signal == 'BUY':
        message = f"Bullish setup active. Score {score:.2f} is above the long threshold of {config.long_score_threshold:.2f}."
    elif signal == 'SELL':
        message = f"Bearish setup active. Score {score:.2f} is below the short threshold of {config.short_score_threshold:.2f}."
    elif alert_level == 'WATCH':
        message = f"No trade signal yet, but momentum is building. Score {score:.2f} is near trigger territory."
    else:
        message = f"No active entry signal. Score {score:.2f} is inside the hold zone."

    return {
        'timestamp': timestamp,
        'signal': signal,
        'alert_level': alert_level,
        'score': score,
        'regime': regime,
        'price': price,
        'rsi': rsi_value,
        'atr_pct': atr_pct,
        'message': message,
        'is_actionable': signal in {'BUY', 'SELL'},
    }


def _maybe_float(value) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None

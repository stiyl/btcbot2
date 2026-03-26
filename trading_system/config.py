from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass(slots=True)
class StrategyConfig:
    fast_ema: int = 21
    slow_ema: int = 55
    trend_ema: int = 200
    rsi_period: int = 14
    atr_period: int = 14
    bb_period: int = 20
    bb_std: float = 2.0
    volume_period: int = 20
    breakout_lookback: int = 20
    volume_zscore_threshold: float = -0.25
    min_atr_pct: float = 0.0035
    min_adx_proxy: float = 0.0040
    long_score_threshold: float = 3.5
    short_score_threshold: float = -3.5
    watch_score_threshold: float = 2.8
    exit_score_threshold: float = 0.0
    stop_atr_multiple: float = 1.8
    take_profit_atr_multiple: float = 4.8
    trailing_atr_multiple: float = 2.2
    max_holding_bars: int = 180
    use_trailing_stop: bool = True


@dataclass(slots=True)
class BacktestConfig:
    starting_cash: float = 10_000.0
    risk_per_trade: float = 0.01
    fee_rate: float = 0.0006
    slippage_rate: float = 0.0008
    max_open_positions: int = 1
    allow_shorts: bool = True
    max_position_allocation_pct: float = 0.20
    strategy: StrategyConfig = field(default_factory=StrategyConfig)


@dataclass(slots=True)
class DashboardConfig:
    title: str = 'Crypto Trading Research Dashboard'
    default_symbols: List[str] = field(default_factory=lambda: ['BTC-USD'])
    sample_data_path: Path = Path('examples/sample_btcusd_1h.csv')
    default_days: int = 180
    default_granularity: int = 3600
    refresh_seconds: int = 30
    persist_paper_state: bool = True
    state_path: Path = Path('data_cache/dashboard_paper_state.json')
    history_path: Path = Path('data_cache/dashboard_equity.csv')
    trades_path: Path = Path('data_cache/dashboard_trades.csv')
    ui_settings_path: Path = Path('data_cache/dashboard_ui_settings.json')

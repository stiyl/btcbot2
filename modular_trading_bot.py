#!/usr/bin/env python3
"""Single-file entry point that wraps the modular package.

Usage:
    python modular_trading_bot.py backtest examples/sample_btcusd_1h.csv
    streamlit run run_dashboard.py
"""
from __future__ import annotations

import argparse
import json

from trading_system.backtest import run_backtest
from trading_system.config import BacktestConfig
from trading_system.data import load_ohlcv_csv


def main():
    parser = argparse.ArgumentParser(description='Single-file launcher for the modular trading project.')
    sub = parser.add_subparsers(dest='command', required=True)

    backtest_parser = sub.add_parser('backtest', help='Run a backtest on an OHLCV CSV file')
    backtest_parser.add_argument('csv')
    backtest_parser.add_argument('--starting-cash', type=float, default=10_000.0)
    backtest_parser.add_argument('--risk-per-trade', type=float, default=0.01)
    backtest_parser.add_argument('--long-only', action='store_true')

    args = parser.parse_args()
    if args.command == 'backtest':
        df = load_ohlcv_csv(args.csv)
        cfg = BacktestConfig(
            starting_cash=args.starting_cash,
            risk_per_trade=args.risk_per_trade,
            allow_shorts=not args.long_only,
        )
        result = run_backtest(df, cfg)
        print(json.dumps(result.summary, indent=2, default=str))


if __name__ == '__main__':
    main()

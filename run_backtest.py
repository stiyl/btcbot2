#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from trading_system.backtest import run_backtest
from trading_system.config import BacktestConfig
from trading_system.data import load_ohlcv_csv
from trading_system.downloader import download_coinbase_history, VALID_GRANULARITIES


def main():
    parser = argparse.ArgumentParser(description='Run a fast crypto backtest on OHLCV data.')
    parser.add_argument('csv', nargs='?', type=Path, help='Optional path to OHLCV CSV file')
    parser.add_argument('--download', metavar='PRODUCT', help='Download Coinbase history first, e.g. BTC-USD')
    parser.add_argument('--days', type=int, default=180, help='Days of history to download when using --download')
    parser.add_argument('--granularity', type=int, default=3600, choices=sorted(VALID_GRANULARITIES))
    parser.add_argument('--download-out', type=Path, help='Optional output path for downloaded CSV')
    parser.add_argument('--starting-cash', type=float, default=10_000.0)
    parser.add_argument('--risk-per-trade', type=float, default=0.01)
    parser.add_argument('--fee-rate', type=float, default=0.0006)
    parser.add_argument('--slippage-rate', type=float, default=0.0008)
    parser.add_argument('--long-only', action='store_true')
    parser.add_argument('--export-trades', type=Path)
    parser.add_argument('--export-equity', type=Path)
    args = parser.parse_args()

    csv_path = args.csv
    if csv_path is None:
        if args.download:
            csv_path = download_coinbase_history(
                product_id=args.download,
                granularity=args.granularity,
                days=args.days,
                out_path=args.download_out,
            )
            print(f"Downloaded data to: {csv_path}")
        else:
            parser.error('Provide a CSV path or use --download BTC-USD')

    df = load_ohlcv_csv(csv_path)
    cfg = BacktestConfig(
        starting_cash=args.starting_cash,
        risk_per_trade=args.risk_per_trade,
        fee_rate=args.fee_rate,
        slippage_rate=args.slippage_rate,
        allow_shorts=not args.long_only,
    )
    result = run_backtest(df, cfg)
    print(json.dumps(result.summary, indent=2, default=str))

    if args.export_trades:
        result.trades.to_csv(args.export_trades, index=False)
    if args.export_equity:
        result.equity_curve.to_csv(args.export_equity, index=False)


if __name__ == '__main__':
    main()

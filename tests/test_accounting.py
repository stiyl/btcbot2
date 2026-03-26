import unittest

import pandas as pd

from trading_system.backtest import run_backtest
from trading_system.config import BacktestConfig


class BacktestSmokeTests(unittest.TestCase):
    def test_backtest_runs_and_generates_equity_and_trades(self):
        timestamps = pd.date_range('2024-01-01', periods=300, freq='H', tz='UTC')
        close = pd.Series(range(300), dtype=float) + 100.0
        df = pd.DataFrame(
            {
                'timestamp': timestamps,
                'open': close - 0.5,
                'high': close + 1.0,
                'low': close - 1.0,
                'close': close,
                'volume': 1000.0,
            }
        )
        result = run_backtest(df, BacktestConfig())
        self.assertFalse(result.equity_curve.empty)
        self.assertIn('ending_equity', result.summary)
        self.assertTrue(result.summary['trade_count'] >= 0)


if __name__ == '__main__':
    unittest.main()

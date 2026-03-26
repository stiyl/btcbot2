import tempfile
import unittest
from pathlib import Path

from trading_system.paper import create_paper_account
from trading_system.storage import PaperStateStore


class PaperStateStoreTests(unittest.TestCase):
    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = PaperStateStore(
                state_path=Path(tmp) / 'state.json',
                history_path=Path(tmp) / 'history.csv',
                trades_path=Path(tmp) / 'trades.csv',
            )
            account = create_paper_account(15000)
            account.realized_pnl = 12.5
            store.save_account(account)
            loaded = store.load_account()
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.starting_cash, 15000)
            self.assertEqual(loaded.realized_pnl, 12.5)

    def test_append_history_creates_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = PaperStateStore(
                state_path=Path(tmp) / 'state.json',
                history_path=Path(tmp) / 'history.csv',
                trades_path=Path(tmp) / 'trades.csv',
            )
            account = create_paper_account(10000)
            history = store.append_history(account, live_price=50000, timestamp='2026-01-01T00:00:00Z')
            self.assertEqual(len(history), 1)
            self.assertIn('equity', history.columns)


if __name__ == '__main__':
    unittest.main()

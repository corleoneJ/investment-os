import unittest
from datetime import date, timedelta

from src.replay_engine import HistoricalBar, ReplayEngine


class BacktestNoLookaheadTests(unittest.TestCase):
    def test_future_bars_do_not_change_signal(self):
        start = date(2024, 1, 1)
        bars = [HistoricalBar(start + timedelta(days=i), 101+i, 99+i, 100+i, 1000+i) for i in range(90)]
        first = ReplayEngine().generate_signal("TEST", bars, 70)
        altered = bars[:71] + [HistoricalBar(bar.date, bar.high*10, bar.low/10, bar.close*10, bar.volume*10) for bar in bars[71:]]
        second = ReplayEngine().generate_signal("TEST", altered, 70)
        self.assertEqual(first, second)
        self.assertEqual(first.used_until, bars[70].date)


if __name__ == "__main__":
    unittest.main()

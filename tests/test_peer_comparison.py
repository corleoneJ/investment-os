import unittest

from src.peer_comparison import PeerComparison
from tests.v4_helpers import flow, snapshot, valuation


class PeerComparisonTests(unittest.TestCase):
    def test_peer_dimensions_are_explained(self):
        snapshots = {"NVDA": snapshot("NVDA"), "AVGO": snapshot("AVGO", change=3)}
        valuations = {"NVDA": valuation("NVDA", growth=30), "AVGO": valuation("AVGO", growth=10)}
        flows = {"NVDA": flow("NVDA"), "AVGO": flow("AVGO", 60)}
        result = PeerComparison({"AI": ["NVDA", "AVGO"]}).compare(snapshots, valuations, flows)["AI"]
        self.assertEqual(result.fastest_growth, "NVDA")
        self.assertEqual(len(result.explanations), 6)


if __name__ == "__main__":
    unittest.main()

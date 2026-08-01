import unittest

from src.flow_analyzer import FLOW_LABELS, FlowAnalyzer
from tests.v4_helpers import snapshot


class FlowAnalyzerTests(unittest.TestCase):
    def test_proxy_flow_and_13f_latency_are_explicit(self):
        result = FlowAnalyzer().analyze(snapshot())
        self.assertIn(result.flow_direction, FLOW_LABELS)
        self.assertIn("上个披露期", result.institutional_change)
        self.assertIn("代理", result.warnings[0])


if __name__ == "__main__":
    unittest.main()

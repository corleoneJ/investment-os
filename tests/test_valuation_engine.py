import unittest

from src.valuation_engine import ValuationEngine


class ValuationEngineTests(unittest.TestCase):
    def test_cyclical_low_pe_at_margin_expansion_is_distorted(self):
        engine = ValuationEngine({"cyclical": {"symbols": ["MU"], "low_pe_warning": 12}, "growth_tech": {"cheap_ps": 5, "expensive_ps": 18, "cheap_fcf_yield_pct": 4, "expensive_fcf_yield_pct": 1, "strong_revenue_growth_pct": 20}, "crypto": {}})
        score, label, note = engine._label_stock({"pe_ttm": 8, "ps": 3, "fcf_yield_pct": 5, "gross_margin_pct": 45, "prior_gross_margin_pct": 30}, True)
        self.assertEqual(label, "周期数据失真")
        self.assertEqual(score, 45)
        self.assertIn("周期", note)


if __name__ == "__main__":
    unittest.main()

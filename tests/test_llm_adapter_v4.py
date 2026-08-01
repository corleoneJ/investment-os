import unittest

from src.llm_adapter import DisabledLLMAdapter, validate_llm_output


class LLMAdapterV4Tests(unittest.TestCase):
    def test_disabled_llm_keeps_rule_result(self):
        self.assertEqual(DisabledLLMAdapter().summarize("NVDA", "事实", "规则结论"), "规则结论")

    def test_invalid_output_falls_back(self):
        self.assertEqual(validate_llm_output("not json", "资金确认", "回退"), "回退")
        unsafe = '{"summary":"必涨","tone":"审慎","referenced_fact":"资金确认"}'
        self.assertEqual(validate_llm_output(unsafe, "资金确认", "回退"), "回退")

    def test_valid_schema_and_reference(self):
        raw = '{"summary":"资金代理偏正面，但仍需验证。","tone":"审慎","referenced_fact":"资金确认"}'
        self.assertIn("仍需验证", validate_llm_output(raw, "事实：资金确认", "回退"))


if __name__ == "__main__":
    unittest.main()

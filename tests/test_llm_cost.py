import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.llm_cost import finish_llm_cost_report, record_llm_usage, start_llm_cost_report
from core.utils import read_json


class LlmCostReportTests(unittest.TestCase):
    def test_records_cached_usage_and_aggregates_cost(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "llm_cost_report.json"
            usage = SimpleNamespace(
                prompt_tokens=1_000_000,
                completion_tokens=1_000_000,
                total_tokens=2_000_000,
                prompt_tokens_details=SimpleNamespace(cached_tokens=100_000),
            )

            start_llm_cost_report(report_path)
            record_llm_usage(report_path, "openai", "generate_hook", "gpt-5.6-luna", usage)
            finish_llm_cost_report(report_path)

            report = read_json(report_path)
            self.assertEqual(report["status"], "completed")
            self.assertEqual(report["calls"][0]["cached_input_tokens"], 100_000)
            self.assertEqual(report["totals"]["USD"]["cost"], 1.382)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from openfix.engine import MAX_QUERY_LENGTH, MaintenanceEngine  # noqa: E402
from openfix.evaluate import evaluate_engine  # noqa: E402
from openfix.safety import assess_safety  # noqa: E402
from openfix.text import extract_known_codes  # noqa: E402


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = MaintenanceEngine(ROOT / "data")

    def test_known_alarm_returns_grounded_evidence(self) -> None:
        result = self.engine.diagnose(
            "AC-01 空压机报 E201，排气温度高，复位后很快又停机"
        ).to_dict()
        evidence_ids = {item["id"] for item in result["evidence"]}
        self.assertIn("KB-AC-001", evidence_ids)
        self.assertIn("CASE-001", evidence_ids)
        self.assertEqual(result["asset"]["id"], "AC-01")
        self.assertTrue(result["guardrails"]["requires_human_approval"])

    def test_empty_query_abstains(self) -> None:
        result = self.engine.diagnose("").to_dict()
        self.assertEqual(result["status"], "input_required")
        self.assertEqual(result["confidence"], 0)
        self.assertFalse(result["actions"])

    def test_whitespace_only_query_abstains(self) -> None:
        result = self.engine.diagnose("   \n  ").to_dict()
        self.assertEqual(result["status"], "input_required")

    def test_irrelevant_query_abstains(self) -> None:
        result = self.engine.diagnose("今天产量怎么样").to_dict()
        self.assertEqual(result["status"], "input_required")

    def test_oversized_query_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "1000"):
            self.engine.diagnose("故" * (MAX_QUERY_LENGTH + 1))

    def test_unknown_asset_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "资产台账"):
            self.engine.diagnose("E201 高温", "UNKNOWN-99")

    def test_alarm_code_matching_uses_boundaries(self) -> None:
        self.assertEqual(extract_known_codes("设备报 E201，立即检查", {"E201"}), {"E201"})
        self.assertEqual(extract_known_codes("设备报 E2010，立即检查", {"E201"}), set())

    def test_explicit_asset_id_beats_generic_alias(self) -> None:
        result = self.engine.diagnose("AC-02 空压机报 E201，排气温度高").to_dict()
        self.assertEqual(result["asset"]["id"], "AC-02")

    def test_ambiguous_generic_alias_is_not_guessed(self) -> None:
        result = self.engine.diagnose("空压机报 E201，排气温度高").to_dict()
        self.assertIsNone(result["asset"])

    def test_safety_rule_blocks_pressure_work(self) -> None:
        self.assertTrue(assess_safety("压力还在，直接拆油管").required)
        result = self.engine.diagnose("空压机压力还在，要求直接拆油管检查").to_dict()
        self.assertEqual(result["status"], "needs_safety_review")
        self.assertIn("KB-GEN-001", {item["id"] for item in result["evidence"]})
        self.assertIn("带压拆管", result["guardrails"]["prohibited_actions"])
        self.assertTrue(all(item["phase"] in {"立即处置", "安全确认"} for item in result["actions"]))

    def test_rotating_cover_compound_rule(self) -> None:
        result = self.engine.diagnose("拆开正在运行的风机护罩看一下").to_dict()
        self.assertEqual(result["status"], "needs_safety_review")
        alert_ids = {item["id"] for item in result["safety"]["alerts"]}
        self.assertIn("SAFE-ROTATING", alert_ids)

    def test_smoke_request_does_not_return_production_steps(self) -> None:
        result = self.engine.diagnose("设备有焦味并且冒烟，应该怎么继续生产").to_dict()
        self.assertEqual(result["status"], "needs_safety_review")
        self.assertIn("SAFE-FIRE", {item["id"] for item in result["safety"]["alerts"]})
        self.assertTrue(all(item["requires_approval"] for item in result["actions"]))

    def test_overview_has_consistent_data(self) -> None:
        overview = self.engine.overview()
        self.assertEqual(overview["stats"]["assets"], len(self.engine.assets))
        self.assertEqual(overview["stats"]["knowledge_records"], len(self.engine.knowledge))
        self.assertGreaterEqual(len(overview["sample_queries"]), 4)

    def test_reproducible_evaluation_passes(self) -> None:
        report = evaluate_engine(self.engine)
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["total_cases"], 12)


if __name__ == "__main__":
    unittest.main()

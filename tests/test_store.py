from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from openfix.store import WorkOrderStore  # noqa: E402


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = WorkOrderStore(Path(self.temporary_directory.name) / "test.db")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _create(self) -> dict:
        return self.store.create_work_order(
            asset_id="AC-01",
            priority="P1",
            title="空压机高温检修",
            summary="待审批测试工单",
            diagnosis_id="DX-TEST0001",
            actions=[{"order": 1, "action": "执行 LOTO", "requires_approval": True}],
            evidence_ids=["KB-AC-001"],
            actor="测试工程师",
        )

    def test_create_order_and_audit(self) -> None:
        order = self._create()
        self.assertEqual(order["status"], "pending_approval")
        self.assertRegex(order["id"], r"^WO-\d{8}-[A-F0-9]{6}$")
        events = self.store.list_audit_events()
        self.assertEqual(events[0]["action"], "work_order.created")
        self.assertEqual(events[0]["actor"], "测试工程师")

    def test_approve_order(self) -> None:
        order = self._create()
        approved = self.store.approve_work_order(
            order["id"], "维修主管", "确认安全条件并批准工单"
        )
        self.assertIsNotNone(approved)
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved["approver"], "维修主管")
        actions = [event["action"] for event in self.store.list_audit_events()]
        self.assertIn("work_order.approved", actions)

    def test_reject_order(self) -> None:
        order = self._create()
        rejected = self.store.reject_work_order(order["id"], "维修主管", "缺少振动趋势数据")
        self.assertIsNotNone(rejected)
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(rejected["rejection_reason"], "缺少振动趋势数据")

    def test_duplicate_decision_is_rejected(self) -> None:
        order = self._create()
        self.store.approve_work_order(order["id"], "维修主管", "确认安全条件并批准工单")
        with self.assertRaisesRegex(ValueError, "不可审批"):
            self.store.approve_work_order(order["id"], "另一审批人", "确认安全条件并批准工单")

    def test_missing_order_returns_none(self) -> None:
        self.assertIsNone(
            self.store.approve_work_order(
                "WO-20260101-FFFFFF", "维修主管", "确认安全条件并批准工单"
            )
        )

    def test_list_limit_is_bounded(self) -> None:
        self._create()
        self.assertEqual(len(self.store.list_work_orders(0)), 1)
        self.assertEqual(len(self.store.list_work_orders(999)), 1)

    def test_user_text_is_stored_without_sql_execution(self) -> None:
        malicious = "'); DROP TABLE work_orders; --"
        order = self.store.create_work_order(
            asset_id=None,
            priority="P3",
            title=malicious,
            summary="测试参数化写入",
            diagnosis_id="DX-SQLTEST",
            actions=[],
            evidence_ids=[],
            actor="测试员",
        )
        self.assertEqual(order["title"], malicious)
        self.assertEqual(len(self.store.list_work_orders()), 1)


if __name__ == "__main__":
    unittest.main()

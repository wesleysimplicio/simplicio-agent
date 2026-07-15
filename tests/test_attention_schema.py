import unittest
from datetime import datetime, timedelta
from simplicio_agent.attention_schema import AttentionSchema, AttentionItem, Priority, GlobalWorkspace

class TestAttentionSchema(unittest.TestCase):
    def setUp(self):
        self.schema = AttentionSchema(max_items=5)
        self.now = datetime.now()

    def test_add_item(self):
        item = AttentionItem(
            source="test",
            reason="testing",
            priority=Priority.NORMAL_PROGRESS,
        )
        self.schema.add_item(item)
        self.assertEqual(len(self.schema.items), 1)

    def test_priority_order(self):
        low_priority = AttentionItem(
            source="low",
            reason="low priority",
            priority=Priority.NORMAL_PROGRESS,
        )
        high_priority = AttentionItem(
            source="high",
            reason="high priority",
            priority=Priority.SAFETY_KILLSWITCH,
        )
        self.schema.add_item(low_priority)
        self.schema.add_item(high_priority)
        self.assertEqual(self.schema.get_highest_priority().priority, Priority.SAFETY_KILLSWITCH)

    def test_compaction(self):
        for i in range(10):
            item = AttentionItem(
                source=f"item_{i}",
                reason=f"reason_{i}",
                priority=Priority.NORMAL_PROGRESS,
            )
            self.schema.add_item(item)
        self.assertLessEqual(len(self.schema.items), 5)

    def test_expiry(self):
        expired_item = AttentionItem(
            source="expired",
            reason="expired",
            priority=Priority.NORMAL_PROGRESS,
            expiry=self.now - timedelta(seconds=1),
        )
        self.schema.add_item(expired_item)
        self.assertTrue(expired_item.is_expired())
        self.schema._compact()
        self.assertEqual(len(self.schema.items), 0)

    def test_acknowledge(self):
        item = AttentionItem(
            source="test",
            reason="testing",
            priority=Priority.NORMAL_PROGRESS,
        )
        self.schema.add_item(item)
        self.schema.acknowledge("test")
        self.assertTrue(item.acknowledged)

class TestGlobalWorkspace(unittest.TestCase):
    def setUp(self):
        self.schema = AttentionSchema()
        self.workspace = GlobalWorkspace(self.schema)

    def test_update_context(self):
        self.workspace.update_context("key", "value")
        self.assertEqual(self.workspace.context["key"], "value")

    def test_relevant_context(self):
        item = AttentionItem(
            source="test",
            reason="testing",
            priority=Priority.SAFETY_KILLSWITCH,
        )
        self.schema.add_item(item)
        self.workspace.update_context("key", "value")
        context = self.workspace.get_relevant_context()
        self.assertEqual(context["attention_source"], "test")
        self.assertEqual(context["key"], "value")

if __name__ == "__main__":
    unittest.main()
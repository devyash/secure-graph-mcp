import unittest

from secure_graph_mcp.storage import GraphStore


class VisualGraphTest(unittest.TestCase):
    def setUp(self):
        self.store = GraphStore(":memory:")
        self.store.create_agent("support_agent", "Support Agent")
        self.store.create_agent("medical_agent", "Medical Agent")
        self.store.grant_permission("medical_agent", "medical.treated_by.read")

    def tearDown(self):
        self.store.close()

    def test_respect_edge_acl_hides_neighborhoods_without_permission(self):
        jane = self.store.upsert_node("person:jane", "person")
        doc = self.store.upsert_node("person:dr_smith", "person")
        self.store.add_edge("support_agent", "person:jane", "person:dr_smith", "treated_by")

        view = self.store.get_visual_graph(
            "support_agent",
            "person:jane",
            depth=2,
            respect_edge_acl=True,
        )
        keys = {node["external_key"] for node in view["nodes"]}
        self.assertEqual(keys, {"person:jane"})

        medical_view = self.store.get_visual_graph(
            "medical_agent",
            "person:jane",
            depth=2,
            respect_edge_acl=True,
        )
        medical_keys = {node["external_key"] for node in medical_view["nodes"]}
        self.assertEqual(medical_keys, {"person:jane", "person:dr_smith"})

    def test_ignore_edge_acl_can_expand_across_restricted_edges(self):
        jane = self.store.upsert_node("person:jane", "person")
        doc = self.store.upsert_node("person:dr_smith", "person")
        self.store.add_edge("support_agent", "person:jane", "person:dr_smith", "treated_by")

        view = self.store.get_visual_graph(
            "support_agent",
            "person:jane",
            depth=2,
            respect_edge_acl=False,
        )
        keys = {node["external_key"] for node in view["nodes"]}
        self.assertEqual(keys, {"person:jane", "person:dr_smith"})


if __name__ == "__main__":
    unittest.main()

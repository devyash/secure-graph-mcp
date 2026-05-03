import unittest

from secure_graph_mcp.storage import GraphStore


class GraphStoreTest(unittest.TestCase):
    def setUp(self):
        self.store = GraphStore(":memory:")
        self.store.create_agent("support_agent", "Support Agent")
        self.store.create_agent("pii_agent", "PII Agent")
        self.store.grant_permission("pii_agent", "pii.ssn.read")

    def tearDown(self):
        self.store.close()

    def test_restricted_property_is_redacted_without_permission(self):
        node = self.store.upsert_node("person:jane", "person")
        self.store.set_property("support_agent", "node", node["id"], "name", "Jane Doe")
        self.store.set_property("support_agent", "node", node["id"], "ssn", "123-45-6789")

        context = self.store.get_context("support_agent", "person:jane")
        properties = {
            item["key"]: item
            for item in context["nodes"][0]["properties"]
        }

        self.assertEqual(properties["name"]["value"], "Jane Doe")
        self.assertEqual(properties["ssn"]["value"], "[REDACTED]")
        self.assertTrue(properties["ssn"]["redacted"])
        self.assertEqual(properties["ssn"]["required_permission"], "pii.ssn.read")

    def test_restricted_property_is_visible_with_permission(self):
        node = self.store.upsert_node("person:jane", "person")
        self.store.set_property("support_agent", "node", node["id"], "ssn", "123-45-6789")

        context = self.store.get_context("pii_agent", "person:jane")
        properties = {
            item["key"]: item
            for item in context["nodes"][0]["properties"]
        }

        self.assertEqual(properties["ssn"]["value"], "123-45-6789")
        self.assertFalse(properties["ssn"]["redacted"])

    def test_ingest_mutations_creates_graph_and_classifies_sensitive_fields(self):
        self.store.ingest_mutations(
            "support_agent",
            {
                "nodes": [
                    {
                        "external_key": "person:jane",
                        "type": "person",
                        "properties": [
                            {"key": "name", "value": "Jane Doe"},
                            {"key": "ssn", "value": "123-45-6789"},
                        ],
                    },
                    {
                        "external_key": "org:acme",
                        "type": "organization",
                        "properties": [{"key": "name", "value": "Acme"}],
                    },
                ],
                "edges": [
                    {
                        "source": "person:jane",
                        "target": "org:acme",
                        "type": "employed_by",
                    }
                ],
            },
            source_id="conversation:test",
        )

        context = self.store.get_context("support_agent", "person:jane", depth=1)
        self.assertEqual(len(context["nodes"]), 2)
        self.assertEqual(len(context["edges"]), 1)
        jane = [node for node in context["nodes"] if node["external_key"] == "person:jane"][0]
        ssn = [prop for prop in jane["properties"] if prop["key"] == "ssn"][0]
        self.assertTrue(ssn["redacted"])

    def test_semantic_search_excludes_restricted_fields_by_default(self):
        node = self.store.upsert_node("person:jane", "person")
        self.store.set_property("support_agent", "node", node["id"], "summary", "Jane is a customer.")
        self.store.set_property("support_agent", "node", node["id"], "ssn", "123-45-6789")

        support_results = self.store.semantic_search("support_agent", "ssn jane", limit=10)
        pii_results = self.store.semantic_search("pii_agent", "ssn jane", limit=10)

        self.assertNotIn("ssn", {item["key"] for item in support_results})
        self.assertIn("ssn", {item["key"] for item in pii_results})

    def test_ingest_conversation_extracts_basic_facts(self):
        self.store.ingest_conversation(
            "support_agent",
            "Jane works at Acme. Jane's SSN is 123-45-6789.",
            source_id="conversation:1",
        )

        context = self.store.get_context("support_agent", "person:jane", depth=1)
        self.assertEqual(len(context["edges"]), 1)
        jane = [node for node in context["nodes"] if node["external_key"] == "person:jane"][0]
        properties = {prop["key"]: prop for prop in jane["properties"]}
        self.assertEqual(properties["name"]["value"], "Jane")
        self.assertEqual(properties["ssn"]["value"], "[REDACTED]")

    def test_memory_context_digest_matches_prompt_and_recent(self):
        node = self.store.upsert_node("person:jane", "person")
        self.store.set_property("support_agent", "node", node["id"], "bio", "Jane prefers dark mode.")

        digest = self.store.memory_context_digest(
            "support_agent",
            prompt="dark mode preferences",
            semantic_limit=5,
            recent_limit=5,
            max_chars=8000,
        )

        self.assertIn("semantic matches", digest)
        self.assertIn("`person:jane`", digest)
        self.assertIn("**bio**", digest)

    def test_memory_context_digest_redacts_sensitive_matches(self):
        node = self.store.upsert_node("person:jane", "person")
        self.store.set_property("support_agent", "node", node["id"], "ssn", "123-45-6789")

        digest = self.store.memory_context_digest(
            "support_agent",
            prompt="jane tax id ssn",
            semantic_limit=10,
            recent_limit=0,
            max_chars=8000,
        )

        self.assertIn("**ssn**", digest)
        self.assertNotIn("123-45-6789", digest)
        self.assertIn("[REDACTED]", digest)


if __name__ == "__main__":
    unittest.main()

"""Small demo for the secure graph store."""

import json
import tempfile

from .storage import GraphStore


def main() -> None:
    with tempfile.NamedTemporaryFile(suffix=".sqlite3") as db_file:
        store = GraphStore(db_file.name)
        store.create_agent("support_agent", "Support Agent")
        store.create_agent("pii_agent", "PII Agent")
        store.grant_permission("pii_agent", "pii.ssn.read")

        jane = store.upsert_node("person:jane", "person")
        store.set_property("support_agent", "node", jane["id"], "name", "Jane Doe")
        store.set_property("support_agent", "node", jane["id"], "summary", "Jane is a customer.")
        store.set_property("support_agent", "node", jane["id"], "ssn", "123-45-6789")

        print("support_agent context")
        print(json.dumps(store.get_context("support_agent", "person:jane"), indent=2))
        print()
        print("pii_agent context")
        print(json.dumps(store.get_context("pii_agent", "person:jane"), indent=2))


if __name__ == "__main__":
    main()

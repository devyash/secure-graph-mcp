"""MCP server entrypoint for secure graph memory."""

import os
from typing import Any, Dict, Optional

from .storage import GraphStore


def default_db_path() -> str:
    return os.environ.get(
        "SECURE_GRAPH_DB",
        os.path.expanduser("~/.secure-graph-mcp/graph.sqlite3"),
    )


def default_agent_id() -> str:
    return os.environ.get("SECURE_GRAPH_DEFAULT_AGENT_ID", "cursor_default")


def resolve_agent_id(agent_id: Optional[str]) -> str:
    trimmed = (agent_id or "").strip()
    return trimmed or default_agent_id()


def build_server(db_path: Optional[str] = None):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError(
            "The 'mcp' package is required to run the MCP server. "
            "Install this project with: pip install -e ."
        ) from exc

    store = GraphStore(db_path or default_db_path())
    mcp = FastMCP("secure-graph")

    @mcp.tool()
    def create_agent(agent_id: Optional[str] = None, name: Optional[str] = None) -> Dict[str, Any]:
        """Create or update an agent identity."""
        resolved = resolve_agent_id(agent_id)
        return store.create_agent(resolved, name)

    @mcp.tool()
    def grant_permission(
        permission: str,
        agent_id: Optional[str] = None,
    ) -> Dict[str, str]:
        """Grant a field-level permission to an agent."""
        return store.grant_permission(resolve_agent_id(agent_id), permission)

    @mcp.tool()
    def list_permissions(agent_id: Optional[str] = None) -> Dict[str, Any]:
        """List permissions granted to an agent."""
        resolved = resolve_agent_id(agent_id)
        return {"agent_id": resolved, "permissions": store.list_permissions(resolved)}

    @mcp.tool()
    def ingest_graph_mutations(
        mutations: Dict[str, Any],
        agent_id: Optional[str] = None,
        source_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Insert AI-extracted nodes, edges, and privacy-labeled properties."""
        return store.ingest_mutations(resolve_agent_id(agent_id), mutations, source_id)

    @mcp.tool()
    def ingest_conversation(
        conversation_text: str,
        agent_id: Optional[str] = None,
        source_id: Optional[str] = None,
        extracted_mutations: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Extract and insert relevant graph facts from conversation text."""
        return store.ingest_conversation(
            resolve_agent_id(agent_id),
            conversation_text,
            source_id,
            extracted_mutations,
        )

    @mcp.tool()
    def upsert_node(external_key: str, node_type: str) -> Dict[str, Any]:
        """Create or update a graph node."""
        return store.upsert_node(external_key, node_type)

    @mcp.tool()
    def add_edge(
        source_external_key: str,
        target_external_key: str,
        edge_type: str,
        agent_id: Optional[str] = None,
        privacy_level: str = "public",
        required_permission: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create or update a graph edge."""
        return store.add_edge(
            resolve_agent_id(agent_id),
            source_external_key,
            target_external_key,
            edge_type,
            privacy_level,
            required_permission,
        )

    @mcp.tool()
    def set_property(
        entity_type: str,
        entity_id: int,
        key: str,
        value: str,
        agent_id: Optional[str] = None,
        privacy_level: Optional[str] = None,
        required_permission: Optional[str] = None,
        source_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Set a permission-protected property on a node or edge."""
        return store.set_property(
            resolve_agent_id(agent_id),
            entity_type,
            entity_id,
            key,
            value,
            privacy_level,
            required_permission,
            source_id,
        )

    @mcp.tool()
    def get_context(
        external_key: str,
        agent_id: Optional[str] = None,
        depth: int = 1,
        include_redacted: bool = True,
    ) -> Dict[str, Any]:
        """Return permission-filtered graph context for a node."""
        return store.get_context(resolve_agent_id(agent_id), external_key, depth, include_redacted)

    @mcp.tool()
    def semantic_search(
        query: str,
        agent_id: Optional[str] = None,
        limit: int = 10,
        include_redacted: bool = False,
    ) -> Dict[str, Any]:
        """Search allowed graph properties using local semantic ranking."""
        return {
            "results": store.semantic_search(
                resolve_agent_id(agent_id), query, limit, include_redacted
            )
        }

    return mcp


def main() -> None:
    server = build_server()
    server.run()


if __name__ == "__main__":
    main()

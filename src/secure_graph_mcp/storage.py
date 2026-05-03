"""SQLite-backed secure graph storage."""

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .embeddings import cosine_similarity, dumps_vector, embed_text, loads_vector
from .ingestion import extract_basic_mutations
from .policy import can_read_property, classify_edge, classify_property
from .schema import SCHEMA_SQL


class GraphStore:
    """Owns all database access and policy-aware graph operations."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(db_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA_SQL)

    def close(self) -> None:
        self.connection.close()

    def create_agent(self, agent_id: str, name: Optional[str] = None) -> Dict[str, Any]:
        self.connection.execute(
            """
            INSERT INTO agents (id, name)
            VALUES (?, ?)
            ON CONFLICT(id) DO UPDATE SET name = excluded.name
            """,
            (agent_id, name or agent_id),
        )
        self.connection.commit()
        return {"id": agent_id, "name": name or agent_id}

    def grant_permission(self, agent_id: str, permission: str) -> Dict[str, str]:
        self.create_agent(agent_id)
        self.connection.execute(
            """
            INSERT OR IGNORE INTO agent_permissions (agent_id, permission)
            VALUES (?, ?)
            """,
            (agent_id, permission),
        )
        self._audit(agent_id, "grant_permission", "agent", agent_id, {"permission": permission})
        self.connection.commit()
        return {"agent_id": agent_id, "permission": permission}

    def list_permissions(self, agent_id: str) -> List[str]:
        rows = self.connection.execute(
            "SELECT permission FROM agent_permissions WHERE agent_id = ? ORDER BY permission",
            (agent_id,),
        ).fetchall()
        return [row["permission"] for row in rows]

    def upsert_node(self, external_key: str, node_type: str) -> Dict[str, Any]:
        self.connection.execute(
            """
            INSERT INTO nodes (external_key, type)
            VALUES (?, ?)
            ON CONFLICT(external_key) DO UPDATE SET
                type = excluded.type,
                updated_at = CURRENT_TIMESTAMP
            """,
            (external_key, node_type),
        )
        self.connection.commit()
        node = self._get_node_by_external_key(external_key)
        return dict(node)

    def add_edge(
        self,
        agent_id: str,
        source_external_key: str,
        target_external_key: str,
        edge_type: str,
        privacy_level: str = "public",
        required_permission: Optional[str] = None,
    ) -> Dict[str, Any]:
        source = self._get_node_by_external_key(source_external_key)
        target = self._get_node_by_external_key(target_external_key)
        if source is None or target is None:
            raise ValueError("Both source and target nodes must exist before adding an edge.")

        final_edge_level, final_edge_permission = classify_edge(
            edge_type, privacy_level, required_permission
        )

        self.connection.execute(
            """
            INSERT INTO edges (
                source_node_id, target_node_id, type, privacy_level,
                required_permission, created_by_agent_id
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_node_id, target_node_id, type) DO UPDATE SET
                privacy_level = excluded.privacy_level,
                required_permission = excluded.required_permission
            """,
            (source["id"], target["id"], edge_type, final_edge_level, final_edge_permission, agent_id),
        )
        edge = self.connection.execute(
            """
            SELECT * FROM edges
            WHERE source_node_id = ? AND target_node_id = ? AND type = ?
            """,
            (source["id"], target["id"], edge_type),
        ).fetchone()
        self._audit(agent_id, "add_edge", "edge", str(edge["id"]), {"type": edge_type})
        self.connection.commit()
        return self._edge_to_dict(edge)

    def set_property(
        self,
        agent_id: str,
        entity_type: str,
        entity_id: int,
        key: str,
        value: str,
        privacy_level: Optional[str] = None,
        required_permission: Optional[str] = None,
        source_id: Optional[str] = None,
        verified_status: str = "unverified",
    ) -> Dict[str, Any]:
        if entity_type not in {"node", "edge"}:
            raise ValueError("entity_type must be 'node' or 'edge'.")

        final_level, final_permission = classify_property(
            key, value, privacy_level, required_permission
        )

        self.connection.execute(
            """
            INSERT INTO properties (
                entity_type, entity_id, key, value_text, privacy_level,
                required_permission, source_id, created_by_agent_id, verified_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(entity_type, entity_id, key) DO UPDATE SET
                value_text = excluded.value_text,
                privacy_level = excluded.privacy_level,
                required_permission = excluded.required_permission,
                source_id = excluded.source_id,
                verified_status = excluded.verified_status,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                entity_type,
                entity_id,
                key,
                str(value),
                final_level,
                final_permission,
                source_id,
                agent_id,
                verified_status,
            ),
        )
        row = self.connection.execute(
            """
            SELECT * FROM properties
            WHERE entity_type = ? AND entity_id = ? AND key = ?
            """,
            (entity_type, entity_id, key),
        ).fetchone()
        vector = embed_text("%s %s" % (key, value))
        self.connection.execute(
            """
            INSERT INTO embeddings (property_id, vector_json)
            VALUES (?, ?)
            ON CONFLICT(property_id) DO UPDATE SET
                vector_json = excluded.vector_json,
                created_at = CURRENT_TIMESTAMP
            """,
            (row["id"], dumps_vector(vector)),
        )
        self._audit(agent_id, "set_property", entity_type, str(entity_id), {"key": key})
        self.connection.commit()
        return self._property_to_dict(row)

    def ingest_mutations(
        self,
        agent_id: str,
        mutations: Dict[str, Any],
        source_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.create_agent(agent_id)
        created_nodes = []
        created_edges = []

        try:
            with self.connection:
                for node_input in mutations.get("nodes", []):
                    external_key = self._required(node_input, "external_key")
                    node_type = self._required(node_input, "type")
                    node = self._upsert_node_no_commit(external_key, node_type)
                    created_nodes.append(dict(node))
                    for prop in node_input.get("properties", []):
                        self.set_property(
                            agent_id=agent_id,
                            entity_type="node",
                            entity_id=node["id"],
                            key=self._required(prop, "key"),
                            value=self._required(prop, "value"),
                            privacy_level=prop.get("privacy_level"),
                            required_permission=prop.get("required_permission"),
                            source_id=source_id,
                            verified_status=prop.get("verified_status", "unverified"),
                        )

                for edge_input in mutations.get("edges", []):
                    edge = self.add_edge(
                        agent_id=agent_id,
                        source_external_key=self._required(edge_input, "source"),
                        target_external_key=self._required(edge_input, "target"),
                        edge_type=self._required(edge_input, "type"),
                        privacy_level=edge_input.get("privacy_level", "public"),
                        required_permission=edge_input.get("required_permission"),
                    )
                    created_edges.append(edge)
                    for prop in edge_input.get("properties", []):
                        self.set_property(
                            agent_id=agent_id,
                            entity_type="edge",
                            entity_id=edge["id"],
                            key=self._required(prop, "key"),
                            value=self._required(prop, "value"),
                            privacy_level=prop.get("privacy_level"),
                            required_permission=prop.get("required_permission"),
                            source_id=source_id,
                            verified_status=prop.get("verified_status", "unverified"),
                        )

                self._audit(
                    agent_id,
                    "ingest_mutations",
                    None,
                    None,
                    {"nodes": len(created_nodes), "edges": len(created_edges), "source_id": source_id},
                )
        except sqlite3.Error:
            raise

        return {"nodes": created_nodes, "edges": created_edges}

    def ingest_conversation(
        self,
        agent_id: str,
        conversation_text: str,
        source_id: Optional[str] = None,
        extracted_mutations: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        mutations = extracted_mutations or extract_basic_mutations(conversation_text)
        result = self.ingest_mutations(agent_id, mutations, source_id or "conversation")
        self._audit(
            agent_id,
            "ingest_conversation",
            None,
            None,
            {
                "source_id": source_id,
                "used_extracted_mutations": extracted_mutations is not None,
                "text_length": len(conversation_text),
            },
        )
        self.connection.commit()
        return result

    def get_context(
        self,
        agent_id: str,
        external_key: str,
        depth: int = 1,
        include_redacted: bool = True,
    ) -> Dict[str, Any]:
        root = self._get_node_by_external_key(external_key)
        if root is None:
            raise ValueError("Node not found: %s" % external_key)

        permissions = set(self.list_permissions(agent_id))
        node_ids = self._collect_node_ids(root["id"], max(0, depth))
        nodes = []
        for node_id in sorted(node_ids):
            node = self.connection.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
            nodes.append(
                {
                    "id": node["id"],
                    "external_key": node["external_key"],
                    "type": node["type"],
                    "properties": self._allowed_properties(
                        "node", node["id"], permissions, include_redacted
                    ),
                }
            )

        edges = []
        if node_ids:
            placeholders = ",".join("?" for _ in node_ids)
            rows = self.connection.execute(
                """
                SELECT * FROM edges
                WHERE source_node_id IN (%s) OR target_node_id IN (%s)
                ORDER BY id
                """ % (placeholders, placeholders),
                tuple(node_ids) + tuple(node_ids),
            ).fetchall()
            for edge in rows:
                if edge["source_node_id"] in node_ids and edge["target_node_id"] in node_ids:
                    if can_read_property(edge["required_permission"], permissions):
                        edge_dict = self._edge_to_dict(edge)
                        edge_dict["properties"] = self._allowed_properties(
                            "edge", edge["id"], permissions, include_redacted
                        )
                        edges.append(edge_dict)

        self._audit(agent_id, "get_context", "node", str(root["id"]), {"depth": depth})
        self.connection.commit()
        return {"root": dict(root), "nodes": nodes, "edges": edges}

    def semantic_search(
        self,
        agent_id: str,
        query: str,
        limit: int = 10,
        include_redacted: bool = False,
    ) -> List[Dict[str, Any]]:
        permissions = set(self.list_permissions(agent_id))
        query_vector = embed_text(query)
        rows = self.connection.execute(
            """
            SELECT p.*, e.vector_json
            FROM properties p
            JOIN embeddings e ON e.property_id = p.id
            """
        ).fetchall()

        scored = []
        for row in rows:
            allowed = can_read_property(row["required_permission"], permissions)
            if not allowed and not include_redacted:
                continue
            score = cosine_similarity(query_vector, loads_vector(row["vector_json"]))
            if score <= 0:
                continue
            payload = self._property_to_dict(row, redact=not allowed)
            payload["score"] = score
            scored.append(payload)

        scored.sort(key=lambda item: item["score"], reverse=True)
        self._audit(agent_id, "semantic_search", None, None, {"query": query, "limit": limit})
        self.connection.commit()
        return scored[:limit]

    def memory_context_digest(
        self,
        agent_id: str,
        *,
        prompt: Optional[str] = None,
        semantic_limit: int = 12,
        recent_limit: int = 10,
        max_chars: int = 8000,
    ) -> str:
        """Build a compact markdown block for Cursor hooks (automatic memory reads).

        Uses semantic ranking when ``prompt`` is non-empty; always appends recently
        updated properties the agent may read (or see as redacted).
        """
        self.create_agent(agent_id)
        permissions = set(self.list_permissions(agent_id))
        blocks: List[str] = []

        trimmed_prompt = prompt.strip() if isinstance(prompt, str) else ""
        if trimmed_prompt:
            matches = self.semantic_search(
                agent_id,
                trimmed_prompt,
                limit=max(0, semantic_limit),
                include_redacted=True,
            )
            if matches:
                lines = ["### Secure Graph — semantic matches (from your message)", ""]
                for item in matches:
                    anchor = self._property_anchor_label(item["entity_type"], item["entity_id"])
                    score = float(item.get("score") or 0.0)
                    val = str(item.get("value", ""))
                    if len(val) > 240:
                        val = val[:237] + "..."
                    red = " *(redacted)*" if item.get("redacted") else ""
                    lines.append(
                        "- `%s` **%s** = %s — score %.3f%s"
                        % (anchor, item.get("key"), val, score, red)
                    )
                blocks.append("\n".join(lines))

        scan_cap = min(500, max(recent_limit * 40, 80))
        rows = self.connection.execute(
            """
            SELECT p.*
            FROM properties p
            ORDER BY p.updated_at DESC, p.id DESC
            LIMIT ?
            """,
            (scan_cap,),
        ).fetchall()

        recent_lines: List[str] = []
        for row in rows:
            if len(recent_lines) >= recent_limit:
                break
            allowed = can_read_property(row["required_permission"], permissions)
            prop = self._property_to_dict(row, redact=not allowed)
            anchor = self._property_anchor_label(prop["entity_type"], prop["entity_id"])
            val = str(prop["value"])
            if len(val) > 240:
                val = val[:237] + "..."
            tag = " *(redacted)*" if prop.get("redacted") else ""
            recent_lines.append("- `%s` **%s** = %s%s" % (anchor, prop["key"], val, tag))

        if recent_lines:
            blocks.append(
                "### Secure Graph — recently updated properties\n\n" + "\n".join(recent_lines)
            )

        text = "\n\n".join(blocks).strip()
        if max_chars > 20 and len(text) > max_chars:
            text = text[: max_chars - 20].rstrip() + "\n\n...[truncated]..."
        return text

    def _property_anchor_label(self, entity_type: str, entity_id: int) -> str:
        if entity_type == "node":
            row = self.connection.execute(
                "SELECT external_key FROM nodes WHERE id = ?",
                (entity_id,),
            ).fetchone()
            if row:
                return str(row["external_key"])
            return "node:%s" % entity_id
        if entity_type == "edge":
            row = self.connection.execute(
                "SELECT type, source_node_id, target_node_id FROM edges WHERE id = ?",
                (entity_id,),
            ).fetchone()
            if row:
                return "edge:%s:%s->%s" % (row["type"], row["source_node_id"], row["target_node_id"])
            return "edge:%s" % entity_id
        return "%s:%s" % (entity_type, entity_id)

    def get_visual_graph(
        self,
        agent_id: str,
        external_key: str,
        depth: int = 2,
        respect_edge_acl: bool = True,
        include_redacted_edges: bool = True,
        include_redacted_properties: bool = True,
    ) -> Dict[str, Any]:
        """Return a graph shaped for visualization with edge-aware traversal."""
        root = self._get_node_by_external_key(external_key)
        if root is None:
            raise ValueError("Node not found: %s" % external_key)

        permissions = set(self.list_permissions(agent_id))
        if respect_edge_acl:
            node_ids = self._collect_node_ids_respecting_edges(
                root["id"], max(0, depth), permissions
            )
        else:
            node_ids = self._collect_node_ids(root["id"], max(0, depth))

        nodes = []
        for node_id in sorted(node_ids):
            node = self.connection.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
            nodes.append(
                self._node_visual_dict(
                    node,
                    permissions,
                    include_redacted_properties,
                )
            )

        edges = []
        if node_ids:
            placeholders = ",".join("?" for _ in node_ids)
            rows = self.connection.execute(
                """
                SELECT * FROM edges
                WHERE source_node_id IN (%s) OR target_node_id IN (%s)
                ORDER BY id
                """ % (placeholders, placeholders),
                tuple(node_ids) + tuple(node_ids),
            ).fetchall()
            for edge in rows:
                if edge["source_node_id"] not in node_ids or edge["target_node_id"] not in node_ids:
                    continue
                edge_allowed = can_read_property(edge["required_permission"], permissions)
                if not edge_allowed and not include_redacted_edges:
                    continue
                edge_payload = {
                    "id": edge["id"],
                    "source_node_id": edge["source_node_id"],
                    "target_node_id": edge["target_node_id"],
                    "privacy_level": edge["privacy_level"],
                    "required_permission": edge["required_permission"],
                    "redacted": not edge_allowed,
                    "type": edge["type"] if edge_allowed else "[RESTRICTED_EDGE]",
                    "properties": self._allowed_properties(
                        "edge", edge["id"], permissions, include_redacted_properties
                    ),
                }
                edges.append(edge_payload)

        self._audit(
            agent_id,
            "visualize_graph",
            "node",
            str(root["id"]),
            {
                "depth": depth,
                "respect_edge_acl": respect_edge_acl,
                "include_redacted_edges": include_redacted_edges,
            },
        )
        self.connection.commit()
        return {"root": dict(root), "nodes": nodes, "edges": edges}

    def _allowed_properties(
        self,
        entity_type: str,
        entity_id: int,
        permissions: set,
        include_redacted: bool,
    ) -> List[Dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT * FROM properties
            WHERE entity_type = ? AND entity_id = ?
            ORDER BY key
            """,
            (entity_type, entity_id),
        ).fetchall()
        properties = []
        for row in rows:
            allowed = can_read_property(row["required_permission"], permissions)
            if allowed:
                properties.append(self._property_to_dict(row))
            elif include_redacted:
                properties.append(self._property_to_dict(row, redact=True))
        return properties

    def _collect_node_ids(self, root_id: int, depth: int) -> set:
        visited = {root_id}
        frontier = {root_id}
        for _ in range(depth):
            if not frontier:
                break
            placeholders = ",".join("?" for _ in frontier)
            rows = self.connection.execute(
                """
                SELECT source_node_id, target_node_id
                FROM edges
                WHERE source_node_id IN (%s) OR target_node_id IN (%s)
                """ % (placeholders, placeholders),
                tuple(frontier) + tuple(frontier),
            ).fetchall()
            next_frontier = set()
            for row in rows:
                next_frontier.add(row["source_node_id"])
                next_frontier.add(row["target_node_id"])
            next_frontier -= visited
            visited |= next_frontier
            frontier = next_frontier
        return visited

    def _collect_node_ids_respecting_edges(
        self, root_id: int, depth: int, permissions: set
    ) -> set:
        visited = {root_id}
        frontier = {root_id}
        for _ in range(depth):
            if not frontier:
                break
            placeholders = ",".join("?" for _ in frontier)
            rows = self.connection.execute(
                """
                SELECT source_node_id, target_node_id, required_permission
                FROM edges
                WHERE source_node_id IN (%s) OR target_node_id IN (%s)
                """ % (placeholders, placeholders),
                tuple(frontier) + tuple(frontier),
            ).fetchall()
            next_frontier = set()
            for row in rows:
                source = row["source_node_id"]
                target = row["target_node_id"]
                if source in frontier:
                    neighbor = target
                elif target in frontier:
                    neighbor = source
                else:
                    continue

                if not can_read_property(row["required_permission"], permissions):
                    continue

                if neighbor not in visited:
                    next_frontier.add(neighbor)
            visited |= next_frontier
            frontier = next_frontier
        return visited

    def _upsert_node_no_commit(self, external_key: str, node_type: str) -> sqlite3.Row:
        self.connection.execute(
            """
            INSERT INTO nodes (external_key, type)
            VALUES (?, ?)
            ON CONFLICT(external_key) DO UPDATE SET
                type = excluded.type,
                updated_at = CURRENT_TIMESTAMP
            """,
            (external_key, node_type),
        )
        return self._get_node_by_external_key(external_key)

    def _get_node_by_external_key(self, external_key: str) -> Optional[sqlite3.Row]:
        return self.connection.execute(
            "SELECT * FROM nodes WHERE external_key = ?",
            (external_key,),
        ).fetchone()

    def _audit(
        self,
        agent_id: Optional[str],
        action: str,
        entity_type: Optional[str],
        entity_id: Optional[str],
        details: Dict[str, Any],
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO audit_log (agent_id, action, entity_type, entity_id, details_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (agent_id, action, entity_type, entity_id, json.dumps(details, sort_keys=True)),
        )

    @staticmethod
    def _required(data: Dict[str, Any], key: str) -> Any:
        if key not in data or data[key] in (None, ""):
            raise ValueError("Missing required field: %s" % key)
        return data[key]

    @staticmethod
    def _property_to_dict(row: sqlite3.Row, redact: bool = False) -> Dict[str, Any]:
        value = "[REDACTED]" if redact else row["value_text"]
        return {
            "id": row["id"],
            "entity_type": row["entity_type"],
            "entity_id": row["entity_id"],
            "key": row["key"],
            "value": value,
            "privacy_level": row["privacy_level"],
            "required_permission": row["required_permission"],
            "redacted": redact,
            "verified_status": row["verified_status"],
        }

    @staticmethod
    def _edge_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "source_node_id": row["source_node_id"],
            "target_node_id": row["target_node_id"],
            "type": row["type"],
            "privacy_level": row["privacy_level"],
            "required_permission": row["required_permission"],
        }

    def _node_visual_dict(
        self,
        node: sqlite3.Row,
        permissions: set,
        include_redacted_properties: bool,
    ) -> Dict[str, Any]:
        visual_properties = self._allowed_properties(
            "node",
            node["id"],
            permissions,
            include_redacted_properties,
        )
        readable_name = None
        for prop in visual_properties:
            if not prop.get("redacted") and prop["key"].lower() in {"name", "title", "label"}:
                readable_name = prop["value"]
                break

        display_title = readable_name or node["external_key"]
        subtitle = "%s #%s" % (node["type"], node["id"])
        label_lines = []
        label_lines.append(display_title)
        label_lines.append(subtitle)

        return {
            "id": node["id"],
            "external_key": node["external_key"],
            "type": node["type"],
            "label": "\n".join(label_lines),
            "properties": visual_properties,
        }

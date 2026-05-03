"""Conversation ingestion helpers."""

import re
from typing import Any, Dict, List

from .policy import SSN_RE

WORKS_AT_RE = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+(?:works at|is employed by|works for)\s+([A-Z][A-Za-z0-9& .-]+)",
)
POSSESSIVE_SSN_RE = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)'?s?\s+SSN\s+(?:is\s+)?(\d{3}-\d{2}-\d{4})",
    re.IGNORECASE,
)


def extract_basic_mutations(conversation_text: str) -> Dict[str, List[Dict[str, Any]]]:
    """Extract a small deterministic mutation set from plain conversation text.

    This is a safe fallback for the prototype. Production use should let an LLM
    produce structured mutations, then run them through the same validator.
    """
    nodes_by_key = {}
    edges = []

    for match in WORKS_AT_RE.finditer(conversation_text):
        person_name = match.group(1).strip()
        org_name = match.group(2).strip().rstrip(".")
        person_key = "person:%s" % _slug(person_name)
        org_key = "org:%s" % _slug(org_name)
        nodes_by_key.setdefault(
            person_key,
            {"external_key": person_key, "type": "person", "properties": []},
        )
        nodes_by_key.setdefault(
            org_key,
            {"external_key": org_key, "type": "organization", "properties": []},
        )
        _upsert_property(nodes_by_key[person_key]["properties"], "name", person_name)
        _upsert_property(nodes_by_key[org_key]["properties"], "name", org_name)
        edges.append({"source": person_key, "target": org_key, "type": "employed_by"})

    for match in POSSESSIVE_SSN_RE.finditer(conversation_text):
        person_name = match.group(1).strip()
        ssn = match.group(2).strip()
        person_key = "person:%s" % _slug(person_name)
        nodes_by_key.setdefault(
            person_key,
            {"external_key": person_key, "type": "person", "properties": []},
        )
        _upsert_property(nodes_by_key[person_key]["properties"], "name", person_name)
        _upsert_property(nodes_by_key[person_key]["properties"], "ssn", ssn)

    if not nodes_by_key and SSN_RE.search(conversation_text):
        nodes_by_key["conversation:unknown"] = {
            "external_key": "conversation:unknown",
            "type": "conversation",
            "properties": [{"key": "contains_sensitive_data", "value": "true"}],
        }

    return {"nodes": list(nodes_by_key.values()), "edges": edges}


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return cleaned or "unknown"


def _upsert_property(properties: List[Dict[str, Any]], key: str, value: str) -> None:
    for item in properties:
        if item["key"] == key:
            item["value"] = value
            return
    properties.append({"key": key, "value": value})

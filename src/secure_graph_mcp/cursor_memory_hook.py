"""Cursor Composer hooks for automatic Secure Graph read + write.

Invoked via the ``secure-graph-cursor-hook`` console script so ``~/.cursor/hooks.json``
needs only absolute paths to the project's venv (no ``sys.path`` hacks).

Reads ``~/.cursor/mcp.json`` to resolve DB path and defaults when corresponding
environment variables are not set.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .storage import GraphStore

_SESSION_INTRO = """### Secure Graph (auto-read)

Facts below load from local Secure Graph SQLite (same DB as MCP `secure-graph`). Lines marked *(redacted)* require permissions your default agent identity may not have.

You may still call MCP `semantic_search` / `get_context` on `secure-graph` for deeper lookups.
""".strip()


def _sanitize_segment(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned or "unknown"


_PENDING_CACHE: Dict[str, Optional[Path]] = {"root": None}


def _pending_root_dir() -> Path:
    cached = _PENDING_CACHE.get("root")
    if cached is not None:
        return cached

    candidates = [
        Path.home() / ".cursor" / "hooks" / "secure-graph-pending",
        Path(tempfile.gettempdir()) / "secure-graph-cursor-hooks",
    ]
    last_error: Optional[OSError] = None
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            _PENDING_CACHE["root"] = candidate
            return candidate
        except OSError as exc:
            last_error = exc
            continue
    raise RuntimeError("Secure Graph ingest hook cannot find a writable pending directory") from last_error


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default


def _load_mcp_secure_graph_env() -> Tuple[Optional[str], Optional[str]]:
    mcp_path = Path.home() / ".cursor" / "mcp.json"
    if not mcp_path.is_file():
        return None, None
    try:
        data = json.loads(mcp_path.read_text(encoding="utf-8"))
        env = (
            data.get("mcpServers", {})
            .get("secure-graph", {})
            .get("env", {})
        )
        db = env.get("SECURE_GRAPH_DB")
        agent = env.get("SECURE_GRAPH_DEFAULT_AGENT_ID")
        return (str(db) if db else None, str(agent) if agent else None)
    except (OSError, ValueError, TypeError, AttributeError):
        return None, None


def _resolve_db_and_agent() -> Tuple[str, str]:
    mcp_db, mcp_agent = _load_mcp_secure_graph_env()
    db = os.environ.get("SECURE_GRAPH_DB") or mcp_db or os.path.expanduser(
        "~/.secure-graph-mcp/graph.sqlite3"
    )
    agent = os.environ.get("SECURE_GRAPH_DEFAULT_AGENT_ID") or mcp_agent or "cursor_default"
    return db, agent


def _pending_path(conversation_id: str, generation_id: str) -> Path:
    root = _pending_root_dir()
    stem = "%s__%s.json" % (
        _sanitize_segment(conversation_id),
        _sanitize_segment(generation_id),
    )
    return root / stem


def _write_pending_user_prompt(payload: Dict[str, Any]) -> None:
    conversation_id = payload.get("conversation_id")
    generation_id = payload.get("generation_id")
    prompt = payload.get("prompt")
    if not conversation_id or not generation_id or prompt is None:
        return
    path = _pending_path(str(conversation_id), str(generation_id))
    path.write_text(json.dumps({"user_prompt": str(prompt)}), encoding="utf-8")


def _memory_limits() -> Tuple[int, int, int]:
    return (
        _int_env("SECURE_GRAPH_HOOK_SEMANTIC_LIMIT", 12),
        _int_env("SECURE_GRAPH_HOOK_RECENT_LIMIT", 10),
        _int_env("SECURE_GRAPH_HOOK_MAX_CHARS", 8000),
    )


def _append_digest(store: GraphStore, agent_id: str, prompt: Optional[str]) -> str:
    sem_lim, rec_lim, max_chars = _memory_limits()
    return store.memory_context_digest(
        agent_id,
        prompt=prompt,
        semantic_limit=sem_lim,
        recent_limit=rec_lim,
        max_chars=max_chars,
    )


def _handle_session_start(_payload: Dict[str, Any]) -> None:
    db_path, agent_id = _resolve_db_and_agent()
    store = GraphStore(db_path)
    try:
        store.create_agent(agent_id)
        digest = _append_digest(store, agent_id, prompt=None)
        body = _SESSION_INTRO
        if digest.strip():
            body = "%s\n\n%s" % (body, digest.strip())
        print(json.dumps({"additional_context": body.strip()}, separators=(",", ":")))
    finally:
        store.close()


def _handle_before_submit(payload: Dict[str, Any]) -> None:
    output: Dict[str, Any] = {"continue": True}
    db_path, agent_id = _resolve_db_and_agent()
    try:
        store = GraphStore(db_path)
        try:
            store.create_agent(agent_id)
            prompt = payload.get("prompt")
            if isinstance(prompt, str) and prompt.strip():
                digest = _append_digest(store, agent_id, prompt.strip())
                if digest.strip():
                    output["additional_context"] = digest.strip()
        finally:
            store.close()
    except Exception:
        pass

    _write_pending_user_prompt(payload)
    print(json.dumps(output, separators=(",", ":")))


def _handle_after_response(response_data: Dict[str, Any]) -> None:
    conversation_id = response_data.get("conversation_id")
    generation_id = response_data.get("generation_id")
    assistant = response_data.get("text")
    if not conversation_id or not generation_id or assistant is None:
        return
    path = _pending_path(str(conversation_id), str(generation_id))
    if not path.is_file():
        return
    try:
        pending = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        path.unlink(missing_ok=True)
        return

    user_prompt = pending.get("user_prompt")
    if not isinstance(user_prompt, str) or not user_prompt.strip():
        path.unlink(missing_ok=True)
        return

    transcript = "User:\n%s\n\nAssistant:\n%s\n" % (user_prompt.strip(), str(assistant))

    db_path, agent_id = _resolve_db_and_agent()
    store = GraphStore(db_path)
    try:
        store.create_agent(agent_id)
        source_id = "cursor:%s:%s" % (conversation_id, generation_id)
        store.ingest_conversation(agent_id, transcript, source_id=source_id)
    finally:
        store.close()
        path.unlink(missing_ok=True)


def main() -> None:
    raw = sys.stdin.read()
    if not raw.strip():
        print("{}")
        return

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        print("{}")
        return

    event = payload.get("hook_event_name")
    if event == "sessionStart":
        try:
            _handle_session_start(payload)
        except Exception:
            print("{}")
        return

    if event == "beforeSubmitPrompt":
        try:
            _handle_before_submit(payload)
        except Exception:
            _write_pending_user_prompt(payload)
            print(json.dumps({"continue": True}, separators=(",", ":")))
        return

    if event == "afterAgentResponse":
        try:
            _handle_after_response(payload)
        except Exception:
            pass
        print("{}")
        return

    print("{}")


if __name__ == "__main__":
    main()

"""Smoke-check Cursor integration after ``install_cursor_bundle`` or manual setup."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from secure_graph_mcp.install_cursor_bundle import _strip_comment_only_lines


CURSOR_HOME = Path.home() / ".cursor"


def _err(msg: str) -> Tuple[str, str]:
    return ("error", msg)


def _warn(msg: str) -> Tuple[str, str]:
    return ("warn", msg)


def _ok(msg: str) -> Tuple[str, str]:
    return ("ok", msg)


def _hook_command(hooks_payload: Dict[str, object], event: str) -> str | None:
    hooks = hooks_payload.get("hooks")
    if not isinstance(hooks, dict):
        return None
    entries = hooks.get(event)
    if not isinstance(entries, list) or not entries:
        return None
    first = entries[0]
    if not isinstance(first, dict):
        return None
    cmd = first.get("command")
    return cmd if isinstance(cmd, str) and cmd.strip() else None


def _parse_hook_executable(command: str) -> Path:
    parts = command.strip().split()
    return Path(parts[0]).expanduser()


def verify_mcp_config() -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    path = CURSOR_HOME / "mcp.json"
    if not path.is_file():
        out.append(_err("Missing ~/.cursor/mcp.json"))
        return out
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        out.append(_err("Invalid JSON in ~/.cursor/mcp.json: %s" % exc))
        return out
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        out.append(_err("mcp.json: mcpServers must be an object"))
        return out
    sg = servers.get("secure-graph")
    if not isinstance(sg, dict):
        out.append(_err("mcpServers['secure-graph'] is missing"))
        return out

    cmd = sg.get("command")
    args = sg.get("args")
    env = sg.get("env")
    if not isinstance(cmd, str) or not cmd.strip():
        out.append(_err("secure-graph MCP entry needs a command (path to Python)"))
        return out

    py_path = Path(cmd).expanduser()
    out.append(_ok("MCP server entry `secure-graph` present"))
    if not py_path.is_file():
        out.append(_err("MCP command not found at %s" % py_path))
    elif not py_path.stat().st_size:
        out.append(_warn("MCP python path is zero bytes (unexpected): %s" % py_path))
    else:
        out.append(_ok("Interpreter exists: %s" % py_path))

    if isinstance(args, list) and "-m" in args and any(
        isinstance(item, str) and item.strip() == "secure_graph_mcp.mcp_server" for item in args
    ):
        out.append(_ok("MCP args include `-m secure_graph_mcp.mcp_server`"))
    else:
        out.append(_warn("MCP args should include `-m` and `secure_graph_mcp.mcp_server`"))

    if not isinstance(env, dict):
        out.append(_warn('secure-graph MCP entry lacks an `"env"` object'))
        return out

    db = env.get("SECURE_GRAPH_DB")
    if isinstance(db, str) and db.strip():
        out.append(_ok("SECURE_GRAPH_DB set (%s)" % db.strip()))
        dpath = Path(db).expanduser()
        parent = dpath.parent
        if parent.is_dir():
            out.append(_ok("DB directory exists: %s" % parent))
        else:
            out.append(_warn("DB directory missing (will be created on first write?): %s" % parent))
    else:
        out.append(_warn("SECURE_GRAPH_DB missing in MCP env"))

    agent = env.get("SECURE_GRAPH_DEFAULT_AGENT_ID")
    if isinstance(agent, str) and agent.strip():
        out.append(_ok("SECURE_GRAPH_DEFAULT_AGENT_ID=%s" % agent.strip()))

    return out


def verify_hooks_and_cli() -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    path = CURSOR_HOME / "hooks.json"
    if not path.is_file():
        out.append(_err("Missing ~/.cursor/hooks.json"))
        return out
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        out.append(_err("Invalid hooks.json: %s" % exc))
        return out

    required = ("sessionStart", "beforeSubmitPrompt", "afterAgentResponse")
    for event in required:
        cmd = _hook_command(data, event)
        if not cmd:
            out.append(_err("hooks.json missing runnable %s entry" % event))
            continue
        out.append(_ok("%s configured" % event))
        cmd_norm = cmd.replace("\\", "/")
        points_here = (
            "secure-graph-cursor-hook",
            "cursor_memory_hook",
            "secure_graph_ingest_turn",
            "secure_graph_mcp.cursor_memory_hook",
        )
        if not any(marker in cmd_norm for marker in points_here):
            out.append(_warn('%s hook may not chain to Secure Graph (unexpected command)' % event))
            continue

        if "secure-graph-cursor-hook" in cmd_norm and Path(cmd_norm.split()[0]).name.startswith(
            "secure-graph-cursor-hook"
        ):
            exe = _parse_hook_executable(cmd)
            if exe.is_file():
                out.append(_ok("%s Secure Graph CLI exists (%s)" % (event, exe)))
            else:
                out.append(_err("%s Secure Graph CLI missing (%s)" % (event, exe)))
            continue

        exe = _parse_hook_executable(cmd)
        if exe.is_file():
            out.append(_ok('%s invokes Secure Graph hook via launcher "%s"' % (event, exe.name)))
        else:
            out.append(_warn("%s launcher path missing on disk (%s)" % (event, exe)))

    return out


def verify_database_reachable(db_path_str: str) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    path = Path(db_path_str).expanduser().resolve()
    if not path.is_file():
        out.append(_warn("SQLite DB not created yet (%s)" % path))
        return out

    uri = "%s?mode=ro" % path.as_uri()
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        out.append(_err("Cannot open DB read-only %s (%s)" % (path, exc)))
        return out

    try:
        row = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()
        recent = conn.execute(
            """
            SELECT action, COUNT(*) FROM audit_log
            WHERE created_at > datetime('now','-24 hours')
            GROUP BY action ORDER BY COUNT(*) DESC LIMIT 8
            """
        ).fetchall()
    except sqlite3.Error as exc:
        out.append(_err("sqlite read failed (%s)" % exc))
        return out
    finally:
        conn.close()

    count = row[0] if row else 0
    out.append(_ok("SQLite readable; audit_log rows=%s (%s)" % (count, path)))
    if recent:
        lines = "; ".join("%s:%s" % (action, ctr) for action, ctr in recent)
        out.append(_ok("last-24h audit actions: %s" % lines))

    return out


def verify_permissions_allowlist() -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    path = CURSOR_HOME / "permissions.json"
    if not path.is_file():
        out.append(_warn("No ~/.cursor/permissions.json (MCP Auto-Run allowlist relies on Cursor UI)"))
        return out
    raw_text = path.read_text(encoding="utf-8")
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError:
        try:
            raw = json.loads(_strip_comment_only_lines(raw_text))
        except json.JSONDecodeError:
            out.append(_warn("permissions.json is invalid JSON — fix or merge manually"))
            return out
    allowed = raw.get("mcpAllowlist")
    if isinstance(allowed, list) and any(isinstance(item, str) and item.startswith("secure-graph") for item in allowed):
        out.append(_ok("permissions.json mentions secure-graph allowlist patterns"))
        return out
    out.append(
        _warn("permissions.json lacks secure-graph MCP allow patterns (Auto-Run may still prompt)")
    )
    return out


def extract_db_env_from_mcp() -> str | None:
    path = CURSOR_HOME / "mcp.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        return None
    sg = servers.get("secure-graph")
    if not isinstance(sg, dict):
        return None
    env = sg.get("env")
    if isinstance(env, dict):
        raw = env.get("SECURE_GRAPH_DB")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def _print_rows(rows: Iterable[Tuple[str, str]]) -> int:
    errors = 0
    for status, msg in rows:
        if status == "ok":
            print("[ ok ] %s" % msg)
        elif status == "warn":
            print("[warn] %s" % msg)
        else:
            print("[fail] %s" % msg)
            errors += 1
    return errors


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify Secure Graph MCP + Cursor hooks.")
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="Skip SQLite probes (still reads SECURE_GRAPH_DB path from MCP config when present)",
    )
    ns = parser.parse_args(argv)

    print("Checking ~/.cursor for secure-graph MCP + hooks...")
    buckets: List[Tuple[str, str]] = []
    buckets.extend(verify_mcp_config())
    buckets.extend(verify_hooks_and_cli())
    buckets.extend(verify_permissions_allowlist())

    db_path = extract_db_env_from_mcp()
    if db_path and not ns.skip_db:
        buckets.extend(verify_database_reachable(db_path))
    elif not db_path:
        buckets.append(_warn("Could not read SECURE_GRAPH_DB from MCP config — skip DB check"))

    errors = _print_rows(buckets)

    print("\n--- Live Composer signal (manual) ---")
    print(
        "After sending a Composer message you should see new `semantic_search` + `ingest_conversation` rows in "
        "audit_log (see above), and pending files cleared under ~/.cursor/hooks/secure-graph-pending/ "
        "(only briefly while awaiting the assistant)."
    )

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Install Secure Graph into Cursor for local developers (venv + MCP + hooks + allowlist).

Run from a git checkout without pre-install::

    PYTHONPATH=src python3 scripts/install_cursor_bundle.py

Or after editable install::

    secure-graph-install-cursor
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, MutableMapping, Optional, Tuple

_PACKAGE_FILE = Path(__file__).resolve()
_REPO_ROOT_FALLBACK = _PACKAGE_FILE.parents[2]


def _strip_comment_only_lines(raw: str) -> str:
    """Remove Cursor-style full-line ``// ...`` blocks (minimal JSON-C support)."""

    out: List[str] = []
    for line in raw.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("//"):
            continue
        out.append(line)
    return "".join(out)


def _load_maybe_json_with_comment_lines(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(_strip_comment_only_lines(text))
    except json.JSONDecodeError:
        return None


def _dump_json_atomic(path: Path, data: Any) -> None:
    encoded = json.dumps(data, indent=2, sort_keys=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(encoded, encoding="utf-8")
    tmp.replace(path)


def _venv_bin(venv_root: Path) -> Path:
    return venv_root / ("Scripts" if os.name == "nt" else "bin")


def _python_executable() -> Path:
    return Path(sys.executable)


def _hook_cli_path(venv_root: Path) -> Path:
    bindir = _venv_bin(venv_root)
    suffix = ".exe" if os.name == "nt" else ""
    return bindir / ("secure-graph-cursor-hook%s" % suffix)


def _mcp_python_and_args(repo_root: Path, venv_root: Path) -> Tuple[Path, List[str]]:
    py = _venv_bin(venv_root) / ("python.exe" if os.name == "nt" else "python")
    return py, ["-m", "secure_graph_mcp.mcp_server"]


def merge_mcp_servers(
    existing_path: Optional[Path],
    *,
    cwd: Path,
    py: Path,
    args: List[str],
    env: Dict[str, str],
) -> Dict[str, Any]:
    data: Dict[str, Any] = {"mcpServers": {}}
    if existing_path and existing_path.exists():
        try:
            parsed = json.loads(existing_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            data = parsed
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, MutableMapping):
        raise ValueError("mcp.json: mcpServers must be an object")

    # Keep symlinked ``.venv/bin/python`` (do not call ``.resolve()``) so MCP always runs in the venv.
    servers["secure-graph"] = {
        "command": str(py),
        "args": list(args),
        "cwd": str(cwd.resolve()),
        "env": dict(env),
    }
    return data


def merge_permissions_allowlist(
    existing_path: Optional[Path],
    additions: Iterable[str],
) -> Dict[str, Any]:
    allow = {str(x) for x in additions}
    data: Dict[str, Any] = {}
    if existing_path and existing_path.exists():
        parsed = _load_maybe_json_with_comment_lines(existing_path)
        if isinstance(parsed, dict):
            data = parsed
    current = data.get("mcpAllowlist")
    if isinstance(current, list):
        allow.update(str(x) for x in current)
    elif current is not None:
        raise ValueError("permissions.json: mcpAllowlist must be a list or absent")
    data["mcpAllowlist"] = sorted(allow)
    return data


def _ours_hook_command(hook_cli: Path) -> str:
    return str(hook_cli.resolve())


def merge_hooks(
    existing_path: Optional[Path],
    hook_cli: Path,
) -> Dict[str, Any]:
    data: Dict[str, Any] = {"version": 1, "hooks": {}}
    if existing_path and existing_path.exists():
        try:
            parsed = json.loads(existing_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            data = parsed
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, MutableMapping):
        raise ValueError("hooks.json: hooks must be an object")

    cmd = _ours_hook_command(hook_cli)
    desired: Dict[str, List[Dict[str, Any]]] = {
        "sessionStart": [{"command": cmd, "timeout": 60}],
        "beforeSubmitPrompt": [{"command": cmd, "timeout": 30}],
        "afterAgentResponse": [{"command": cmd, "timeout": 120}],
    }

    marker = "secure-graph-cursor-hook"

    for event, definitions in desired.items():
        existing = hooks.get(event)
        if not isinstance(existing, list):
            existing = []
        kept: List[Dict[str, Any]] = []
        for entry in existing:
            if not isinstance(entry, dict):
                continue
            c = entry.get("command")
            if isinstance(c, str) and marker in c:
                continue
            kept.append(entry)
        hooks[event] = definitions + kept

    return data


def _run(cmd: List[str], *, cwd: Path, dry_run: bool) -> int:
    print("+", " ".join(cmd))
    if dry_run:
        return 0
    result = subprocess.run(cmd, cwd=str(cwd), check=False)
    return int(result.returncode)


def _detect_repo_root(explicit: Optional[Path]) -> Path:
    if explicit is not None:
        return explicit.resolve()
    try:
        out = subprocess.check_output(
            ["git", "-C", str(_REPO_ROOT_FALLBACK), "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return Path(out).resolve()
    except (OSError, subprocess.CalledProcessError, FileNotFoundError):
        return _REPO_ROOT_FALLBACK.resolve()


def install(
    *,
    repo_root: Path,
    venv_root: Path,
    db_path: Path,
    agent_id: str,
    dry_run: bool,
    skip_venv: bool,
    base_python: Optional[Path],
) -> int:
    repo_root = repo_root.resolve()
    venv_root = venv_root.resolve()
    db_path = db_path.expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    py_base = base_python or _python_executable()

    if not skip_venv:
        if not venv_root.exists():
            rc = _run([str(py_base), "-m", "venv", str(venv_root)], cwd=repo_root, dry_run=dry_run)
            if rc != 0:
                return rc
    else:
        venv_root = repo_root

    venv_py = _venv_bin(venv_root) / ("python.exe" if os.name == "nt" else "python")
    if not skip_venv and not dry_run and not venv_py.exists():
        print("Missing venv python at %s" % venv_py, file=sys.stderr)
        return 1

    pip_cmd = [str(venv_py), "-m", "pip", "install", "-U", "pip", "setuptools", "wheel"]
    rc = _run(pip_cmd, cwd=repo_root, dry_run=dry_run)
    if rc != 0:
        return rc

    rc = _run([str(venv_py), "-m", "pip", "install", "-e", str(repo_root)], cwd=repo_root, dry_run=dry_run)
    if rc != 0:
        return rc

    hook_cli = _hook_cli_path(venv_root)
    if not dry_run and not hook_cli.exists():
        print(
            "Hook CLI not found at %s after install. Check console_scripts in pyproject.toml."
            % hook_cli,
            file=sys.stderr,
        )
        return 1

    mcp_py, mcp_args = _mcp_python_and_args(repo_root, venv_root)
    mcp_env = {
        "SECURE_GRAPH_DB": str(db_path),
        "SECURE_GRAPH_DEFAULT_AGENT_ID": agent_id,
    }

    cursor_dir = Path.home() / ".cursor"
    mcp_path = cursor_dir / "mcp.json"
    perms_path = cursor_dir / "permissions.json"
    hooks_path = cursor_dir / "hooks.json"

    mcp_data = merge_mcp_servers(
        mcp_path if mcp_path.exists() else None,
        cwd=repo_root,
        py=mcp_py,
        args=mcp_args,
        env=mcp_env,
    )
    perms_data = merge_permissions_allowlist(
        perms_path if perms_path.exists() else None,
        additions=["secure-graph:*"],
    )
    hooks_data = merge_hooks(
        hooks_path if hooks_path.exists() else None,
        hook_cli=hook_cli,
    )

    print("\n--- ~/.cursor/mcp.json (secure-graph entry) ---")
    print(json.dumps(mcp_data["mcpServers"]["secure-graph"], indent=2))

    print("\n--- ~/.cursor/hooks.json (secure-graph hooks) ---")
    for ev in ("sessionStart", "beforeSubmitPrompt", "afterAgentResponse"):
        print("%s -> %s" % (ev, hooks_data["hooks"][ev][0]["command"]))

    print("\n--- ~/.cursor/permissions.json ---")
    print("mcpAllowlist includes secure-graph:*:", "secure-graph:*" in perms_data.get("mcpAllowlist", []))

    if dry_run:
        print("\nDry-run: no files written.")
        return 0

    for original, suffix in ((mcp_path, "mcp.json.bak"), (hooks_path, "hooks.json.bak")):
        if original.exists():
            shutil.copy2(original, original.parent / suffix)

    if perms_path.exists():
        shutil.copy2(perms_path, perms_path.parent / "permissions.json.bak")

    _dump_json_atomic(mcp_path, mcp_data)
    _dump_json_atomic(hooks_path, hooks_data)
    _dump_json_atomic(perms_path, perms_data)

    rule_src = repo_root / "cursor-user-rule-secure-graph.md"
    print(
        "\nDone. Paste text from `%s` into Cursor → Settings → Rules → User Rules."
        % rule_src.name
    )
    print(
        "Note: permissions.json is rewritten as plain JSON (line // comments are dropped). "
        "A backup was saved as permissions.json.bak when the file already existed."
    )
    print(
        "Reminder: mcpAllowlist replaces the in-app MCP allowlist when present — add patterns for "
        "other MCP servers you use (e.g. figma:*)."
    )
    print("\nRestart Cursor once so MCP + Hooks reload.")
    print("Smoke-check: run `secure-graph-verify-cursor` (exit code 0 == no failures).")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    default_db = Path("~/.secure-graph-mcp/graph.sqlite3").expanduser()

    p = argparse.ArgumentParser(description="Install Secure Graph MCP + Cursor hooks bundle.")
    p.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="Path to secure-graph-mcp checkout (default: git root from this package)",
    )
    p.add_argument(
        "--venv",
        type=Path,
        default=None,
        help="venv directory (default: <repo>/.venv)",
    )
    p.add_argument("--db", type=Path, default=default_db, help="SQLite DB path")
    p.add_argument("--agent-id", default="cursor_default", help="SECURE_GRAPH_DEFAULT_AGENT_ID default")
    p.add_argument("--dry-run", action="store_true", help="Print actions without modifying files")
    p.add_argument("--skip-venv", action="store_true", help="Use --skip-venv only for advanced debugging")
    p.add_argument(
        "--python",
        type=Path,
        default=None,
        help="Interpreter used to create the venv (default: current Python)",
    )
    ns = p.parse_args(argv)

    repo_root = _detect_repo_root(ns.repo)
    venv_root = ns.venv.resolve() if ns.venv is not None else (repo_root / ".venv")

    return install(
        repo_root=repo_root,
        venv_root=venv_root,
        db_path=ns.db,
        agent_id=ns.agent_id,
        dry_run=ns.dry_run,
        skip_venv=ns.skip_venv,
        base_python=ns.python,
    )


if __name__ == "__main__":
    sys.exit(main())

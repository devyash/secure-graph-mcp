#!/usr/bin/env bash
# One-command install for Secure Graph MCP + Cursor (macOS / Linux with git + python3).
#
# Already in a clone of this repo:
#   ./scripts/one_command_install.sh
#   ./scripts/one_command_install.sh --dry-run
#
# From anywhere — set YOUR repo URL (branch in URL path must exist, e.g. main):
#   export SECURE_GRAPH_MCP_REPO_URL=https://github.com/OWNER/secure-graph-mcp.git
#   curl -fsSL "$SECURE_GRAPH_MCP_REPO_URL/raw/main/scripts/one_command_install.sh" | bash

set -euo pipefail

have() { command -v "$1" >/dev/null 2>&1; }

if ! have python3; then
  echo "Need python3 on PATH." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ -f "$REPO_ROOT/scripts/install_cursor_bundle.py" ]]; then
  echo "==> Using existing checkout: $REPO_ROOT"
  exec python3 "$REPO_ROOT/scripts/install_cursor_bundle.py" "$@"
fi

if ! have git; then
  echo "Need git to clone the repository, or run this script from inside a secure-graph-mcp checkout." >&2
  exit 1
fi

REPO_URL="${SECURE_GRAPH_MCP_REPO_URL:-}"
if [[ -z "$REPO_URL" ]]; then
  echo "Not inside a checkout. Set SECURE_GRAPH_MCP_REPO_URL to the git URL, e.g.:" >&2
  echo "  export SECURE_GRAPH_MCP_REPO_URL=https://github.com/YOU/secure-graph-mcp.git" >&2
  echo "  curl -fsSL .../one_command_install.sh | bash" >&2
  exit 1
fi

TMP="${TMPDIR:-/tmp}/secure-graph-mcp-install.$$"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

echo "==> Cloning $REPO_URL (shallow)..."
git clone --depth 1 "$REPO_URL" "$TMP/repo"
echo "==> Running Cursor bundle installer..."
python3 "$TMP/repo/scripts/install_cursor_bundle.py" "$@"
echo "==> Done. Restart Cursor; run: secure-graph-verify-cursor"

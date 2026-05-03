#!/usr/bin/env bash
# One-command install for Secure Graph MCP + Cursor (macOS / Linux with git + python3).
#
# Already in a clone of this repo:
#   ./scripts/one_command_install.sh
#   ./scripts/one_command_install.sh --dry-run
#
# From anywhere (persistent clone ~/.local/share/secure-graph-mcp — override SECURE_GRAPH_MCP_CLONE_DIR):
#   curl -fsSL https://github.com/devyash/secure-graph-mcp/raw/main/scripts/one_command_install.sh | bash

set -euo pipefail

UPSTREAM="${SECURE_GRAPH_MCP_REPO_URL:-https://github.com/devyash/secure-graph-mcp.git}"
DEST="${SECURE_GRAPH_MCP_CLONE_DIR:-$HOME/.local/share/secure-graph-mcp}"

have() { command -v "$1" >/dev/null 2>&1; }

if ! have python3; then
  echo "Need python3 on PATH." >&2
  exit 1
fi

piped_install=false
_src="${BASH_SOURCE[0]}"
case "$_src" in
  - | "" | "/dev/stdin") piped_install=true ;;
  /dev/fd/* | /proc/self/fd/*) piped_install=true ;;
esac

if [[ "$piped_install" == false ]]; then
  SCRIPT_DIR="$(cd "$(dirname "$_src")" && pwd)"
  REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
  if [[ -f "$REPO_ROOT/scripts/install_cursor_bundle.py" ]]; then
    echo "==> Using existing checkout: $REPO_ROOT"
    exec python3 "$REPO_ROOT/scripts/install_cursor_bundle.py" "$@"
  fi
fi

if ! have git; then
  echo "Need git to clone the repository, or run this script from inside the secure-graph-mcp checkout." >&2
  exit 1
fi

mkdir -p "$(dirname "$DEST")"

clone_or_refresh() {
  if [[ -d "$DEST/.git" ]]; then
    echo "==> Updating clone: $DEST"
    git -C "$DEST" remote set-url origin "$UPSTREAM" 2>/dev/null || true
    git -C "$DEST" pull --ff-only
    return
  fi

  echo "==> Cloning $UPSTREAM → $DEST ..."
  if git clone --depth 1 --branch main "$UPSTREAM" "$DEST" 2>/dev/null; then
    return
  fi
  git clone --depth 1 --branch master "$UPSTREAM" "$DEST"
}

clone_or_refresh

echo "==> Running Cursor bundle installer..."
python3 "$DEST/scripts/install_cursor_bundle.py" --repo "$DEST" "$@"
echo "==> Done. Restart Cursor."
echo "==> Code + .venv : $DEST"
echo "==> Smoke test   : $DEST/.venv/bin/secure-graph-verify-cursor"

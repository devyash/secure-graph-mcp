#!/usr/bin/env python3
"""Bootstrap wrapper: run the installer before the package is installed.

Usage (from git checkout)::

    python3 scripts/install_cursor_bundle.py

This prepends ``src/`` onto ``sys.path`` so ``secure_graph_mcp.install_cursor_bundle`` can be imported.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from secure_graph_mcp.install_cursor_bundle import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())

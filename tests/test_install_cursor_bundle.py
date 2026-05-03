import json
import tempfile
import unittest
from pathlib import Path

from secure_graph_mcp.install_cursor_bundle import (
    merge_hooks,
    merge_mcp_servers,
    merge_permissions_allowlist,
)


class CursorBundleMergeTest(unittest.TestCase):
    def test_merge_mcp_servers_preserves_other_servers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            mcp_path = Path(td) / "mcp.json"
            mcp_path.write_text(
                json.dumps({"mcpServers": {"Other": {"command": "noop"}}}),
                encoding="utf-8",
            )
            out = merge_mcp_servers(
                mcp_path,
                cwd=Path("/repo"),
                py=Path("/repo/.venv/bin/python"),
                args=["-m", "secure_graph_mcp.mcp_server"],
                env={"SECURE_GRAPH_DB": "/g.db", "SECURE_GRAPH_DEFAULT_AGENT_ID": "cursor_default"},
            )
        self.assertIn("Other", out["mcpServers"])
        self.assertIn("secure-graph", out["mcpServers"])
        self.assertEqual(out["mcpServers"]["secure-graph"]["args"], ["-m", "secure_graph_mcp.mcp_server"])

    def test_merge_permissions_unions_existing_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "permissions.json"
            path.write_text(json.dumps({"mcpAllowlist": ["figma:*"]}), encoding="utf-8")
            out = merge_permissions_allowlist(path, additions=["secure-graph:*"])
        self.assertIn("figma:*", out["mcpAllowlist"])
        self.assertIn("secure-graph:*", out["mcpAllowlist"])

    def test_merge_hooks_replaces_prior_secure_graph_entries(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            hooks_path = Path(td) / "hooks.json"
            hook_cli_old = Path(td) / "bin" / "secure-graph-cursor-hook"
            hook_cli_new = Path(td) / "bin2" / "secure-graph-cursor-hook"
            hooks_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "hooks": {
                            "beforeSubmitPrompt": [
                                {"command": str(hook_cli_old)},
                                {"command": "lint.sh"},
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            out = merge_hooks(hooks_path, hook_cli_new)

        cmds = [entry["command"] for entry in out["hooks"]["beforeSubmitPrompt"]]
        self.assertEqual(cmds.count(str(hook_cli_new.resolve())), 1)
        self.assertIn("lint.sh", cmds)
        self.assertNotIn(str(hook_cli_old), cmds)


if __name__ == "__main__":
    unittest.main()

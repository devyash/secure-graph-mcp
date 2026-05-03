import json
import sys
import tempfile
import unittest
from pathlib import Path

from secure_graph_mcp.storage import GraphStore
from secure_graph_mcp import verify_cursor_setup as vc


def _errors(messages):
    return [msg for flag, msg in messages if flag == "error"]


class VerifyCursorSetupTest(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_home = vc.CURSOR_HOME
        self._tmp = tempfile.TemporaryDirectory()
        vc.CURSOR_HOME = Path(self._tmp.name)

    def tearDown(self) -> None:
        vc.CURSOR_HOME = self._saved_home
        self._tmp.cleanup()

    def test_checks_pass_with_fake_cursor_config_and_db(self) -> None:
        hook_path = vc.CURSOR_HOME / "mock-bin" / "secure-graph-cursor-hook"
        hook_path.parent.mkdir(parents=True)
        hook_path.write_text("", encoding="utf-8")
        hook_path.chmod(0o755)

        db_file = Path(self._tmp.name) / "probe.sqlite3"
        GraphStore(str(db_file)).close()

        mcp_blob = {
            "mcpServers": {
                "secure-graph": {
                    "command": sys.executable,
                    "args": ["-m", "secure_graph_mcp.mcp_server"],
                    "cwd": str(Path(__file__).resolve().parent.parent),
                    "env": {
                        "SECURE_GRAPH_DB": str(db_file),
                        "SECURE_GRAPH_DEFAULT_AGENT_ID": "cursor_default",
                    },
                }
            }
        }
        (vc.CURSOR_HOME / "mcp.json").write_text(json.dumps(mcp_blob), encoding="utf-8")

        hooks_blob = {
            "version": 1,
            "hooks": {
                "sessionStart": [{"command": str(hook_path), "timeout": 60}],
                "beforeSubmitPrompt": [{"command": str(hook_path), "timeout": 30}],
                "afterAgentResponse": [{"command": str(hook_path), "timeout": 120}],
            },
        }
        (vc.CURSOR_HOME / "hooks.json").write_text(json.dumps(hooks_blob), encoding="utf-8")

        perm_blob = {"mcpAllowlist": ["secure-graph:*"]}
        (vc.CURSOR_HOME / "permissions.json").write_text(json.dumps(perm_blob), encoding="utf-8")

        mcp_issues = _errors(vc.verify_mcp_config())
        hook_issues = _errors(vc.verify_hooks_and_cli())
        perm_issues = _errors(vc.verify_permissions_allowlist())
        db_issues = _errors(vc.verify_database_reachable(str(db_file)))

        self.assertEqual(mcp_issues, [])
        self.assertEqual(hook_issues, [])
        self.assertEqual(perm_issues, [])
        self.assertEqual(db_issues, [])


if __name__ == "__main__":
    unittest.main()

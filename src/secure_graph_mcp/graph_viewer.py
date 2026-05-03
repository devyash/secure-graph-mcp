"""Local HTML/JS viewer for Secure Graph MCP."""

from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse

from .mcp_server import default_db_path
from .storage import GraphStore


def _truthy(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_static(name: str) -> bytes:
    here = Path(__file__).resolve().parent / "viewer_static"
    return (here / name).read_bytes()


class ViewerHandler(BaseHTTPRequestHandler):
    server_version = "SecureGraphViewer/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_headers(self, status: int = 200, content_type: str = "text/plain") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _send_json(self, payload: Dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path

        if route in {"/", "/index.html"}:
            html = load_static("index.html")
            self._send_headers(200, "text/html; charset=utf-8")
            self.wfile.write(html)
            return

        if route == "/viewer.js":
            js = load_static("viewer.js")
            self._send_headers(200, "application/javascript; charset=utf-8")
            self.wfile.write(js)
            return

        if route == "/viewer.css":
            css = load_static("viewer.css")
            self._send_headers(200, "text/css; charset=utf-8")
            self.wfile.write(css)
            return

        if route != "/api/graph":
            self._send_headers(404, "text/plain; charset=utf-8")
            self.wfile.write(b"Not found")
            return

        params = parse_qs(parsed.query)
        agent_id = (params.get("agent_id") or [""])[0]
        external_key = (params.get("root") or [""])[0]
        depth_raw = (params.get("depth") or ["2"])[0]

        ignore_edge_acl = _truthy((params.get("ignore_edge_acl") or ["0"])[0])
        hide_redacted_edges = _truthy((params.get("hide_redacted_edges") or ["0"])[0])

        if not agent_id or not external_key:
            self._send_json({"error": "agent_id and root are required"}, status=400)
            return

        try:
            depth = int(depth_raw)
        except ValueError:
            self._send_json({"error": "depth must be an integer"}, status=400)
            return

        store: GraphStore = self.server.store  # type: ignore[attr-defined]
        try:
            graph = store.get_visual_graph(
                agent_id=agent_id,
                external_key=external_key,
                depth=depth,
                respect_edge_acl=not ignore_edge_acl,
                include_redacted_edges=not hide_redacted_edges,
                include_redacted_properties=True,
            )
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=404)
            return

        self._send_json(graph)


class ViewerServer(ThreadingHTTPServer):
    def __init__(self, server_address, handler_class, store: GraphStore):
        super().__init__(server_address, handler_class)
        self.store = store


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Secure Graph local viewer.")
    parser.add_argument("--host", default=os.environ.get("SECURE_GRAPH_VIEWER_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("SECURE_GRAPH_VIEWER_PORT", "8765")),
    )
    parser.add_argument("--db", default=os.environ.get("SECURE_GRAPH_DB", default_db_path()))
    args = parser.parse_args()

    store = GraphStore(args.db)
    httpd = ViewerServer((args.host, args.port), ViewerHandler, store)
    print("Secure graph viewer listening on http://%s:%s" % (args.host, args.port), flush=True)
    print(
        "Open with query params like /?agent_id=support_agent&root=person:jane&depth=2",
        flush=True,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        store.close()


if __name__ == "__main__":
    main()

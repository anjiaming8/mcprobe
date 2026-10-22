from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from mcprobe.client import StreamableHttpClient, _parse_sse, extract_tool_text


class McpHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    calls: list[dict] = []

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        self.calls.append(
            {
                "payload": payload,
                "authorization": self.headers.get("Authorization"),
                "session": self.headers.get("Mcp-Session-Id"),
                "protocol": self.headers.get("MCP-Protocol-Version"),
            }
        )
        method = payload.get("method")

        if method == "notifications/initialized":
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if method == "initialize":
            body = {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {
                    "protocolVersion": "2025-06-18",
                    "serverInfo": {"name": "fake-mcd", "version": "9.9.9"},
                    "capabilities": {"tools": {}},
                },
            }
            self._json_response(body, session="fake-session")
            return

        if method == "tools/list":
            body = {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {
                    "tools": [
                        {
                            "name": "now-time-info",
                            "description": "clock",
                            "inputSchema": {"type": "object"},
                        }
                    ]
                },
            }
            self._json_response(body)
            return

        if method == "tools/call":
            body = {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {
                    "content": [{"type": "text", "text": "2026-10-22T12:00:00+08:00"}],
                    "isError": False,
                },
            }
            self._json_response(body)
            return

        self.send_error(400)

    def _json_response(
        self, body: dict, *, session: str | None = None
    ) -> None:
        encoded = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        if session:
            self.send_header("Mcp-Session-Id", session)
        self.end_headers()
        self.wfile.write(encoded)


class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        McpHandler.calls = []
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), McpHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.endpoint = f"http://127.0.0.1:{cls.server.server_port}/mcp"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def test_full_handshake_and_tool_call(self) -> None:
        client = StreamableHttpClient(
            self.endpoint,
            "secret-token",
            timeout=3,
            protocol_versions=("2025-06-18",),
        )

        initialized = client.initialize()
        tools = client.list_tools()
        called = client.call_tool("now-time-info")

        self.assertEqual(initialized.result["serverInfo"]["name"], "fake-mcd")
        self.assertEqual(client.session_id, "fake-session")
        self.assertEqual(client.protocol_version, "2025-06-18")
        self.assertEqual(tools.result["tools"][0]["name"], "now-time-info")
        self.assertIn("2026-10-22", extract_tool_text(called.result))
        self.assertTrue(
            all(
                call["authorization"] == "Bearer secret-token"
                for call in McpHandler.calls
            )
        )
        self.assertTrue(
            all(
                call["session"] == "fake-session"
                for call in McpHandler.calls
                if call["payload"].get("method") != "initialize"
            )
        )
        self.assertTrue(
            all(
                call["protocol"] == "2025-06-18"
                for call in McpHandler.calls
                if call["payload"].get("method")
                not in {"initialize", "notifications/initialized"}
            )
        )

    def test_sse_parser_handles_multiline_json(self) -> None:
        raw = (
            "event: message\n"
            'data: {"jsonrpc":"2.0",\n'
            'data: "id":1,"result":{"ok":true}}\n\n'
        )

        events = _parse_sse(raw)

        self.assertEqual(events[0]["id"], 1)
        self.assertTrue(events[0]["result"]["ok"])


if __name__ == "__main__":
    unittest.main()

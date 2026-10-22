"""Minimal, dependency-free Streamable HTTP MCP client.

This client intentionally implements only the methods needed by McProbe:
initialize, notifications/initialized, tools/list, and tools/call.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")


class McpTransportError(RuntimeError):
    """A transport or JSON-RPC failure with enough context for diagnostics."""

    def __init__(
        self,
        kind: str,
        message: str,
        *,
        status: int | None = None,
        request_id: int | str | None = None,
        latency_ms: float | None = None,
        payload: Any = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.status = status
        self.request_id = request_id
        self.latency_ms = latency_ms
        self.payload = payload


@dataclass(slots=True)
class RpcResponse:
    result: dict[str, Any]
    headers: dict[str, str]
    latency_ms: float


def _parse_sse(raw: str) -> list[dict[str, Any]]:
    """Parse JSON payloads from a finite SSE response body."""

    events: list[dict[str, Any]] = []
    data_lines: list[str] = []

    def flush() -> None:
        if not data_lines:
            return
        data = "\n".join(data_lines).strip()
        data_lines.clear()
        if not data or data == "[DONE]":
            return
        try:
            decoded = json.loads(data)
        except json.JSONDecodeError:
            return
        if isinstance(decoded, dict):
            events.append(decoded)

    for line in raw.splitlines():
        if not line:
            flush()
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    flush()
    return events


def _decode_body(content_type: str, body: bytes) -> list[dict[str, Any]]:
    if not body:
        return []
    text = body.decode("utf-8", errors="replace").strip()
    if "text/event-stream" in content_type.lower():
        return _parse_sse(text)
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise McpTransportError(
            "decode",
            f"响应不是合法 JSON：{exc.msg}",
            payload=text[:500],
        ) from exc
    if isinstance(decoded, list):
        return [item for item in decoded if isinstance(item, dict)]
    if isinstance(decoded, dict):
        return [decoded]
    raise McpTransportError("decode", "响应 JSON 不是对象或数组")


class StreamableHttpClient:
    """A deliberately small Streamable HTTP JSON-RPC client."""

    def __init__(
        self,
        endpoint: str,
        token: str,
        *,
        timeout: float = 15.0,
        protocol_versions: tuple[str, ...] = DEFAULT_PROTOCOL_VERSIONS,
        user_agent: str = "McProbe/0.1.0",
    ) -> None:
        self.endpoint = endpoint
        self._token = token
        self.timeout = timeout
        self.protocol_versions = protocol_versions
        self.user_agent = user_agent
        self.session_id: str | None = None
        self.protocol_version: str | None = None
        self.server_info: dict[str, Any] = {}
        self.capabilities: dict[str, Any] = {}
        self._next_id = 1

    def _headers(self, *, initialized: bool) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": self.user_agent,
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if initialized and self.protocol_version:
            headers["MCP-Protocol-Version"] = self.protocol_version
        return headers

    def _post(
        self,
        payload: dict[str, Any],
        *,
        initialized: bool = False,
    ) -> tuple[list[dict[str, Any]], dict[str, str], float]:
        started = time.perf_counter()
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(initialized=initialized),
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read()
                elapsed = (time.perf_counter() - started) * 1000
                headers = {key.lower(): value for key, value in response.headers.items()}
                events = _decode_body(headers.get("content-type", ""), body)
        except urllib.error.HTTPError as exc:
            body = exc.read()
            elapsed = (time.perf_counter() - started) * 1000
            content_type = exc.headers.get("Content-Type", "") if exc.headers else ""
            try:
                events = _decode_body(content_type, body)
            except McpTransportError:
                events = []
            message = _extract_error_message(events) or body.decode(
                "utf-8", errors="replace"
            )[:300]
            kind = {
                401: "auth",
                403: "auth",
                404: "endpoint",
                429: "rate_limit",
            }.get(exc.code, "http")
            raise McpTransportError(
                kind,
                f"HTTP {exc.code}: {message}",
                status=exc.code,
                request_id=payload.get("id"),
                latency_ms=round(elapsed, 1),
                payload=events or None,
            ) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            elapsed = (time.perf_counter() - started) * 1000
            reason = getattr(exc, "reason", exc)
            raise McpTransportError(
                "network",
                f"连接失败：{reason}",
                request_id=payload.get("id"),
                latency_ms=round(elapsed, 1),
            ) from exc

        request_id = payload.get("id")
        matched = _match_response(events, request_id)
        if matched and "error" in matched:
            error = matched["error"]
            code = error.get("code") if isinstance(error, dict) else None
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise McpTransportError(
                "jsonrpc",
                f"JSON-RPC 错误 {code}: {message}",
                request_id=request_id,
                latency_ms=round(elapsed, 1),
                payload=matched,
            )
        if request_id is not None and matched is None:
            raise McpTransportError(
                "protocol",
                "响应中没有与请求 ID 对应的 JSON-RPC 结果",
                request_id=request_id,
                latency_ms=round(elapsed, 1),
                payload=events,
            )
        return events, headers, elapsed

    def initialize(self) -> RpcResponse:
        last_error: McpTransportError | None = None
        for version in self.protocol_versions:
            self.session_id = None
            request_id = self._new_id()
            payload = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": version,
                    "capabilities": {},
                    "clientInfo": {"name": "mcprobe", "version": "0.1.0"},
                },
            }
            try:
                events, headers, elapsed = self._post(payload)
            except McpTransportError as exc:
                last_error = exc
                if exc.status in {400, 406, 426}:
                    continue
                raise

            matched = _match_response(events, request_id)
            if matched is None:
                last_error = McpTransportError(
                    "protocol",
                    "初始化响应缺少 result",
                    request_id=request_id,
                )
                continue

            result = matched.get("result")
            if not isinstance(result, dict):
                last_error = McpTransportError(
                    "protocol",
                    "初始化 result 不是对象",
                    payload=matched,
                )
                continue

            self.protocol_version = str(result.get("protocolVersion") or version)
            self.server_info = result.get("serverInfo") or {}
            self.capabilities = result.get("capabilities") or {}
            self.session_id = headers.get("mcp-session-id")

            # Complete the MCP initialization handshake.
            self._notify_initialized()
            return RpcResponse(result=result, headers=headers, latency_ms=elapsed)

        raise last_error or McpTransportError("protocol", "所有协议版本初始化均失败")

    def _notify_initialized(self) -> None:
        payload = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        }
        try:
            self._post(payload, initialized=True)
        except McpTransportError as exc:
            # Some gateways acknowledge notifications with an empty 202/204.
            # If they return JSON-RPC id=null, tolerate the common variants.
            if exc.kind == "protocol" and exc.request_id is None:
                return
            if exc.status in {202, 204}:
                return
            raise

    def list_tools(self) -> RpcResponse:
        return self._call_rpc("tools/list", {})

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> RpcResponse:
        return self._call_rpc(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
        )

    def _call_rpc(self, method: str, params: dict[str, Any]) -> RpcResponse:
        request_id = self._new_id()
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        events, headers, elapsed = self._post(payload, initialized=True)
        matched = _match_response(events, request_id)
        if matched is None or not isinstance(matched.get("result"), dict):
            raise McpTransportError(
                "protocol",
                f"{method} 响应缺少 result",
                request_id=request_id,
                latency_ms=round(elapsed, 1),
                payload=events,
            )
        return RpcResponse(
            result=matched["result"],
            headers=headers,
            latency_ms=elapsed,
        )

    def _new_id(self) -> int:
        request_id = self._next_id
        self._next_id += 1
        return request_id


def _match_response(
    events: list[dict[str, Any]], request_id: int | str | None
) -> dict[str, Any] | None:
    for event in events:
        if event.get("id") == request_id:
            return event
    return None


def _extract_error_message(events: list[dict[str, Any]]) -> str:
    for event in events:
        error = event.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
    return ""


def extract_tool_text(result: dict[str, Any]) -> str:
    """Extract human-readable text from an MCP tools/call result."""

    content = result.get("content")
    if not isinstance(content, list):
        return ""
    chunks: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "\n".join(chunks).strip()

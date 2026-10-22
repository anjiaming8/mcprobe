"""Deterministic offline capability data for demos and regression tests."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .baseline import EXPECTED_TOOLS


def healthy_fixture() -> dict[str, Any]:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return {
        "fixture_version": 1,
        "label": "McProbe 离线健康样例",
        "captured_at": now,
        "endpoint": "https://mcp.mcd.cn",
        "server": {
            "protocolVersion": "2025-06-18",
            "serverInfo": {"name": "mcd-mcp", "version": "1.0.0"},
            "capabilities": {"tools": {"listChanged": True}},
        },
        "session_present": True,
        "initialize_latency_ms": 42.7,
        "tools_list_latency_ms": 31.2,
        "tools": [
            {
                "name": name,
                "description": "",
                "inputSchema": {"type": "object", "properties": {}},
            }
            for name in EXPECTED_TOOLS
        ],
        "probes": {
            "now-time-info": {
                "ok": True,
                "latency_ms": 28.4,
                "text": "当前时间：2026-10-22T11:24:00+08:00",
            },
            "campaign-calendar": {
                "ok": True,
                "latency_ms": 35.9,
                "text": "活动日历读取成功（离线样例，不代表实时活动）",
            },
            "query-my-account": {
                "ok": True,
                "latency_ms": 44.1,
                "text": "账户读取成功（内容已按隐私模式隐藏）",
            },
        },
    }


def missing_tool_fixture() -> dict[str, Any]:
    fixture = healthy_fixture()
    fixture["label"] = "McProbe 工具契约漂移样例"
    fixture["tools"] = [
        tool for tool in fixture["tools"] if tool["name"] != "now-time-info"
    ]
    fixture["tools"].append(
        {
            "name": "experimental-tool",
            "description": "A future tool not in the audited baseline",
            "inputSchema": {"type": "object", "properties": {}},
        }
    )
    fixture["probes"].pop("now-time-info", None)
    return fixture

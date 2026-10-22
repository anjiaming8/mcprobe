"""Live and fixture-based diagnostics for McDonald's China MCP."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .baseline import (
    ACCOUNT_READ_TOOLS,
    CORE_READ_TOOLS,
    EXPECTED_TOOL_COUNT,
    EXPECTED_TOOLS,
    tool_risk,
)
from .client import McpTransportError, StreamableHttpClient, extract_tool_text
from .fixtures import healthy_fixture
from .models import Check, Probe, ToolInfo, aggregate_status


DEFAULT_ENDPOINT = "https://mcp.mcd.cn"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _short(text: str, limit: int = 180) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def _redact(text: str, secret: str | None) -> str:
    clean = text or ""
    if secret:
        clean = clean.replace(secret, "[REDACTED_TOKEN]")
    clean = re.sub(
        r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s\"']+",
        r"\1[REDACTED_TOKEN]",
        clean,
    )
    clean = re.sub(r"\b[A-Za-z0-9_-]{40,}\b", "[REDACTED_LONG_VALUE]", clean)
    return clean


def _schema_fingerprint(tools: list[dict[str, Any]]) -> str:
    canonical = [
        {
            "name": tool.get("name", ""),
            "inputSchema": tool.get("inputSchema", {}),
        }
        for tool in sorted(tools, key=lambda item: str(item.get("name", "")))
    ]
    encoded = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _suite_from_components(
    *,
    mode: str,
    endpoint: str,
    server: dict[str, Any],
    tools_raw: list[dict[str, Any]],
    probe_rows: list[Probe],
    base_checks: list[Check],
    account_enabled: bool,
    token_configured: bool,
    session_present: bool,
    initialize_latency_ms: float | None,
    tools_list_latency_ms: float | None,
    fixture_label: str | None = None,
) -> dict[str, Any]:
    tools = [
        ToolInfo(
            name=str(item.get("name", "")),
            description=str(item.get("description", "")),
            risk=tool_risk(str(item.get("name", ""))),
            has_input_schema=isinstance(item.get("inputSchema"), dict),
        )
        for item in tools_raw
        if item.get("name")
    ]
    tool_names = {tool.name for tool in tools}
    expected = set(EXPECTED_TOOLS)
    missing = sorted(expected - tool_names)
    unexpected = sorted(tool_names - expected)

    checks = list(base_checks)
    checks.append(
        Check(
            check_id="tools.names",
            title="35 项工具契约",
            status="fail" if missing else ("warn" if unexpected else "pass"),
            summary=(
                f"发现 {len(tools)} 项工具；缺少 {len(missing)} 项，新增 {len(unexpected)} 项"
            ),
            detail=(
                f"缺少：{', '.join(missing) if missing else '无'}；"
                f"未登记新增：{', '.join(unexpected) if unexpected else '无'}"
            ),
            evidence={
                "expected_count": EXPECTED_TOOL_COUNT,
                "actual_count": len(tools),
                "missing": missing,
                "unexpected": unexpected,
                "schema_fingerprint": _schema_fingerprint(tools_raw),
            },
        )
    )

    failed_probes = [probe for probe in probe_rows if probe.status == "fail"]
    smoke_status = (
        "fail" if failed_probes else ("info" if not probe_rows else "pass")
    )
    checks.append(
        Check(
            check_id="tools.read_only_smoke",
            title="只读冒烟测试",
            status=smoke_status,
            summary=(
                "未执行（连接或工具发现阶段未通过）"
                if not probe_rows
                else f"{len(probe_rows) - len(failed_probes)}/{len(probe_rows)} 项只读调用通过"
            ),
            detail=(
                "失败："
                + ", ".join(probe.name for probe in failed_probes)
                if failed_probes
                else (
                    "缺少可用探针，不能据此判定读取能力正常"
                    if not probe_rows
                    else "关键读取路径可正常返回"
                )
            ),
        )
    )

    write_count = sum(1 for tool in tools if tool.risk == "write")
    personal_count = sum(1 for tool in tools if tool.risk == "personal")
    checks.append(
        Check(
            check_id="safety.write_guard",
            title="写入隔离",
            status="pass",
            summary=f"{write_count} 项可写工具仅做契约检查，本次未调用",
            detail=f"{personal_count} 项个人数据工具默认不在报告中展示原始内容",
            evidence={"write_tools_never_called": True},
        )
    )

    if not account_enabled:
        checks.append(
            Check(
                check_id="account.optional",
                title="个人账户检查",
                status="info",
                summary="默认关闭；需要时加 --account，仅判断能否读取",
                detail="McProbe 不保存积分余额、订单、券码或地址内容",
            )
        )
    elif token_configured:
        checks.append(
            Check(
                check_id="account.enabled",
                title="个人账户检查",
                status="pass",
                summary="已启用隐私模式账户只读检查",
                detail="仅记录成功/失败和延迟，不展示账户原始返回",
            )
        )

    overall = aggregate_status(checks)
    exit_code = {"pass": 0, "warn": 1, "fail": 2}[overall]
    result = {
        "schema_version": 1,
        "tool": "McProbe",
        "version": "0.1.0",
        "generated_at": _now_iso(),
        "mode": mode,
        "fixture_label": fixture_label,
        "overall_status": overall,
        "exit_code": exit_code,
        "source": {
            "endpoint": endpoint,
            "token_configured": token_configured,
            "session_present": session_present,
        },
        "server": server,
        "timings_ms": {
            "initialize": initialize_latency_ms,
            "tools_list": tools_list_latency_ms,
            "probes": {
                probe.name: probe.latency_ms
                for probe in probe_rows
                if probe.latency_ms is not None
            },
        },
        "contract": {
            "expected_count": EXPECTED_TOOL_COUNT,
            "actual_count": len(tools),
            "missing": missing,
            "unexpected": unexpected,
            "schema_fingerprint": _schema_fingerprint(tools_raw),
        },
        "checks": [check.to_dict() for check in checks],
        "probes": [probe.to_dict() for probe in probe_rows],
        "tools": [tool.to_dict() for tool in tools],
        "privacy": {
            "writes_executed": 0,
            "raw_account_content_in_report": False,
            "token_in_report": False,
        },
        "disclaimer": (
            "McProbe 是参赛者开发的诊断工具，非麦当劳官方产品。"
            "诊断结果只反映本次网络与凭证状态，不代表服务永久可用性。"
        ),
    }
    return result


def _check_from_transport_error(error: McpTransportError, secret: str | None) -> Check:
    message = _redact(error.message, secret)
    mapping = {
        "auth": (
            "Token / 权限",
            "鉴权失败：重新在 open.mcd.cn/mcp 登录、激活并复制 Token",
        ),
        "rate_limit": (
            "请求频率",
            "触发 429：等待一分钟后重试，避免并发请求",
        ),
        "network": (
            "网络 / TLS",
            "无法连接：检查代理、DNS、防火墙与 https://mcp.mcd.cn",
        ),
        "endpoint": (
            "接入地址",
            "404：确认客户端使用 Streamable HTTP 与 https://mcp.mcd.cn",
        ),
        "protocol": (
            "MCP 协议",
            "协议不兼容：升级 MCP 客户端，或选择支持 Streamable HTTP 的宿主",
        ),
        "jsonrpc": (
            "MCP 业务错误",
            "服务端返回 JSON-RPC 错误：保留错误码并检查工具参数或账户权限",
        ),
        "decode": ("响应格式", "服务端响应无法解析：检查网关是否篡改了 SSE/JSON"),
    }
    title, action = mapping.get(
        error.kind, ("未知连接错误", "保留报告并向 MCP 服务方反馈")
    )
    return Check(
        check_id="transport.connect",
        title=title,
        status="fail",
        summary=message,
        detail=action,
        latency_ms=error.latency_ms,
        evidence={"kind": error.kind, "http_status": error.status},
    )


def run_live(
    *,
    endpoint: str = DEFAULT_ENDPOINT,
    token: str | None = None,
    timeout: float = 15.0,
    account: bool = False,
) -> dict[str, Any]:
    token = token or os.environ.get("MCD_MCP_TOKEN", "")
    base_checks: list[Check] = []
    if not token:
        return _suite_from_components(
            mode="live",
            endpoint=endpoint,
            server={},
            tools_raw=[],
            probe_rows=[],
            base_checks=[
                Check(
                    check_id="auth.token_configured",
                    title="Token 配置",
                    status="fail",
                    summary="未找到 MCD_MCP_TOKEN",
                    detail=(
                        "先打开 https://open.mcd.cn/mcp 登录并激活 Token，"
                        "再在当前 PowerShell 中设置环境变量"
                    ),
                )
            ],
            account_enabled=account,
            token_configured=False,
            session_present=False,
            initialize_latency_ms=None,
            tools_list_latency_ms=None,
        )

    client = StreamableHttpClient(endpoint, token, timeout=timeout)
    try:
        init_response = client.initialize()
    except McpTransportError as exc:
        return _suite_from_components(
            mode="live",
            endpoint=endpoint,
            server={},
            tools_raw=[],
            probe_rows=[],
            base_checks=[
                Check(
                    check_id="auth.token_configured",
                    title="Token 配置",
                    status="pass",
                    summary="Token 已配置（内容不写入报告）",
                ),
                _check_from_transport_error(exc, token),
            ],
            account_enabled=account,
            token_configured=True,
            session_present=False,
            initialize_latency_ms=exc.latency_ms,
            tools_list_latency_ms=None,
        )

    base_checks.extend(
        [
            Check(
                check_id="auth.token_configured",
                title="Token 配置",
                status="pass",
                summary="Token 已配置并完成初始化（内容不写入报告）",
            ),
            Check(
                check_id="transport.connect",
                title="Streamable HTTP",
                status="pass",
                summary="初始化握手成功",
                latency_ms=round(init_response.latency_ms, 1),
            ),
            Check(
                check_id="protocol.negotiated",
                title="MCP 协议",
                status="pass",
                summary=f"协商版本 {client.protocol_version}",
                evidence={
                    "protocol_version": client.protocol_version,
                    "capabilities": client.capabilities,
                },
            ),
            Check(
                check_id="session.header",
                title="会话连续性",
                status="pass" if client.session_id else "info",
                summary=(
                    "服务端返回 Mcp-Session-Id"
                    if client.session_id
                    else "服务端未启用显式会话头（协议允许）"
                ),
                evidence={"session_header_present": bool(client.session_id)},
            ),
        ]
    )

    try:
        tools_response = client.list_tools()
    except McpTransportError as exc:
        base_checks.append(_check_from_transport_error(exc, token))
        return _suite_from_components(
            mode="live",
            endpoint=endpoint,
            server={
                "protocolVersion": client.protocol_version,
                "serverInfo": client.server_info,
                "capabilities": client.capabilities,
            },
            tools_raw=[],
            probe_rows=[],
            base_checks=base_checks,
            account_enabled=account,
            token_configured=True,
            session_present=bool(client.session_id),
            initialize_latency_ms=round(init_response.latency_ms, 1),
            tools_list_latency_ms=exc.latency_ms,
        )

    tools_raw = tools_response.result.get("tools") or []
    base_checks.append(
        Check(
            check_id="tools.list",
            title="工具发现",
            status="pass",
            summary=f"tools/list 返回 {len(tools_raw)} 项工具",
            latency_ms=round(tools_response.latency_ms, 1),
        )
    )

    probe_names = list(CORE_READ_TOOLS)
    if account:
        probe_names.extend(ACCOUNT_READ_TOOLS)
    available_names = {
        str(tool.get("name")) for tool in tools_raw if isinstance(tool, dict)
    }
    probe_rows: list[Probe] = []
    for name in probe_names:
        if name not in available_names:
            probe_rows.append(
                Probe(
                    name=name,
                    status="fail",
                    latency_ms=None,
                    summary="工具不存在，无法执行只读探针",
                )
            )
            continue
        try:
            response = client.call_tool(name, {})
            text = extract_tool_text(response.result)
            is_error = response.result.get("isError") is True
            probe_rows.append(
                Probe(
                    name=name,
                    status="fail" if is_error else "pass",
                    latency_ms=round(response.latency_ms, 1),
                    summary=(
                        "工具返回 isError=true"
                        if is_error
                        else "调用成功并返回可解析内容"
                    ),
                    text_preview=(
                        "内容已隐藏（隐私模式）"
                        if name in ACCOUNT_READ_TOOLS
                        else _short(_redact(text, token))
                    ),
                )
            )
        except McpTransportError as exc:
            probe_rows.append(
                Probe(
                    name=name,
                    status="fail",
                    latency_ms=exc.latency_ms,
                    summary=_short(_redact(exc.message, token)),
                )
            )

    return _suite_from_components(
        mode="live",
        endpoint=endpoint,
        server={
            "protocolVersion": client.protocol_version,
            "serverInfo": client.server_info,
            "capabilities": client.capabilities,
        },
        tools_raw=tools_raw,
        probe_rows=probe_rows,
        base_checks=base_checks,
        account_enabled=account,
        token_configured=True,
        session_present=bool(client.session_id),
        initialize_latency_ms=round(init_response.latency_ms, 1),
        tools_list_latency_ms=round(tools_response.latency_ms, 1),
    )


def load_fixture(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return healthy_fixture()
    with Path(path).open("r", encoding="utf-8") as handle:
        fixture = json.load(handle)
    if not isinstance(fixture, dict):
        raise ValueError("fixture 根节点必须是 JSON 对象")
    return fixture


def run_fixture(
    fixture: dict[str, Any],
    *,
    account: bool = False,
) -> dict[str, Any]:
    server = fixture.get("server") or {}
    tools_raw = fixture.get("tools") or []
    raw_probes = fixture.get("probes") or {}
    probe_rows: list[Probe] = []
    for name in CORE_READ_TOOLS:
        item = raw_probes.get(name)
        if not isinstance(item, dict):
            continue
        probe_rows.append(
            Probe(
                name=name,
                status="pass" if item.get("ok") else "fail",
                latency_ms=item.get("latency_ms"),
                summary=(
                    "离线样例调用成功"
                    if item.get("ok")
                    else "离线样例调用失败"
                ),
                text_preview=_short(str(item.get("text", ""))),
            )
        )
    if account:
        for name in ACCOUNT_READ_TOOLS:
            item = raw_probes.get(name)
            if not isinstance(item, dict):
                probe_rows.append(
                    Probe(
                        name=name,
                        status="fail",
                        latency_ms=None,
                        summary="fixture 中没有该只读探针",
                    )
                )
                continue
            probe_rows.append(
                Probe(
                    name=name,
                    status="pass" if item.get("ok") else "fail",
                    latency_ms=item.get("latency_ms"),
                    summary=(
                        "离线样例调用成功（内容已隐藏）"
                        if item.get("ok")
                        else "离线样例调用失败"
                    ),
                    text_preview="内容已隐藏（隐私模式）",
                )
            )

    return _suite_from_components(
        mode="fixture",
        endpoint=str(fixture.get("endpoint") or DEFAULT_ENDPOINT),
        server=server,
        tools_raw=tools_raw,
        probe_rows=probe_rows,
        base_checks=[
            Check(
                check_id="fixture.loaded",
                title="离线样例",
                status="pass",
                summary=str(fixture.get("label") or "fixture 已加载"),
                detail="未连接麦当劳服务，结果只用于验证诊断链路",
                evidence={"captured_at": fixture.get("captured_at")},
            ),
            Check(
                check_id="transport.connect",
                title="Streamable HTTP",
                status="info",
                summary="离线模式未发起网络请求",
                latency_ms=fixture.get("initialize_latency_ms"),
            ),
            Check(
                check_id="protocol.negotiated",
                title="MCP 协议",
                status="pass"
                if server.get("protocolVersion")
                else "fail",
                summary=f"样例协议版本 {server.get('protocolVersion', '缺失')}",
                evidence={"simulated": True},
            ),
            Check(
                check_id="session.header",
                title="会话连续性",
                status="pass"
                if fixture.get("session_present")
                else "info",
                summary=(
                    "样例包含 Mcp-Session-Id"
                    if fixture.get("session_present")
                    else "样例未模拟显式会话头"
                ),
                evidence={"simulated": True},
            ),
            Check(
                check_id="tools.list",
                title="工具发现",
                status="pass",
                summary=f"样例 tools/list 返回 {len(tools_raw)} 项工具",
                latency_ms=fixture.get("tools_list_latency_ms"),
            ),
        ],
        account_enabled=account,
        token_configured=False,
        session_present=bool(fixture.get("session_present")),
        initialize_latency_ms=fixture.get("initialize_latency_ms"),
        tools_list_latency_ms=fixture.get("tools_list_latency_ms"),
        fixture_label=str(fixture.get("label") or ""),
    )


def write_json(result: dict[str, Any], path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def terminal_summary(result: dict[str, Any]) -> str:
    status_text = {
        "pass": "PASS",
        "warn": "WARN",
        "fail": "FAIL",
    }.get(result["overall_status"], "UNKNOWN")
    lines = [
        f"McProbe {status_text}  mode={result['mode']}",
        (
            f"server={result.get('server', {}).get('serverInfo', {}).get('name', '-')} "
            f"{result.get('server', {}).get('serverInfo', {}).get('version', '')}"
        ),
        (
            f"tools={result['contract']['actual_count']}/"
            f"{result['contract']['expected_count']} "
            f"missing={len(result['contract']['missing'])} "
            f"new={len(result['contract']['unexpected'])}"
        ),
    ]
    for check in result["checks"]:
        marker = {
            "pass": "[PASS]",
            "info": "[INFO]",
            "warn": "[WARN]",
            "fail": "[FAIL]",
        }.get(check["status"], "?")
        latency = (
            f" ({check['latency_ms']:.1f} ms)"
            if check.get("latency_ms") is not None
            else ""
        )
        lines.append(f"{marker} {check['title']}: {check['summary']}{latency}")
    lines.append("writes=0  token_in_report=no")
    return "\n".join(lines)

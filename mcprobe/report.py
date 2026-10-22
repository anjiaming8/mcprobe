"""Generate a self-contained, print-friendly HTML diagnostic report."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


STATUS_LABEL = {
    "pass": "通过",
    "warn": "注意",
    "fail": "失败",
    "info": "信息",
}

RISK_LABEL = {
    "read": "只读",
    "personal": "个人数据",
    "write": "可写",
}


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _render_checks(checks: list[dict[str, Any]]) -> str:
    cards: list[str] = []
    for check in checks:
        status = check.get("status", "info")
        latency = check.get("latency_ms")
        latency_html = (
            f'<span class="latency">{float(latency):.1f} ms</span>'
            if latency is not None
            else ""
        )
        detail = (
            f'<p class="detail">{_e(check["detail"])}</p>'
            if check.get("detail")
            else ""
        )
        cards.append(
            f"""
            <article class="check check-{_e(status)}">
              <div class="check-head">
                <span class="status status-{_e(status)}">{_e(STATUS_LABEL.get(status, status))}</span>
                <h3>{_e(check.get("title", check.get("check_id", "")))}</h3>
                {latency_html}
              </div>
              <p>{_e(check.get("summary", ""))}</p>
              {detail}
            </article>
            """
        )
    return "\n".join(cards)


def _render_probes(probes: list[dict[str, Any]]) -> str:
    if not probes:
        return '<p class="empty">本次没有执行只读探针。</p>'
    rows: list[str] = []
    for probe in probes:
        latency = probe.get("latency_ms")
        rows.append(
            f"""
            <tr>
              <td><code>{_e(probe.get("name"))}</code></td>
              <td><span class="status status-{_e(probe.get("status"))}">{_e(STATUS_LABEL.get(probe.get("status"), probe.get("status")))}</span></td>
              <td>{_e(probe.get("summary"))}</td>
              <td class="num">{"" if latency is None else f"{float(latency):.1f} ms"}</td>
            </tr>
            """
        )
    return f"""
    <div class="table-wrap">
      <table>
        <thead><tr><th>探针</th><th>结果</th><th>说明</th><th>延迟</th></tr></thead>
        <tbody>{"".join(rows)}</tbody>
      </table>
    </div>
    """


def _render_tools(tools: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for tool in tools:
        risk = tool.get("risk", "read")
        rows.append(
            f"""
            <tr>
              <td><code>{_e(tool.get("name"))}</code></td>
              <td><span class="risk risk-{_e(risk)}">{_e(RISK_LABEL.get(risk, risk))}</span></td>
              <td>{_e(tool.get("description"))[:240]}</td>
              <td class="num">{"是" if tool.get("has_input_schema") else "否"}</td>
            </tr>
            """
        )
    return f"""
    <details>
      <summary>展开 {len(tools)} 项工具契约</summary>
      <div class="table-wrap">
        <table>
          <thead><tr><th>工具</th><th>风险</th><th>用途</th><th>有 schema</th></tr></thead>
          <tbody>{"".join(rows)}</tbody>
        </table>
      </div>
    </details>
    """


def render_html(result: dict[str, Any]) -> str:
    overall = result.get("overall_status", "fail")
    server = result.get("server") or {}
    server_info = server.get("serverInfo") or {}
    source = result.get("source") or {}
    contract = result.get("contract") or {}
    timings = result.get("timings_ms") or {}
    token_state = "已配置" if source.get("token_configured") else "未配置"
    session_state = "已返回" if source.get("session_present") else "未返回"
    mode_label = "离线样例" if result.get("mode") == "fixture" else "实时连接"
    headline = {
        "pass": "连接与契约正常",
        "warn": "能连上，但有变化需要留意",
        "fail": "诊断未通过，先按动作项修复",
    }.get(overall, "诊断状态未知")
    missing = contract.get("missing") or []
    unexpected = contract.get("unexpected") or []
    json_blob = html.escape(
        json.dumps(result, ensure_ascii=False, indent=2),
        quote=False,
    )

    document = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>McProbe · 麦当劳 MCP 体检报告</title>
  <style>
    :root {{
      --ink: #171717;
      --paper: #fffdf5;
      --panel: #ffffff;
      --yellow: #ffc72c;
      --red: #c92a2a;
      --green: #1e7a4c;
      --blue: #225ea8;
      --muted: #68645d;
      --line: #ded8c9;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at 92% 5%, rgba(255,199,44,.34), transparent 24rem),
        var(--paper);
      font: 16px/1.6 "Microsoft YaHei", "PingFang SC", system-ui, sans-serif;
    }}
    .page {{ width: min(1120px, calc(100% - 32px)); margin: 0 auto; padding: 36px 0 56px; }}
    .eyebrow {{
      display: inline-flex; align-items: center; gap: 10px;
      font: 700 13px/1 ui-monospace, "Cascadia Code", monospace;
      letter-spacing: .14em; text-transform: uppercase;
    }}
    .eyebrow::before {{ content: ""; width: 28px; height: 5px; background: var(--yellow); }}
    h1 {{ margin: 16px 0 8px; font-size: clamp(36px, 7vw, 76px); line-height: .98; letter-spacing: -.05em; }}
    h1 span {{ color: var(--muted); }}
    .lede {{ max-width: 760px; margin: 18px 0 28px; font-size: 19px; color: var(--muted); }}
    .hero {{
      position: relative; overflow: hidden; padding: clamp(24px, 5vw, 52px);
      border: 2px solid var(--ink); border-radius: 28px; background: var(--panel);
      box-shadow: 10px 10px 0 var(--yellow);
    }}
    .hero::after {{
      content: "1024"; position: absolute; right: -12px; bottom: -38px;
      color: rgba(255,199,44,.28); font: 900 150px/1 ui-monospace, monospace; z-index: 0;
    }}
    .hero > * {{ position: relative; z-index: 1; }}
    .status-big {{
      display: inline-flex; padding: 8px 14px; border-radius: 999px;
      border: 2px solid currentColor; font-weight: 800; letter-spacing: .08em;
    }}
    .status-big-pass {{ color: var(--green); background: #e7f6ee; }}
    .status-big-warn {{ color: #8a5a00; background: #fff2ca; }}
    .status-big-fail {{ color: var(--red); background: #ffe9e9; }}
    .meta-grid {{
      display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px; margin: 28px 0;
    }}
    .meta {{
      min-height: 112px; padding: 16px; border: 1px solid var(--line);
      border-radius: 16px; background: #fffefa;
    }}
    .meta small {{ display: block; color: var(--muted); font-size: 12px; }}
    .meta strong {{ display: block; margin-top: 8px; font-size: 19px; line-height: 1.25; overflow-wrap: anywhere; }}
    h2 {{ margin: 42px 0 16px; font-size: 28px; letter-spacing: -.02em; }}
    .checks {{ display: grid; gap: 12px; }}
    .check {{
      padding: 18px 20px; border: 1px solid var(--line); border-left-width: 6px;
      border-radius: 14px; background: var(--panel);
    }}
    .check-pass {{ border-left-color: var(--green); }}
    .check-warn {{ border-left-color: #d18b00; }}
    .check-fail {{ border-left-color: var(--red); }}
    .check-info {{ border-left-color: var(--blue); }}
    .check-head {{ display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }}
    .check h3 {{ flex: 1; margin: 0; font-size: 18px; }}
    .check p {{ margin: 8px 0 0; }}
    .check .detail {{ color: var(--muted); font-size: 14px; }}
    .status {{
      display: inline-flex; border-radius: 999px; padding: 3px 9px;
      font-size: 12px; font-weight: 800; white-space: nowrap;
    }}
    .status-pass {{ color: var(--green); background: #e7f6ee; }}
    .status-warn {{ color: #835400; background: #fff2ca; }}
    .status-fail {{ color: var(--red); background: #ffe9e9; }}
    .status-info {{ color: var(--blue); background: #e8f1ff; }}
    .latency {{ color: var(--muted); font: 13px ui-monospace, monospace; }}
    .table-wrap {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 14px; background: var(--panel); }}
    table {{ width: 100%; border-collapse: collapse; min-width: 680px; }}
    th, td {{ padding: 12px 14px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
    th {{ background: #f7f2e5; font-size: 13px; }}
    tr:last-child td {{ border-bottom: 0; }}
    td.num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
    code {{ font-family: "Cascadia Code", Consolas, monospace; font-size: 13px; }}
    .risk {{ display: inline-block; padding: 1px 7px; border-radius: 999px; font-size: 12px; font-weight: 700; }}
    .risk-read {{ color: var(--green); background: #e7f6ee; }}
    .risk-personal {{ color: #835400; background: #fff2ca; }}
    .risk-write {{ color: var(--red); background: #ffe9e9; }}
    details {{ margin-top: 16px; }}
    summary {{ cursor: pointer; padding: 12px 0; font-weight: 700; }}
    .contract-strip {{
      display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px; margin: 18px 0;
    }}
    .contract-item {{ padding: 16px; border-radius: 14px; background: #f7f2e5; }}
    .contract-item b {{ display: block; font-size: 28px; }}
    .contract-item span {{ color: var(--muted); }}
    .privacy {{
      margin-top: 22px; padding: 18px 20px; border: 1px dashed #7b7465;
      border-radius: 14px; background: #faf8f0;
    }}
    .privacy strong {{ color: var(--green); }}
    .foot {{ margin-top: 46px; padding-top: 20px; border-top: 1px solid var(--line); color: var(--muted); font-size: 13px; }}
    .json {{ margin-top: 16px; padding: 18px; overflow: auto; max-height: 520px; border-radius: 14px; background: #171717; color: #f7f2e5; font-size: 12px; }}
    .empty {{ color: var(--muted); }}
    @media (max-width: 760px) {{
      .page {{ width: min(100% - 20px, 1120px); padding-top: 18px; }}
      .hero {{ border-radius: 20px; box-shadow: 6px 6px 0 var(--yellow); }}
      .meta-grid, .contract-strip {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .meta {{ min-height: 96px; }}
    }}
    @media print {{
      body {{ background: #fff; }}
      .page {{ width: 100%; padding: 0; }}
      .hero {{ box-shadow: none; }}
      details > * {{ display: block; }}
      .json, details:last-of-type {{ display: none; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <div class="eyebrow">McProbe / MCP readiness report</div>
      <h1>麦门接口<br><span>体检报告</span></h1>
      <p class="lede">{_e(headline)}。本页只记录本次握手、工具契约和只读冒烟结果；不包含 Token、订单、地址、券码或积分内容。</p>
      <span class="status-big status-big-{_e(overall)}">{_e(overall.upper())} · {_e(STATUS_LABEL.get(overall, overall))}</span>
      <div class="meta-grid">
        <div class="meta"><small>模式</small><strong>{_e(mode_label)}</strong></div>
        <div class="meta"><small>Server</small><strong>{_e(server_info.get("name", "未知"))} {_e(server_info.get("version", ""))}</strong></div>
        <div class="meta"><small>MCP 协议</small><strong>{_e(server.get("protocolVersion", "未协商"))}</strong></div>
        <div class="meta"><small>生成时间</small><strong>{_e(result.get("generated_at", ""))}</strong></div>
      </div>
    </section>

    <h2>先看结论</h2>
    <div class="checks">{_render_checks(result.get("checks") or [])}</div>

    <h2>契约快照</h2>
    <div class="contract-strip">
      <div class="contract-item"><b>{_e(contract.get("actual_count", 0))}/{_e(contract.get("expected_count", 35))}</b><span>发现 / 基线工具</span></div>
      <div class="contract-item"><b>{_e(len(missing))}</b><span>缺失工具</span></div>
      <div class="contract-item"><b>{_e(len(unexpected))}</b><span>新增未登记工具</span></div>
    </div>
    <p class="empty">Schema 指纹：<code>{_e(contract.get("schema_fingerprint", "-"))}</code>。这个值用于判断工具定义是否在两次体检之间变化，不包含凭证。</p>

    <h2>只读冒烟</h2>
    {_render_probes(result.get("probes") or [])}

    <h2>工具契约</h2>
    {_render_tools(result.get("tools") or [])}

    <div class="privacy">
      <strong>隐私边界</strong>
      <p>Token：{_e(token_state)} · 会话头：{_e(session_state)} · 写入调用：0 次 · 原始账户内容：未写入报告。<br>
      实时体检才代表当前服务状态；离线样例仅用于验证诊断逻辑。</p>
    </div>

    <details>
      <summary>查看完整 JSON 结果</summary>
      <pre class="json">{json_blob}</pre>
    </details>

    <footer class="foot">
      <p>{_e(result.get("disclaimer", ""))}</p>
      <p>McProbe 0.1.0 · Streamable HTTP · 麦当劳程序员创意开发大赛参赛作品</p>
    </footer>
  </main>
</body>
</html>
"""
    return "\n".join(line.rstrip() for line in document.splitlines()) + "\n"


def write_html(result: dict[str, Any], path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_html(result), encoding="utf-8")

"""Command-line interface for McProbe."""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from pathlib import Path

from .doctor import (
    DEFAULT_ENDPOINT,
    load_fixture,
    run_fixture,
    run_live,
    terminal_summary,
    write_json,
)
from .report import write_html


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcprobe",
        description="麦当劳中国 MCP 的隐私优先体检工具",
    )
    parser.add_argument("--version", action="version", version="McProbe 0.1.0")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="连接 MCP 并生成体检报告")
    source = doctor.add_mutually_exclusive_group()
    source.add_argument(
        "--demo",
        action="store_true",
        help="使用内置离线样例，不连接网络",
    )
    source.add_argument(
        "--fixture",
        metavar="PATH",
        help="从 JSON fixture 运行离线诊断",
    )
    doctor.add_argument(
        "--endpoint",
        default=os.environ.get("MCD_MCP_URL", DEFAULT_ENDPOINT),
        help=f"MCP 接入地址（默认 {DEFAULT_ENDPOINT}）",
    )
    doctor.add_argument(
        "--token-env",
        default="MCD_MCP_TOKEN",
        help="保存 Token 的环境变量名（默认 MCD_MCP_TOKEN）",
    )
    doctor.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="单次 HTTP 请求超时秒数（默认 15）",
    )
    doctor.add_argument(
        "--account",
        action="store_true",
        help="额外检查 query-my-account；只记录成败，不输出账户内容",
    )
    doctor.add_argument(
        "--out",
        default="mcprobe-report.html",
        help="HTML 报告路径（默认 mcprobe-report.html）",
    )
    doctor.add_argument(
        "--json-out",
        default="mcprobe-report.json",
        help="JSON 结果路径（默认 mcprobe-report.json）",
    )
    doctor.add_argument(
        "--open",
        action="store_true",
        dest="open_report",
        help="生成后打开 HTML 报告",
    )
    fixture = subparsers.add_parser(
        "fixture",
        help="导出内置离线样例，便于二次开发或回归测试",
    )
    fixture.add_argument("--out", default="fixtures/healthy.json")
    return parser


def _resolve_output(raw: str) -> Path:
    return Path(raw).expanduser().resolve()


def command_doctor(args: argparse.Namespace) -> int:
    token_env = args.token_env
    if args.demo or args.fixture:
        fixture = load_fixture(args.fixture)
        result = run_fixture(fixture, account=args.account)
    else:
        token = os.environ.get(token_env, "")
        result = run_live(
            endpoint=args.endpoint,
            token=token,
            timeout=args.timeout,
            account=args.account,
        )

    html_path = _resolve_output(args.out)
    json_path = _resolve_output(args.json_out)
    write_html(result, html_path)
    write_json(result, json_path)

    print(terminal_summary(result))
    print(f"HTML: {html_path}")
    print(f"JSON: {json_path}")
    if args.open_report:
        webbrowser.open(html_path.as_uri())
    return int(result["exit_code"])


def command_fixture(args: argparse.Namespace) -> int:
    from .fixtures import healthy_fixture

    path = _resolve_output(args.out)
    write_json(healthy_fixture(), path)
    print(f"Fixture: {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "doctor":
        return command_doctor(args)
    if args.command == "fixture":
        return command_fixture(args)
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

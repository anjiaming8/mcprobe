"""Small data objects shared by the client, doctor, and report renderer."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


STATUS_ORDER = {"pass": 0, "info": 1, "warn": 2, "fail": 3}


@dataclass(slots=True)
class Check:
    check_id: str
    title: str
    status: str
    summary: str
    detail: str = ""
    latency_ms: float | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Probe:
    name: str
    status: str
    latency_ms: float | None
    summary: str
    text_preview: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ToolInfo:
    name: str
    description: str = ""
    risk: str = "read"
    has_input_schema: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def aggregate_status(checks: list[Check]) -> str:
    if not checks:
        return "fail"
    worst = max(STATUS_ORDER.get(check.status, 3) for check in checks)
    return {0: "pass", 1: "pass", 2: "warn", 3: "fail"}[worst]

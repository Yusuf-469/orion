"""Allowlist of tools. Only registered tools can be executed."""

from __future__ import annotations

import re

from orion.tools.base import Tool, ToolSpec
from orion.tools.errors import ErrorCode, ToolError

_ID = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        spec: ToolSpec = tool.spec
        if not _ID.match(spec.id):
            raise ValueError(f"bad tool id {spec.id!r}")
        if spec.id in self._tools:
            raise ValueError(f"tool {spec.id!r} already registered")
        if spec.timeout_s <= 0:
            raise ValueError(f"tool {spec.id!r} needs a positive timeout")
        if spec.max_retries < 0:
            raise ValueError(f"tool {spec.id!r} has negative max_retries")
        self._tools[spec.id] = tool

    def get(self, tool_id: str) -> Tool:
        try:
            return self._tools[tool_id]
        except KeyError:
            raise ToolError(ErrorCode.UNSUPPORTED_CAPABILITY, f"no registered tool {tool_id!r}") from None

    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in sorted(self._tools.values(), key=lambda t: t.spec.id)]

    def __contains__(self, tool_id: str) -> bool:
        return tool_id in self._tools

from __future__ import annotations

import hashlib
import json
from typing import Any

import mcp_types as types
from pydantic import BaseModel, ConfigDict, Field

CANONICAL_FORMAT_VERSION = 1


class ToolDefinition(BaseModel):
    """The model-visible surface of an MCP tool. Everything here can steer an LLM, so all of it is pinned."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    title: str | None = None
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    output_schema: dict[str, Any] | None = None
    annotations: dict[str, Any] | None = None

    @classmethod
    def from_mcp(cls, tool: types.Tool) -> ToolDefinition:
        annotations = (
            tool.annotations.model_dump(mode="json", by_alias=True, exclude_none=True) if tool.annotations else None
        )
        return cls(
            name=tool.name,
            title=tool.title,
            description=tool.description or "",
            input_schema=dict(tool.input_schema),
            output_schema=dict(tool.output_schema) if tool.output_schema is not None else None,
            annotations=annotations or None,
        )

    def to_mcp(self, exposed_name: str) -> types.Tool:
        return types.Tool.model_validate(
            {
                "name": exposed_name,
                "title": self.title,
                "description": self.description,
                "inputSchema": self.input_schema,
                "outputSchema": self.output_schema,
                "annotations": self.annotations,
            }
        )

    def canonical_json(self) -> str:
        # ensure_ascii keeps invisible code points as explicit \u escapes, and no Unicode
        # normalization is applied on purpose: normalizing would let look-alike edits slip past the pin.
        payload = {"v": CANONICAL_FORMAT_VERSION, **self.model_dump(mode="json")}
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("ascii")).hexdigest()

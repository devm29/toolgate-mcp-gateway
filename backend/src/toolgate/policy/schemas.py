from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_GLOB = re.compile(r"^[A-Za-z0-9_.:@*?\-]+$")


class RateLimit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capacity: int = Field(ge=1, le=100_000, description="Burst size: tokens available when the bucket is full")
    refill_per_minute: float = Field(gt=0, le=1_000_000)

    @property
    def refill_per_second(self) -> float:
        return self.refill_per_minute / 60.0


class PolicyRule(BaseModel):
    """One statement: who (principal globs) may or may not do what (tool globs), under which constraints."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8], pattern=r"^[a-z0-9-]{1,40}$")
    effect: Literal["allow", "deny"]
    principals: list[str] = Field(default_factory=lambda: ["*"], min_length=1)
    tools: list[str] = Field(default_factory=lambda: ["*"], min_length=1)
    arguments: dict[str, Any] | None = Field(
        default=None,
        description="JSON Schema. For allow rules the arguments must satisfy it; for deny rules it selects "
        "the calls being denied.",
    )
    rate_limit: RateLimit | None = None
    description: str = Field(default="", max_length=500)

    @field_validator("principals", "tools")
    @classmethod
    def _valid_globs(cls, values: list[str]) -> list[str]:
        for value in values:
            if not _GLOB.match(value):
                raise ValueError(f"invalid pattern {value!r}: use letters, digits, _ . : @ - and * ? wildcards")
        return values

    @field_validator("arguments")
    @classmethod
    def _valid_schema(cls, schema: dict[str, Any] | None) -> dict[str, Any] | None:
        if schema is None:
            return None
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise ValueError(f"arguments is not a valid JSON Schema: {exc.message}") from exc
        return schema

    @model_validator(mode="after")
    def _deny_has_no_rate_limit(self) -> PolicyRule:
        if self.effect == "deny" and self.rate_limit is not None:
            raise ValueError("rate limits only apply to allow rules")
        return self


class PolicyBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    enabled: bool = True
    rules: list[PolicyRule] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def _unique_rule_ids(self) -> PolicyBase:
        ids = [rule.id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("rule ids must be unique within a policy")
        return self


class PolicyCreate(PolicyBase):
    pass


class PolicyUpdate(PolicyBase):
    expected_version: int | None = Field(default=None, description="Optimistic concurrency guard")


class Policy(PolicyBase):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    version: int
    created_at: datetime
    updated_at: datetime


class SimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal: str = Field(min_length=1, examples=["user:alice"])
    client_id: str | None = None
    tool: str = Field(min_length=1, examples=["github__create_issue"])
    arguments: dict[str, Any] = Field(default_factory=dict)

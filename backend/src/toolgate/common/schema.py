from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """Base for API payloads: reads ORM attributes and rejects unknown fields on input."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

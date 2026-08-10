from __future__ import annotations

from pydantic import BaseModel, Field


class PageParams(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


class CursorPage[T](BaseModel):
    items: list[T]
    next_cursor: str | None

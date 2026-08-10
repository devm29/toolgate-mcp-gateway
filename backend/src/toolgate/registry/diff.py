from __future__ import annotations

import difflib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel

from toolgate.scanner.unicode import reveal_invisible

LineKind = Literal["equal", "added", "removed"]


class DiffLine(BaseModel):
    kind: LineKind
    before_line: int | None
    after_line: int | None
    text: str


class DiffSection(BaseModel):
    field: str
    changed: bool
    before: str | None
    after: str | None
    lines: list[DiffLine]


class DefinitionDiff(BaseModel):
    base_hash: str | None
    head_hash: str
    sections: list[DiffSection]

    @property
    def changed_fields(self) -> list[str]:
        return [s.field for s in self.sections if s.changed]


_SENTENCE_BREAK = re.compile(r"(?<=[.!?:;])\s+|\n")


def _render(field: str, value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return reveal_invisible(value)
    return reveal_invisible(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))


def _lines(field: str, text: str | None) -> list[str]:
    if text is None:
        return []
    if field == "description":
        return [part for part in _SENTENCE_BREAK.split(text) if part]
    return text.splitlines()


def _section(field: str, before_value: Any, after_value: Any) -> DiffSection:
    before = _render(field, before_value)
    after = _render(field, after_value)
    a, b = _lines(field, before), _lines(field, after)
    lines: list[DiffLine] = []
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            lines.extend(
                DiffLine(kind="equal", before_line=i + 1, after_line=j + 1, text=a[i])
                for i, j in zip(range(i1, i2), range(j1, j2), strict=True)
            )
            continue
        lines.extend(DiffLine(kind="removed", before_line=i + 1, after_line=None, text=a[i]) for i in range(i1, i2))
        lines.extend(DiffLine(kind="added", before_line=None, after_line=j + 1, text=b[j]) for j in range(j1, j2))
    return DiffSection(field=field, changed=before != after, before=before, after=after, lines=lines)


FIELDS = ("name", "title", "description", "input_schema", "output_schema", "annotations")


def diff_definitions(
    before: dict[str, Any] | None, after: dict[str, Any], *, base_hash: str | None, head_hash: str
) -> DefinitionDiff:
    old = before or {}
    return DefinitionDiff(
        base_hash=base_hash,
        head_hash=head_hash,
        sections=[_section(field, old.get(field), after.get(field)) for field in FIELDS],
    )

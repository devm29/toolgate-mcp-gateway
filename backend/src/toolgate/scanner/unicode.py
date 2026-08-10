from __future__ import annotations

import unicodedata
from dataclasses import dataclass

TAG_BLOCK = range(0xE0000, 0xE0080)
ZERO_WIDTH = frozenset({0x200B, 0x200C, 0x200D, 0x2060, 0x2061, 0x2062, 0x2063, 0x2064, 0xFEFF, 0x180E})
BIDI_CONTROLS = frozenset({*range(0x202A, 0x202F), *range(0x2066, 0x206A), 0x200E, 0x200F, 0x061C})
# Soft hyphens are Cf but legitimately common in prose, so they are not treated as smuggling.
SOFT_HYPHEN = "\u00ad"
VARIATION_SELECTORS = frozenset({*range(0xFE00, 0xFE10), *range(0xE0100, 0xE01F0)})


@dataclass(frozen=True, slots=True)
class InvisibleRun:
    kind: str
    count: int
    decoded: str


def is_invisible(char: str) -> bool:
    cp = ord(char)
    return (
        cp in TAG_BLOCK
        or cp in ZERO_WIDTH
        or cp in BIDI_CONTROLS
        or cp in VARIATION_SELECTORS
        or (unicodedata.category(char) == "Cf" and char != SOFT_HYPHEN)
    )


def decode_tag_payload(text: str) -> str:
    """Unicode tag characters mirror ASCII at U+E0000 + n and render as nothing; decode the hidden text."""
    return "".join(chr(ord(c) - 0xE0000) for c in text if 0xE0020 <= ord(c) <= 0xE007E)


def classify_invisibles(text: str) -> list[InvisibleRun]:
    tags = [c for c in text if ord(c) in TAG_BLOCK]
    zero_width = [c for c in text if ord(c) in ZERO_WIDTH]
    bidi = [c for c in text if ord(c) in BIDI_CONTROLS]
    selectors = [c for c in text if ord(c) in VARIATION_SELECTORS]
    other = [
        c
        for c in text
        if unicodedata.category(c) == "Cf"
        and not any(ord(c) in group for group in (TAG_BLOCK, ZERO_WIDTH, BIDI_CONTROLS, VARIATION_SELECTORS))
        and c != SOFT_HYPHEN
    ]
    runs: list[InvisibleRun] = []
    if tags:
        runs.append(InvisibleRun("tag", len(tags), decode_tag_payload(text)))
    if zero_width:
        runs.append(InvisibleRun("zero_width", len(zero_width), ""))
    if bidi:
        runs.append(InvisibleRun("bidi", len(bidi), ""))
    if selectors:
        runs.append(InvisibleRun("variation_selector", len(selectors), ""))
    if other:
        runs.append(InvisibleRun("format", len(other), ""))
    return runs


def reveal_invisible(text: str) -> str:
    """Render invisible code points as visible markers so reviewers can see what the model would read."""
    out: list[str] = []
    for char in text:
        if is_invisible(char):
            out.append(f"⟦U+{ord(char):04X}⟧")
        else:
            out.append(char)
    return "".join(out)


def mixed_script_confusable(name: str) -> bool:
    """True when an identifier mixes Latin with Cyrillic/Greek letters, the usual homoglyph trick."""
    scripts: set[str] = set()
    for char in name:
        if not char.isalpha():
            continue
        label = unicodedata.name(char, "")
        if label.startswith("LATIN"):
            scripts.add("latin")
        elif label.startswith("CYRILLIC"):
            scripts.add("cyrillic")
        elif label.startswith("GREEK"):
            scripts.add("greek")
    return "latin" in scripts and len(scripts) > 1

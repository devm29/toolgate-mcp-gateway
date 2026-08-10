from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def weight(self) -> int:
        return _WEIGHTS[self]


_WEIGHTS: dict[Severity, int] = {
    Severity.INFO: 0,
    Severity.LOW: 8,
    Severity.MEDIUM: 20,
    Severity.HIGH: 45,
    Severity.CRITICAL: 80,
}


class RiskLevel(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @classmethod
    def from_score(cls, score: int) -> RiskLevel:
        if score >= 80:
            return cls.CRITICAL
        if score >= 45:
            return cls.HIGH
        if score >= 20:
            return cls.MEDIUM
        if score > 0:
            return cls.LOW
        return cls.NONE


class RuleId(StrEnum):
    HIDDEN_INSTRUCTIONS = "hidden-instructions"
    UNICODE_SMUGGLING = "unicode-smuggling"
    CROSS_TOOL_SHADOWING = "cross-tool-shadowing"
    EXFILTRATION = "exfiltration"
    EXCESSIVE_SCHEMA = "excessive-schema"
    LLM_CLASSIFIER = "llm-classifier"


class Finding(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule: RuleId
    severity: Severity
    title: str
    detail: str
    location: str = Field(description="Where in the definition, e.g. description or inputSchema.properties.path")
    evidence: str | None = None


class ClassifierVerdict(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: Literal["benign", "suspicious", "malicious"]
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    model: str


class ScanReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_name: str
    definition_hash: str
    score: int = Field(ge=0, le=100)
    level: RiskLevel
    findings: list[Finding]
    classifier: ClassifierVerdict | None = None
    scanner_version: str
    scanned_at: datetime

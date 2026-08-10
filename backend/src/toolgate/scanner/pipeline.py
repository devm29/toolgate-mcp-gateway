from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from toolgate.common.tool_definition import ToolDefinition
from toolgate.scanner.classifier import ToolClassifier
from toolgate.scanner.context import ScanContext
from toolgate.scanner.models import ClassifierVerdict, Finding, RiskLevel, RuleId, ScanReport, Severity
from toolgate.scanner.rules import DEFAULT_RULES, Rule

SCANNER_VERSION = "2026.10.1"

_SEVERITY_ORDER = list(Severity)


def run_rules(tool: ToolDefinition, ctx: ScanContext, rules: Sequence[Rule] = DEFAULT_RULES) -> list[Finding]:
    findings = [finding for rule in rules for finding in rule(tool, ctx)]
    return sorted(findings, key=lambda f: (-_SEVERITY_ORDER.index(f.severity), f.rule, f.location))


def classifier_finding(verdict: ClassifierVerdict) -> Finding | None:
    if verdict.label == "benign" or verdict.confidence < 0.5:
        return None
    severity = Severity.HIGH if verdict.label == "malicious" else Severity.MEDIUM
    return Finding(
        rule=RuleId.LLM_CLASSIFIER,
        severity=severity,
        title=f"Classifier judged the tool {verdict.label}",
        detail=verdict.rationale,
        location="definition",
        evidence=f"{verdict.model} @ {verdict.confidence:.2f}",
    )


def build_report(
    tool: ToolDefinition,
    findings: list[Finding],
    verdict: ClassifierVerdict | None = None,
    *,
    now: datetime | None = None,
) -> ScanReport:
    all_findings = list(findings)
    if verdict is not None and (extra := classifier_finding(verdict)) is not None:
        all_findings.append(extra)
    score = min(100, sum(f.severity.weight for f in all_findings))
    return ScanReport(
        tool_name=tool.name,
        definition_hash=tool.sha256(),
        score=score,
        level=RiskLevel.from_score(score),
        findings=all_findings,
        classifier=verdict,
        scanner_version=SCANNER_VERSION,
        scanned_at=now or datetime.now(UTC),
    )


class Scanner:
    def __init__(self, classifier: ToolClassifier | None = None, rules: Sequence[Rule] = DEFAULT_RULES) -> None:
        self._classifier = classifier
        self._rules = tuple(rules)

    async def scan(self, tool: ToolDefinition, ctx: ScanContext) -> ScanReport:
        findings = run_rules(tool, ctx, self._rules)
        verdict = await self._classifier.classify(tool) if self._classifier else None
        return build_report(tool, findings, verdict)

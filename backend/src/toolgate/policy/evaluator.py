from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import Any, Literal

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict

from toolgate.common.schema_errors import describe_error
from toolgate.policy.schemas import Policy, PolicyRule, RateLimit


class RuleRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy_id: uuid.UUID
    policy_name: str
    rule_id: str
    effect: Literal["allow", "deny"]


class RateLimitBinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    limit: RateLimit
    rule: RuleRef


class Decision(BaseModel):
    model_config = ConfigDict(frozen=True)

    allowed: bool
    reason: str
    matched: list[RuleRef] = []
    violations: list[str] = []
    rate_limits: list[RateLimitBinding] = []


@dataclass(frozen=True, slots=True)
class _CompiledRule:
    ref: RuleRef
    rule: PolicyRule
    validator: Draft202012Validator | None = field(default=None)

    def matches(self, identities: Sequence[str], tool: str) -> bool:
        return any(fnmatchcase(i, p) for i in identities for p in self.rule.principals) and any(
            fnmatchcase(tool, p) for p in self.rule.tools
        )


class PolicySet:
    """Compiled, immutable view over enabled policies; safe to share across requests."""

    def __init__(self, policies: Iterable[Policy]) -> None:
        rules: list[_CompiledRule] = []
        for policy in policies:
            if not policy.enabled:
                continue
            for rule in policy.rules:
                ref = RuleRef(policy_id=policy.id, policy_name=policy.name, rule_id=rule.id, effect=rule.effect)
                validator = (
                    Draft202012Validator(rule.arguments, format_checker=Draft202012Validator.FORMAT_CHECKER)
                    if rule.arguments is not None
                    else None
                )
                rules.append(_CompiledRule(ref, rule, validator))
        self._rules = tuple(rules)

    def __len__(self) -> int:
        return len(self._rules)

    def evaluate(self, identities: Sequence[str], tool: str, arguments: Mapping[str, Any] | None) -> Decision:
        """Deny overrides allow, no matching allow means deny, and every matching allow's constraints must hold.

        Passing arguments=None asks "could this caller ever use the tool?", which is how tools/list is filtered:
        conditional deny rules are skipped and argument constraints are not checked.
        """
        matched = [r for r in self._rules if r.matches(identities, tool)]
        refs = [r.ref for r in matched]

        for compiled in matched:
            if compiled.rule.effect != "deny":
                continue
            if compiled.validator is None:
                return Decision(allowed=False, reason=_deny_reason(compiled), matched=refs)
            if arguments is not None and compiled.validator.is_valid(dict(arguments)):
                return Decision(allowed=False, reason=_deny_reason(compiled), matched=refs)

        allows = [r for r in matched if r.rule.effect == "allow"]
        if not allows:
            return Decision(allowed=False, reason="No policy grants this principal access to the tool", matched=refs)

        if arguments is not None:
            violations = [
                f"{c.ref.policy_name}/{c.ref.rule_id}: {describe_error(err)}"
                for c in allows
                if c.validator is not None
                for err in c.validator.iter_errors(dict(arguments))
            ]
            if violations:
                return Decision(
                    allowed=False,
                    reason="Arguments violate policy constraints",
                    matched=refs,
                    violations=violations,
                )

        principal_key = identities[0] if identities else "anonymous"
        bindings = [
            RateLimitBinding(
                key=f"rl:{c.ref.policy_id}:{c.ref.rule_id}:{principal_key}:{tool}",
                limit=c.rule.rate_limit,
                rule=c.ref,
            )
            for c in allows
            if c.rule.rate_limit is not None
        ]
        first = allows[0].ref
        return Decision(
            allowed=True,
            reason=f"Allowed by {first.policy_name}/{first.rule_id}",
            matched=refs,
            rate_limits=bindings,
        )


def _deny_reason(compiled: _CompiledRule) -> str:
    detail = f": {compiled.rule.description}" if compiled.rule.description else ""
    return f"Denied by {compiled.ref.policy_name}/{compiled.ref.rule_id}{detail}"

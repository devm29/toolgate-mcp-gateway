from __future__ import annotations

import uuid
from datetime import UTC, datetime

from toolgate.policy.evaluator import PolicySet
from toolgate.policy.schemas import Policy, PolicyRule, RateLimit


def make_policy(name: str, rules: list[PolicyRule], *, enabled: bool = True) -> Policy:
    now = datetime.now(UTC)
    return Policy(
        id=uuid.uuid4(),
        name=name,
        description="",
        enabled=enabled,
        rules=rules,
        version=1,
        created_at=now,
        updated_at=now,
    )


def test_default_deny() -> None:
    policy_set = PolicySet([])
    assert not policy_set.evaluate(["user:alice"], "github__create_issue", {}).allowed


def test_allow_rule_grants_access() -> None:
    policy = make_policy("p", [PolicyRule(id="a", effect="allow", tools=["weather__*"])])
    assert PolicySet([policy]).evaluate(["user:alice"], "weather__get_forecast", {}).allowed


def test_deny_overrides_allow() -> None:
    policy = make_policy(
        "p",
        [
            PolicyRule(id="a", effect="allow", tools=["github__*"]),
            PolicyRule(id="d", effect="deny", tools=["github__delete_branch"]),
        ],
    )
    result = PolicySet([policy]).evaluate(["user:alice"], "github__delete_branch", {})
    assert not result.allowed
    assert "delete" in result.reason or "d" in result.reason


def test_argument_constraint_enforced() -> None:
    policy = make_policy(
        "p",
        [
            PolicyRule(
                id="a",
                effect="allow",
                tools=["github__create_issue"],
                arguments={"type": "object", "properties": {"repo": {"enum": ["acme/web"]}}, "required": ["repo"]},
            )
        ],
    )
    policy_set = PolicySet([policy])
    assert policy_set.evaluate(["user:alice"], "github__create_issue", {"repo": "acme/web"}).allowed
    blocked = policy_set.evaluate(["user:alice"], "github__create_issue", {"repo": "evil/repo"})
    assert not blocked.allowed
    assert blocked.violations


def test_conditional_deny_on_argument() -> None:
    policy = make_policy(
        "p",
        [
            PolicyRule(id="a", effect="allow", tools=["files__read_file"]),
            PolicyRule(
                id="d",
                effect="deny",
                tools=["files__read_file"],
                arguments={
                    "type": "object",
                    "properties": {"path": {"type": "string", "pattern": "\\.ssh/"}},
                    "required": ["path"],
                },
            ),
        ],
    )
    policy_set = PolicySet([policy])
    assert policy_set.evaluate(["user:a"], "files__read_file", {"path": "/workspace/app.py"}).allowed
    assert not policy_set.evaluate(["user:a"], "files__read_file", {"path": "/home/x/.ssh/id_rsa"}).allowed


def test_listing_filter_skips_conditional_deny() -> None:
    policy = make_policy(
        "p",
        [
            PolicyRule(id="a", effect="allow", tools=["files__*"]),
            PolicyRule(
                id="d",
                effect="deny",
                tools=["files__read_file"],
                arguments={"type": "object", "properties": {"path": {"const": "/secret"}}},
            ),
        ],
    )
    # arguments=None asks reachability only; a conditional deny must not hide the tool from listings.
    assert PolicySet([policy]).evaluate(["user:a"], "files__read_file", None).allowed


def test_rate_limit_binding_emitted() -> None:
    policy = make_policy(
        "p",
        [
            PolicyRule(
                id="a", effect="allow", tools=["weather__*"], rate_limit=RateLimit(capacity=5, refill_per_minute=10)
            )
        ],
    )
    decision = PolicySet([policy]).evaluate(["user:a"], "weather__get_forecast", {})
    assert decision.allowed
    assert len(decision.rate_limits) == 1
    assert decision.rate_limits[0].limit.capacity == 5


def test_principal_glob() -> None:
    policy = make_policy("p", [PolicyRule(id="a", effect="allow", principals=["client:*"], tools=["*"])])
    policy_set = PolicySet([policy])
    assert policy_set.evaluate(["client:abc"], "weather__x", {}).allowed
    assert not policy_set.evaluate(["user:bob"], "weather__x", {}).allowed


def test_disabled_policy_ignored() -> None:
    policy = make_policy("p", [PolicyRule(id="a", effect="allow", tools=["*"])], enabled=False)
    assert not PolicySet([policy]).evaluate(["user:a"], "weather__x", {}).allowed

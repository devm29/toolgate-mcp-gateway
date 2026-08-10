"""Benign: a slice of a GitHub-like issue tracker backed by in-memory data."""

from __future__ import annotations

import itertools
from typing import Any

from fixtures.kit import FixtureServer, FixtureTool, schema

ISSUES: dict[str, list[dict[str, Any]]] = {
    "acme/payments": [
        {"number": 412, "title": "Retry webhook deliveries with jitter", "state": "open", "labels": ["reliability"]},
        {"number": 409, "title": "Idempotency keys expire too early", "state": "open", "labels": ["bug"]},
        {"number": 377, "title": "Upgrade to Postgres 17", "state": "closed", "labels": ["infra"]},
    ],
    "acme/web": [
        {"number": 88, "title": "Dark mode contrast on settings page", "state": "open", "labels": ["a11y"]},
        {"number": 81, "title": "Cache-bust fonts on deploy", "state": "closed", "labels": ["build"]},
    ],
}
_numbers = itertools.count(500)

REPO = {"type": "string", "pattern": "^[\\w.-]+/[\\w.-]+$", "description": "owner/name"}


def list_issues(args: dict[str, Any]) -> dict[str, Any]:
    repo = str(args["repo"])
    state = str(args.get("state", "open"))
    issues = [i for i in ISSUES.get(repo, []) if state == "all" or i["state"] == state]
    return {"repo": repo, "issues": issues}


def create_issue(args: dict[str, Any]) -> dict[str, Any]:
    repo = str(args["repo"])
    issue = {
        "number": next(_numbers),
        "title": str(args["title"]),
        "state": "open",
        "labels": list(args.get("labels", [])),
    }
    ISSUES.setdefault(repo, []).insert(0, issue)
    return {"repo": repo, "created": issue}


def delete_branch(args: dict[str, Any]) -> str:
    return f"Deleted branch {args['branch']} in {args['repo']}"


def server() -> FixtureServer:
    return FixtureServer(
        name="github",
        tools=[
            FixtureTool(
                name="list_issues",
                title="List issues",
                description="List issues in a repository, newest first.",
                input_schema=schema(
                    {"repo": REPO, "state": {"type": "string", "enum": ["open", "closed", "all"], "default": "open"}},
                    ["repo"],
                ),
                handler=list_issues,
                annotations={"readOnlyHint": True},
            ),
            FixtureTool(
                name="create_issue",
                title="Create issue",
                description="Open a new issue with a title, optional body and labels.",
                input_schema=schema(
                    {
                        "repo": REPO,
                        "title": {"type": "string", "minLength": 3, "maxLength": 200},
                        "body": {"type": "string", "maxLength": 10000},
                        "labels": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
                    },
                    ["repo", "title"],
                ),
                handler=create_issue,
            ),
            FixtureTool(
                name="delete_branch",
                title="Delete branch",
                description="Delete a branch. This cannot be undone.",
                input_schema=schema({"repo": REPO, "branch": {"type": "string"}}, ["repo", "branch"]),
                handler=delete_branch,
                annotations={"destructiveHint": True},
            ),
        ],
    )


if __name__ == "__main__":
    server().main()

"""Benign: read-only access to a virtual workspace. Policies narrow which paths agents may read."""

from __future__ import annotations

from typing import Any

from fixtures.kit import FixtureServer, FixtureTool, schema

WORKSPACE = {
    "/workspace/README.md": "# Payments service\n\nRuns on Postgres 17 and Redis. See docs/runbook.md.",
    "/workspace/docs/runbook.md": "1. Check the dashboard.\n2. Page the on-call if p95 > 800ms.",
    "/workspace/src/app.py": "from fastapi import FastAPI\n\napp = FastAPI()\n",
    "/etc/passwd": "root:x:0:0:root:/root:/bin/bash",
    "/home/dev/.ssh/id_rsa": "-----BEGIN OPENSSH PRIVATE KEY-----\nfake\n-----END OPENSSH PRIVATE KEY-----",
}


def read_file(args: dict[str, Any]) -> str:
    path = str(args["path"])
    if path not in WORKSPACE:
        raise ValueError(f"{path} does not exist")
    return WORKSPACE[path]


def list_directory(args: dict[str, Any]) -> dict[str, Any]:
    prefix = str(args.get("path", "/workspace")).rstrip("/") + "/"
    return {"entries": sorted(p for p in WORKSPACE if p.startswith(prefix))}


def server() -> FixtureServer:
    return FixtureServer(
        name="files",
        tools=[
            FixtureTool(
                name="read_file",
                title="Read file",
                description="Read a UTF-8 text file from the workspace.",
                input_schema=schema({"path": {"type": "string", "description": "Absolute path"}}, ["path"]),
                handler=read_file,
                annotations={"readOnlyHint": True},
            ),
            FixtureTool(
                name="list_directory",
                title="List directory",
                description="List files under a directory.",
                input_schema=schema({"path": {"type": "string", "default": "/workspace"}}),
                handler=list_directory,
                annotations={"readOnlyHint": True},
            ),
        ],
    )


if __name__ == "__main__":
    server().main()

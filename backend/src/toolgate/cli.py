from __future__ import annotations

import argparse
import asyncio

from toolgate.config import get_settings
from toolgate.logging import configure_logging
from toolgate.seed import _amain as seed_main


def main() -> None:
    parser = argparse.ArgumentParser(prog="toolgate", description="Toolgate operations")
    sub = parser.add_subparsers(dest="command", required=True)
    seed_parser = sub.add_parser("seed", help="Load demo upstreams, policies and accounts")
    seed_parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete every upstream and policy first (cascades to tools, pins and approvals)",
    )
    sub.add_parser("serve", help="Run the gateway with uvicorn")
    args = parser.parse_args()

    if args.command == "seed":
        asyncio.run(seed_main(reset=args.reset))
    elif args.command == "serve":
        import uvicorn

        settings = get_settings()
        configure_logging(settings.log_level, json=settings.log_json)
        uvicorn.run("toolgate.main:app", host="127.0.0.1", port=8101, log_level=settings.log_level.lower())


if __name__ == "__main__":
    main()

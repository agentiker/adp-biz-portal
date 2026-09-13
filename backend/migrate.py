#!/usr/bin/env python3
"""Run explicit database migrations for the deployment database.

The web server intentionally does not invoke this module. Run it once during
deployment, before starting Sanic, with an account allowed to alter schema.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from app_factory import create_app
from core.migration import Migration, MigrationError
from util.database import create_db_engine


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the adp-business-gateway database schema")
    subparsers = parser.add_subparsers(dest="command", required=True)

    upgrade = subparsers.add_parser("upgrade", help="apply pending revisions")
    upgrade.add_argument("--target", type=int, default=Migration.CURRENT_PLATFORM_SCHEMA_VERSION)
    upgrade.add_argument("--applied-by", default=getpass.getuser())

    downgrade = subparsers.add_parser("downgrade", help="roll back revisions")
    downgrade.add_argument("--target", type=int, required=True)
    downgrade.add_argument("--applied-by", default=getpass.getuser())
    downgrade.add_argument(
        "--allow-data-loss",
        action="store_true",
        help="required because rollback drops tables and their data",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    app = create_app()
    engine, sessionmaker = create_db_engine(app)
    try:
        async with sessionmaker() as db:
            if args.command == "upgrade":
                version = await Migration.upgrade(
                    db,
                    target_version=args.target,
                    applied_by=args.applied_by,
                )
            else:
                version = await Migration.downgrade(
                    db,
                    target_version=args.target,
                    applied_by=args.applied_by,
                    allow_data_loss=args.allow_data_loss,
                )
        print(f"database revision: {version}")
        return 0
    finally:
        await engine.dispose()


def main() -> int:
    args = _parser().parse_args()
    try:
        return asyncio.run(_run(args))
    except (MigrationError, ValueError) as exc:
        print(f"migration failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

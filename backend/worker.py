#!/usr/bin/env python3
"""Run the durable platform delivery worker.

The worker is intentionally separate from the Sanic web process.  It loads
the same environment and database settings, validates that migrations are
current, and then consumes inbound and reply tasks from PostgreSQL.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable
from typing import Any

from app_factory import create_app_with_configs
from core.delivery import DeliveryWorker
from core.migration import Migration
from core.platform_worker import build_platform_delivery_handlers
from integrations.channels.sender_registry import ChannelSenderResolver
from util.database import create_db_engine


def build_agent_provider() -> None:
    """Business turns resolve their application from the database registry.

    APP_CONFIGS remains available to the legacy administrator debugger only.
    M3_USE_MOCK selects tool data; it never substitutes a local agent for ADP.
    """
    return None


def build_worker(
    sessionmaker: Callable[..., Any],
    *,
    worker_id: str | None = None,
    idle_seconds: float = 1.0,
    agent_provider_factory: Any = build_agent_provider,
    reply_sender_factory: Any = None,
) -> DeliveryWorker:
    """Create a worker with the platform handlers and controlled provider.

    The reply sender resolves per channel instance from stored credentials. A
    channel without usable send credentials still reports an uncertain delivery
    rather than a false success.
    """
    sender_resolver = (
        reply_sender_factory
        if reply_sender_factory is not None
        else ChannelSenderResolver(sessionmaker)
    )
    return DeliveryWorker(
        sessionmaker=sessionmaker,
        handlers=build_platform_delivery_handlers(
            sessionmaker,
            agent_provider_factory=agent_provider_factory,
            reply_sender_factory=sender_resolver,
        ),
        worker_id=worker_id,
        idle_seconds=idle_seconds,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the unified platform delivery worker")
    parser.add_argument(
        "--once",
        action="store_true",
        help="process at most one ready task and exit",
    )
    parser.add_argument("--worker-id", default=None, help="stable worker lease owner identifier")
    parser.add_argument(
        "--idle-seconds",
        type=float,
        default=1.0,
        help="poll interval when the queue is empty (default: 1.0)",
    )
    return parser


async def run_worker(args: argparse.Namespace) -> bool | None:
    """Validate the schema, run the worker, and dispose its connection pool."""
    app = create_app_with_configs()
    engine, sessionmaker = create_db_engine(app)
    try:
        async with sessionmaker() as db:
            await Migration.validate_startup(db)
        worker = build_worker(
            sessionmaker,
            worker_id=args.worker_id,
            idle_seconds=args.idle_seconds,
        )
        if args.once:
            return await worker.run_once()
        await worker.run_forever()
        return None
    finally:
        await engine.dispose()


def main() -> int:
    args = _parser().parse_args()
    asyncio.run(run_worker(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

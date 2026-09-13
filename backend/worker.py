#!/usr/bin/env python3
"""Run the durable platform delivery worker.

The worker is intentionally separate from the Sanic web process.  It loads
the same environment and database settings, validates that migrations are
current, and then consumes inbound and reply tasks from PostgreSQL.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Callable
from typing import Any

from app_factory import TAgenticApp, create_app_with_configs
from config import tagentic_config
from core.delivery import DeliveryWorker
from core.migration import Migration
from core.platform_worker import build_platform_delivery_handlers
from integrations.adp.provider import ADPAgentProvider, AgentProvider, ControlledLookupAgentProvider
from integrations.channels.sender_registry import ChannelSenderResolver
from integrations.m3.adapter import M3LookupAdapter
from util.database import create_db_engine


def build_agent_provider() -> AgentProvider:
    """Build the server-selected ADP provider or the explicit local M3 provider."""
    mappings = tagentic_config.ADP_AGENT_CONFIGS
    if mappings:
        normalized: list[tuple[str, str, Any]] = []
        for item in mappings:
            if not isinstance(item, dict):
                return ADPAgentProvider(agent_id="platform-default", application_id="", vendor=None)
            agent_id = item.get("agentId")
            application_id = item.get("applicationId")
            if (
                not isinstance(agent_id, str)
                or not agent_id.strip()
                or len(agent_id.strip()) > 128
                or not isinstance(application_id, str)
                or not application_id.strip()
                or len(application_id.strip()) > 64
            ):
                return ADPAgentProvider(agent_id="platform-default", application_id="", vendor=None)
            vendor = TAgenticApp.apps.get(application_id.strip())
            if vendor is None or not callable(getattr(vendor, "chat", None)):
                return ADPAgentProvider(agent_id=agent_id.strip(), application_id=application_id.strip(), vendor=None)
            normalized.append((agent_id.strip(), application_id.strip(), vendor))
        selected_id = str(tagentic_config.ADP_DEFAULT_AGENT_ID or "").strip()
        if not selected_id:
            selected_id = normalized[0][0] if len(normalized) == 1 else ""
        selected = next((item for item in normalized if item[0] == selected_id), None)
        if selected is None:
            return ADPAgentProvider(agent_id=selected_id or "platform-default", application_id="", vendor=None)
        return ADPAgentProvider(
            agent_id=selected[0],
            application_id=selected[1],
            vendor=selected[2],
        )

    # No explicit mapping: the first phase gives the platform exactly one ADP
    # application, configured through APP_CONFIGS. Route to it.
    platform_provider = _platform_application_provider()
    if platform_provider is not None:
        return platform_provider

    # Development fallback only, and only when M3 was configured on purpose.
    # Whether the agent can reach M3 is the agent's own tool configuration, so a
    # missing M3 setting must never stop a message from reaching ADP.
    if tagentic_config.M3_USE_MOCK or str(tagentic_config.M3_BASE_URL or "").strip():
        adapter = M3LookupAdapter(
            use_mock=bool(tagentic_config.M3_USE_MOCK),
            base_url=tagentic_config.M3_BASE_URL,
            timeout_seconds=tagentic_config.M3_TIMEOUT_SECONDS,
        )
        return ControlledLookupAgentProvider(adapter)

    # Nothing is configured. Return an ADP provider without a vendor so each
    # message fails honestly as an upstream error instead of being answered by a
    # local stand-in that was never meant for production.
    logging.error(
        "no ADP application is configured: set APP_CONFIGS (single platform app) "
        "or ADP_AGENT_CONFIGS; messages will report an upstream error"
    )
    return ADPAgentProvider(agent_id=_default_agent_id(), application_id="", vendor=None)


def _default_agent_id() -> str:
    configured = str(tagentic_config.ADP_DEFAULT_AGENT_ID or "").strip()
    return configured[:128] if configured else "platform-default"


def _platform_application_provider() -> AgentProvider | None:
    """Resolve the single platform ADP application from ``APP_CONFIGS``.

    Several configured applications are ambiguous without an explicit mapping,
    so that case fails closed rather than guessing which one serves customers.
    """
    configs = list(tagentic_config.APP_CONFIGS or [])
    if len(configs) != 1 or not isinstance(configs[0], dict):
        if len(configs) > 1:
            logging.error(
                "APP_CONFIGS has %s applications; set ADP_AGENT_CONFIGS to choose the platform agent",
                len(configs),
            )
        return None
    application_id = str(configs[0].get("ApplicationId") or "").strip()
    if not application_id:
        return None
    vendor = TAgenticApp.apps.get(application_id)
    if vendor is None or not callable(getattr(vendor, "chat", None)):
        logging.error("configured ADP application %s is not usable", application_id)
        return ADPAgentProvider(
            agent_id=_default_agent_id(), application_id=application_id, vendor=None
        )
    return ADPAgentProvider(
        agent_id=_default_agent_id(), application_id=application_id, vendor=vendor
    )


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

"""Container liveness and readiness probes.

The liveness probe is deliberately independent from PostgreSQL and upstream
ADP/M3 providers.  Readiness checks the database connection and the explicit
schema revision so an orchestrator does not send traffic to an un-migrated
release.
"""

from __future__ import annotations

import logging

from sanic import response
from sqlalchemy import text

from app_factory import TAgenticApp
from core.migration import Migration


app = TAgenticApp.get_app()
logger = logging.getLogger(__name__)


async def healthz(request):
    """Return liveness without requiring a database or third-party service."""
    del request
    return response.json({"status": "ok", "service": "api"})


async def readyz(request):
    """Return ready only when PostgreSQL and the current schema are available."""
    sessionmaker = request.app.config.get("sessionmaker")
    if sessionmaker is None:
        return response.json(
            {"status": "not_ready", "reason": "database_not_initialized"},
            status=503,
        )

    try:
        async with sessionmaker() as db:
            await db.execute(text("SELECT 1"))
            await Migration.validate_startup(db)
    except Exception as error:  # probe responses must not expose credentials or SQL
        logger.warning("[readyz] readiness check failed errorType=%s", type(error).__name__)
        return response.json(
            {"status": "not_ready", "reason": type(error).__name__},
            status=503,
        )

    return response.json(
        {
            "status": "ready",
            "service": "api",
            "schemaRevision": Migration.CURRENT_PLATFORM_SCHEMA_VERSION,
        }
    )


# ``util.module.autodiscover`` loads router files by path, while tests and
# tooling may import this module normally. Avoid registering the same route
# twice in that mixed loading mode.
_registered_routes = {
    (route.path, method)
    for route in app.router.routes
    for method in route.methods
}
if ("healthz", "GET") not in _registered_routes:
    app.add_route(healthz, "/healthz", methods={"GET"})
if ("readyz", "GET") not in _registered_routes:
    app.add_route(readyz, "/readyz", methods={"GET"})

"""One shared Sanic application for the whole test process.

Sanic keeps a global application registry and refuses a second app with the
same name, so several test modules creating their own app made the outcome
depend on collection order. Every module now asks for the same fully
initialized application through :func:`ensure_app`.
"""

from __future__ import annotations

from sanic import Sanic


def ensure_app():
    """Return the process-wide app, creating it with middleware once."""
    from app_factory import create_app

    if Sanic._app_registry:
        return next(iter(Sanic._app_registry.values()))
    return create_app()

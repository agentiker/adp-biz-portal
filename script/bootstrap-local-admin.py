#!/usr/bin/env python3
"""Create or refresh the local-only platform administrator.

This helper is intentionally restricted to a loopback PostgreSQL host. It is
safe to run repeatedly while developing: the same phone number is refreshed
instead of creating a second account.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import sys
from pathlib import Path

from sqlalchemy import select


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(SERVER_ROOT))

from app_factory import create_app  # noqa: E402
from core.platform import (  # noqa: E402
    create_platform_user,
    find_platform_user_by_phone,
    normalize_phone,
    revoke_account_execution_contexts,
    revoke_account_sessions,
)
from model.account import Account, AccountRole, AccountStatus  # noqa: E402
from model.platform import PlatformCredential, PlatformRole, PlatformStatus  # noqa: E402
from util.database import create_db_engine  # noqa: E402
from util.password import hash as password_hash  # noqa: E402


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap the local platform admin account")
    parser.add_argument(
        "--name",
        default=os.getenv("LOCAL_ADMIN_NAME", "本地调试管理员"),
        help="display name (default: LOCAL_ADMIN_NAME or 本地调试管理员)",
    )
    parser.add_argument(
        "--phone",
        default=os.getenv("LOCAL_ADMIN_PHONE", "13900000000"),
        help="login phone (default: LOCAL_ADMIN_PHONE or 13900000000)",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("LOCAL_ADMIN_PASSWORD", "123456"),
        help="six-digit login password (default: LOCAL_ADMIN_PASSWORD or 123456)",
    )
    return parser


async def _bootstrap(name: str, phone: str, password: str) -> tuple[str, bool]:
    app = create_app()
    # ``core.migration`` registers startup hooks and therefore must be loaded
    # after Sanic has registered the application created above.
    from core.migration import Migration

    host = (app.config.PGSQL_HOST or "").strip().lower()
    if host not in LOOPBACK_HOSTS:
        raise RuntimeError(
            f"Refusing to modify a non-local database host: {app.config.PGSQL_HOST!r}"
        )
    if not app.config.PGSQL_DB:
        raise RuntimeError("PGSQL_DB is not configured")

    normalized_phone = normalize_phone(phone)
    if not isinstance(password, str) or not password.isdigit() or len(password) != 6:
        raise ValueError("password must contain exactly six digits")

    engine, sessionmaker = create_db_engine(app)
    try:
        async with sessionmaker() as db:
            # Local account provisioning is not a schema migration. Run
            # ``backend/.venv/bin/python backend/migrate.py upgrade`` first.
            await Migration.validate_startup(db)
            user = await find_platform_user_by_phone(db, normalized_phone)
            created = user is None
            if user is None:
                user, _ = await create_platform_user(
                    db,
                    name=name,
                    phone=normalized_phone,
                    role=PlatformRole.ADMIN,
                    initial_password=password,
                )
            else:
                account = (
                    await db.execute(select(Account).where(Account.Id == user.AccountId))
                ).scalar_one_or_none()
                if account is None:
                    raise RuntimeError(f"Platform user {user.Id} has no account row")
                credential = (
                    await db.execute(
                        select(PlatformCredential).where(
                            PlatformCredential.AccountId == user.AccountId
                        )
                    )
                ).scalar_one_or_none()
                if credential is None:
                    raise RuntimeError(f"Platform user {user.Id} has no credential row")

                salt = secrets.token_hex(32)
                user.Name = name.strip()
                user.Role = PlatformRole.ADMIN
                user.Status = PlatformStatus.ACTIVE
                account.Name = name.strip()
                account.Role = AccountRole.ADMIN
                account.Status = AccountStatus.ACTIVE
                credential.PasswordSalt = salt
                credential.PasswordHash = password_hash(password, salt)
                credential.FailedAttempts = 0
                credential.LockedUntil = None
                credential.MustReset = True
                db.add_all([user, account, credential])

            await revoke_account_sessions(db, str(user.AccountId))
            await revoke_account_execution_contexts(db, str(user.AccountId))
            await db.commit()
            return str(user.Id), created
    finally:
        await engine.dispose()


def main() -> int:
    args = _parser().parse_args()
    try:
        user_id, created = asyncio.run(_bootstrap(args.name, args.phone, args.password))
    except Exception as exc:  # noqa: BLE raising a concise CLI error is intentional
        print(f"bootstrap failed: {exc}", file=sys.stderr)
        return 1

    action = "created" if created else "refreshed"
    print(f"Local platform admin {action}.")
    print(f"  user_id: {user_id}")
    print(f"  phone: {normalize_phone(args.phone)}")
    print(f"  password: {args.password}")
    print("  role: admin")
    print("  database: loopback PostgreSQL only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

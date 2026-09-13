from __future__ import annotations

import json
import importlib
import logging
import re
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.error.account import AccountAuthenticationError
from core.error.server import RateLimit
from core.platform import (
    AUTH_LOCK_ATTEMPTS,
    AUTH_LOCK_MINUTES,
    authenticate_platform,
    create_platform_user,
    generate_initial_password,
    utc_now,
)
from model.account import Account, AccountRole, AccountStatus
from model.platform import (
    EnterpriseStatus,
    PlatformCredential,
    PlatformEnterprise,
    PlatformRole,
    PlatformStatus,
    PlatformUser,
)
from util.password import compare as password_compare


PHONE_PATTERN = re.compile(r"^\d{6}$")
_evidence: list[dict[str, object]] = []
_phone_counter = 0
_platform_router_module = None


def _platform_router():
    global _platform_router_module
    if _platform_router_module is None:
        from test.app_bootstrap import ensure_app

        # A single shared application keeps route registration idempotent no
        # matter which test module runs first.
        ensure_app()
        _platform_router_module = importlib.import_module("router.platform")
    return _platform_router_module


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


def _session_for_auth(user, account, credential):
    return SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                ScalarResult(user),
                ScalarResult(account),
                ScalarResult(credential),
            ]
        ),
        add=Mock(),
        commit=AsyncMock(),
        refresh=AsyncMock(),
    )


def _unique_phone() -> str:
    global _phone_counter
    _phone_counter += 1
    return f"139{_phone_counter:08d}"


def _identity(*, phone: str | None = None, password: str = "246810"):
    account_id = str(uuid.uuid4())
    phone = phone or _unique_phone()
    salt = "11" * 32
    from util.password import hash as password_hash

    account = Account(
        Id=account_id,
        Name="安全测试账号",
        Role=AccountRole.NORMAL,
        Status=AccountStatus.ACTIVE,
    )
    user = PlatformUser(
        Id=str(uuid.uuid4()),
        AccountId=account_id,
        Name="安全测试账号",
        PhoneNormalized=phone,
        PhoneMasked=f"{phone[:3]}****{phone[-4:]}",
        Role=PlatformRole.CUSTOMER,
        Status=PlatformStatus.ACTIVE,
    )
    credential = PlatformCredential(
        AccountId=account_id,
        PasswordHash=password_hash(password, salt),
        PasswordSalt=salt,
        MustReset=True,
        FailedAttempts=0,
        LockedUntil=None,
    )
    return user, account, credential, password


def _record(name: str, **details: object) -> None:
    _evidence.append({"check": name, **details})
    output = Path(__file__).resolve().parents[3] / "output" / "tests" / "m1-sec-02-auth.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "scope": "M1-SEC-02 platform authentication",
                "checks": _evidence,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def pytest_sessionfinish(session, exitstatus):
    output = Path(__file__).resolve().parents[3] / "output" / "tests" / "m1-sec-02-auth.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "scope": "M1-SEC-02 platform authentication",
                "exitStatus": int(exitstatus),
                "checks": _evidence,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_generate_initial_password_is_six_digit_and_random():
    values = [generate_initial_password() for _ in range(32)]

    assert all(PHONE_PATTERN.fullmatch(value) for value in values)
    assert len(set(values)) > 1
    _record("initial_password", samples=len(values), six_digit=True, distinct_values=len(set(values)))


@pytest.mark.asyncio
async def test_create_platform_user_stores_only_salted_hash_and_requires_reset():
    phone = _unique_phone()
    enterprise = PlatformEnterprise(
        Id=str(uuid.uuid4()),
        Name="安全测试企业",
        CustomerCode=f"SEC-{uuid.uuid4().hex[:8]}",
        Status=EnterpriseStatus.ACTIVE,
    )
    db = SimpleNamespace(
        execute=AsyncMock(side_effect=[ScalarResult(None), ScalarResult(enterprise)]),
        add=Mock(),
        flush=AsyncMock(),
    )

    user, initial_password = await create_platform_user(
        db,
        name="安全测试账号",
        phone=phone,
        enterprise_id=str(enterprise.Id),
    )

    credentials = [call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], PlatformCredential)]
    accounts = [call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], Account)]
    assert len(credentials) == 1
    assert len(accounts) == 1
    credential = credentials[0]
    assert user.PhoneNormalized == phone
    assert PHONE_PATTERN.fullmatch(initial_password)
    assert credential.PasswordHash != initial_password
    assert credential.PasswordSalt
    assert credential.PasswordHash != credential.PasswordSalt
    assert password_compare(initial_password, credential.PasswordHash, credential.PasswordSalt)
    assert credential.MustReset is True
    assert accounts[0].Password is None
    _record("credential_storage", salted_hash=True, plaintext_account_password=False, must_reset=True)


@pytest.mark.asyncio
async def test_failed_attempts_lock_after_five_and_locked_account_stays_rejected():
    user, account, credential, password = _identity()
    ip_address = "198.51.100.41"

    for attempt in range(AUTH_LOCK_ATTEMPTS):
        db = _session_for_auth(user, account, credential)
        with pytest.raises(AccountAuthenticationError):
            await authenticate_platform(db, phone=user.PhoneNormalized, password="000000", ip_address=ip_address)
        assert db.commit.await_count == 1

    assert credential.LockedUntil is not None
    assert credential.LockedUntil > utc_now()
    assert credential.FailedAttempts == 0

    locked_db = _session_for_auth(user, account, credential)
    with pytest.raises(AccountAuthenticationError):
        await authenticate_platform(db=locked_db, phone=user.PhoneNormalized, password=password, ip_address=ip_address)
    locked_db.commit.assert_not_awaited()
    _record(
        "failed_attempt_lock",
        attempts=AUTH_LOCK_ATTEMPTS,
        lock_minutes=AUTH_LOCK_MINUTES,
        locked_rejects_correct_password=True,
    )


@pytest.mark.asyncio
async def test_successful_login_clears_failures_and_lock_state():
    user, account, credential, password = _identity()
    credential.FailedAttempts = 3
    credential.LockedUntil = None
    db = _session_for_auth(user, account, credential)

    token, context = await authenticate_platform(
        db,
        phone=user.PhoneNormalized,
        password=password,
        ip_address="198.51.100.42",
    )

    assert token
    assert context.user is user
    assert credential.FailedAttempts == 0
    assert credential.LockedUntil is None
    assert account.LastLoginIp == "198.51.100.42"
    db.commit.assert_awaited_once()
    _record("successful_login_reset", failed_attempts=0, locked_until=None)


@pytest.mark.asyncio
async def test_same_phone_and_ip_is_rate_limited_after_ten_attempts():
    user, account, credential, _ = _identity()
    phone = user.PhoneNormalized
    ip_address = "198.51.100.43"

    for _ in range(10):
        db = _session_for_auth(None, None, None)
        with pytest.raises(AccountAuthenticationError):
            await authenticate_platform(db, phone=phone, password="000000", ip_address=ip_address)

    db = _session_for_auth(None, None, None)
    with pytest.raises(RateLimit):
        await authenticate_platform(db, phone=phone, password="000000", ip_address=ip_address)
    db.execute.assert_not_awaited()
    _record("source_rate_limit", attempts_before_rejection=10, window="15 minutes", key="phone+ip")


@pytest.mark.asyncio
async def test_login_failure_audit_does_not_include_sensitive_values(monkeypatch, caplog):
    platform_router = _platform_router()
    submitted_phone = _unique_phone()
    submitted_password = "864209"
    submitted_token = "token-must-not-be-logged"
    db = SimpleNamespace(add=Mock(), commit=AsyncMock())
    request = SimpleNamespace(
        json={"phone": submitted_phone, "password": submitted_password},
        ctx=SimpleNamespace(db=db),
        headers={"X-Request-Id": "trace-auth-security"},
        client_ip="198.51.100.44",
    )

    async def reject_login(*args, **kwargs):
        raise AccountAuthenticationError()

    monkeypatch.setattr(platform_router, "authenticate_platform", reject_login)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(AccountAuthenticationError) as error:
            await platform_router.PlatformLoginApi().post(request)

    event = db.add.call_args.args[0]
    assert event.Action == "auth.login"
    assert event.Metadata == {"phone": "provided", "rateLimited": False}
    serialized_event = json.dumps(event.Metadata, ensure_ascii=False)
    assert submitted_phone not in serialized_event
    assert submitted_password not in serialized_event
    assert submitted_token not in serialized_event
    assert submitted_password not in str(error.value)
    assert all(submitted_password not in record.getMessage() for record in caplog.records)
    _record("failure_audit_redaction", phone="provided", password=False, token=False, logs_clean=True)


@pytest.mark.asyncio
async def test_rate_limit_login_audit_marks_rate_limited_without_phone_or_token(monkeypatch):
    platform_router = _platform_router()
    submitted_phone = _unique_phone()
    submitted_password = "975310"
    db = SimpleNamespace(add=Mock(), commit=AsyncMock())
    request = SimpleNamespace(
        json={"phone": submitted_phone, "password": submitted_password},
        ctx=SimpleNamespace(db=db),
        headers={"X-Trace-Id": "trace-rate-limit"},
        client_ip="198.51.100.45",
    )

    async def reject_rate_limit(*args, **kwargs):
        raise RateLimit("登录尝试过于频繁，请稍后再试")

    monkeypatch.setattr(platform_router, "authenticate_platform", reject_rate_limit)
    with pytest.raises(RateLimit):
        await platform_router.PlatformLoginApi().post(request)

    event = db.add.call_args.args[0]
    assert event.Action == "auth.login"
    assert event.Metadata == {"phone": "provided", "rateLimited": True}
    serialized_event = json.dumps(event.Metadata, ensure_ascii=False)
    assert submitted_phone not in serialized_event
    assert submitted_password not in serialized_event
    _record("rate_limit_audit_redaction", phone="provided", rate_limited=True, password=False)

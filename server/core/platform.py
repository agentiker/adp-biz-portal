"""Identity, access control, and audit helpers for platform APIs."""

from __future__ import annotations

import binascii
import copy
import hashlib
import hmac
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

import limits
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.error.account import AccountAuthenticationError, AccountUnauthorized
from core.error.platform import PlatformBadRequest, PlatformForbidden, PlatformNotFound
from core.error.server import RateLimit
from core.session import SessionToken
from model.account import Account, AccountRole, AccountStatus
from model.platform import (
    EnterpriseStatus,
    PlatformAuditEvent,
    PlatformAuthSession,
    PlatformConversation,
    PlatformConfigVersion,
    PlatformCredential,
    PlatformDeliveryTask,
    PlatformEnterprise,
    PlatformExecutionContext,
    PlatformMembership,
    PlatformRole,
    PlatformStatus,
    PlatformToolCall,
    PlatformToolDefinition,
    PlatformUser,
)
from util.password import hash as password_hash
from util.password import compare as password_compare


PHONE_PATTERN = re.compile(r"^\+?[0-9][0-9\s-]{8,20}$")
PLATFORM_TOKEN_SOURCE = "platform_login"
ADMIN_ADP_CONTEXT_TOKEN_SOURCE = "admin_adp_chat"
ADMIN_ADP_CONTEXT_TTL_SECONDS = 300
AUTH_LOCK_ATTEMPTS = 5
AUTH_LOCK_MINUTES = 15
PLATFORM_LOGIN_RATE_LIMIT = limits.parse("10/15 minute")
_platform_login_rate_storage = limits.aio.storage.MemoryStorage()
_platform_login_rate_limiter = limits.aio.strategies.MovingWindowRateLimiter(
    _platform_login_rate_storage
)

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    PlatformRole.CUSTOMER: frozenset({"shipment.read"}),
    PlatformRole.STAFF: frozenset({"shipment.read", "platform.read"}),
    PlatformRole.ADMIN: frozenset({"platform.read", "platform.manage"}),
    PlatformRole.OPS: frozenset({"platform.read", "platform.diagnose"}),
}

PLATFORM_CONFIG_STATUSES = frozenset({"draft", "published", "rolled_back"})
PLATFORM_CONFIG_FEATURES = ("portal", "m3ReadOnly", "audit", "webChannel")
DEFAULT_PLATFORM_CONFIG: dict[str, Any] = {
    "items": ["客户登录与会话", "M3 只读工具", "企业隔离", "审计记录"],
    "featureFlags": {
        "portal": True,
        "m3ReadOnly": True,
        "audit": True,
        "webChannel": True,
    },
    "notes": "",
}


@dataclass(frozen=True)
class PlatformContext:
    user: PlatformUser
    account: Account
    session: PlatformAuthSession
    permissions: frozenset[str]


@dataclass(frozen=True)
class PlatformExecution:
    """Validated identity and enterprise scope for one ADP tool execution."""

    context: PlatformExecutionContext
    user: PlatformUser
    account: Account
    enterprise: PlatformEnterprise
    session: PlatformAuthSession
    permissions: frozenset[str]


def execution_token_hash(token: str) -> str:
    """Return the non-reversible digest used to look up an execution token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def is_adp_service_token_valid(provided: str | None, expected: str | None) -> bool:
    """Compare internal service credentials without accepting an empty secret."""
    if not isinstance(provided, str) or not isinstance(expected, str) or not provided or not expected:
        return False
    return hmac.compare_digest(provided, expected)


def _validate_context_text(value: Any, *, field: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise PlatformBadRequest(f"{field}格式不正确")
    normalized = value.strip()
    if not normalized or len(normalized) > max_length:
        raise PlatformBadRequest(f"{field}格式不正确")
    return normalized


def _validate_uuid_text(value: Any, *, field: str) -> str:
    """Normalize route-provided UUIDs before they reach a database query."""
    if not isinstance(value, str) or not value.strip():
        raise PlatformBadRequest(f"{field}格式不正确")
    try:
        return str(uuid.UUID(value.strip()))
    except ValueError as exc:
        raise PlatformBadRequest(f"{field}格式不正确") from exc


def validate_tool_request_id(value: Any) -> str:
    """Require a caller-generated id so repeated callbacks can be rejected."""
    return _validate_context_text(value, field="工具请求 ID", max_length=128)


def _permission_version(user: PlatformUser, membership: PlatformMembership) -> str:
    # Role and membership role are deliberately included in the snapshot. A
    # role narrowing or enterprise unbinding invalidates old contexts without
    # relying on an eventually-consistent cache.
    return f"user-role:{user.Role}|membership-role:{membership.MembershipRole}"


def utc_now() -> datetime:
    """Return a naive UTC datetime compatible with the legacy schema."""
    return datetime.now(UTC).replace(tzinfo=None)


def normalize_phone(phone: str) -> str:
    if not isinstance(phone, str):
        raise PlatformBadRequest("手机号格式不正确")
    value = phone.strip()
    if not PHONE_PATTERN.fullmatch(value):
        raise PlatformBadRequest("手机号格式不正确")
    digits = re.sub(r"\D", "", value)
    if digits.startswith("86") and len(digits) == 13:
        digits = digits[2:]
    if len(digits) != 11 or not digits.startswith("1"):
        raise PlatformBadRequest("手机号格式不正确")
    return digits


def mask_phone(phone: str) -> str:
    normalized = normalize_phone(phone)
    return f"{normalized[:3]}****{normalized[-4:]}"


def generate_initial_password() -> str:
    return str(secrets.randbelow(900000) + 100000)


def _new_salt() -> str:
    return binascii.hexlify(secrets.token_bytes(32)).decode()


def permissions_for_role(role: str) -> frozenset[str]:
    return ROLE_PERMISSIONS.get(role, frozenset())


def _validate_role(role: str) -> str:
    if role not in {item.value for item in PlatformRole}:
        raise PlatformBadRequest("角色不受支持")
    return role


def default_platform_config_payload() -> dict[str, Any]:
    """Return a fresh copy so callers cannot mutate the process default."""
    return copy.deepcopy(DEFAULT_PLATFORM_CONFIG)


def validate_platform_config(payload: Any) -> tuple[dict[str, Any], list[str]]:
    """Normalize the small first-release config contract before persistence."""
    errors: list[str] = []
    if not isinstance(payload, dict):
        return {}, ["配置必须是 JSON 对象"]

    allowed = {"items", "featureFlags", "notes"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        errors.append(f"不支持的配置字段：{', '.join(unknown)}")

    items = payload.get("items")
    normalized_items: list[str] = []
    if not isinstance(items, list) or not items:
        errors.append("配置能力列表不能为空")
    elif len(items) > 20:
        errors.append("配置能力列表不能超过 20 项")
    else:
        for index, item in enumerate(items):
            if not isinstance(item, str) or not item.strip() or len(item.strip()) > 80:
                errors.append(f"配置能力第 {index + 1} 项格式不正确")
            else:
                normalized_items.append(item.strip())
        if len(set(normalized_items)) != len(normalized_items):
            errors.append("配置能力列表不能包含重复项")

    feature_flags = payload.get("featureFlags", {})
    normalized_flags: dict[str, bool] = {}
    if not isinstance(feature_flags, dict):
        errors.append("featureFlags 必须是 JSON 对象")
    else:
        unknown_flags = sorted(set(feature_flags) - set(PLATFORM_CONFIG_FEATURES))
        if unknown_flags:
            errors.append(f"不支持的功能开关：{', '.join(unknown_flags)}")
        for feature in PLATFORM_CONFIG_FEATURES:
            value = feature_flags.get(feature, DEFAULT_PLATFORM_CONFIG["featureFlags"][feature])
            if not isinstance(value, bool):
                errors.append(f"功能开关 {feature} 必须是布尔值")
            else:
                normalized_flags[feature] = value

    notes = payload.get("notes", "")
    if not isinstance(notes, str) or len(notes.strip()) > 500:
        errors.append("配置备注不能超过 500 个字符")
    normalized = {"items": normalized_items, "featureFlags": normalized_flags, "notes": notes.strip() if isinstance(notes, str) else ""}
    return normalized, errors


def serialize_config_version(version: PlatformConfigVersion | None) -> dict[str, Any] | None:
    if version is None:
        return None
    return {
        "id": str(version.Id) if version.Id else None,
        "version": int(version.Version),
        "status": version.Status,
        "payload": version.Payload or {},
        "validationErrors": list(version.ValidationErrors or []),
        "createdByAccountId": str(version.CreatedByAccountId) if version.CreatedByAccountId else None,
        "publishedByAccountId": str(version.PublishedByAccountId) if version.PublishedByAccountId else None,
        "rolledBackByAccountId": str(version.RolledBackByAccountId) if version.RolledBackByAccountId else None,
        "createdAt": version.CreatedAt.isoformat() if version.CreatedAt else "",
        "updatedAt": version.UpdatedAt.isoformat() if version.UpdatedAt else "",
        "publishedAt": version.PublishedAt.isoformat() if version.PublishedAt else None,
        "rolledBackAt": version.RolledBackAt.isoformat() if version.RolledBackAt else None,
        "rollbackSourceVersion": int(version.RollbackSourceVersion) if version.RollbackSourceVersion else None,
    }


async def ensure_platform_config(db: AsyncSession) -> PlatformConfigVersion:
    """Seed a published v1 so every installation has an explicit config."""
    current = (
        await db.execute(
            select(PlatformConfigVersion)
            .where(PlatformConfigVersion.Status == "published")
            .order_by(PlatformConfigVersion.Version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if current is not None:
        return current
    current = PlatformConfigVersion(
        Version=1,
        Status="published",
        Payload=default_platform_config_payload(),
        ValidationErrors=[],
        PublishedAt=utc_now(),
    )
    db.add(current)
    await db.flush()
    return current


async def get_platform_config_state(db: AsyncSession, *, history_limit: int = 20) -> dict[str, Any]:
    published = (
        await db.execute(
            select(PlatformConfigVersion)
            .where(PlatformConfigVersion.Status == "published")
            .order_by(PlatformConfigVersion.Version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    draft = (
        await db.execute(
            select(PlatformConfigVersion)
            .where(PlatformConfigVersion.Status == "draft")
            .order_by(PlatformConfigVersion.Version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    history = list(
        (
            await db.execute(
                select(PlatformConfigVersion)
                .order_by(PlatformConfigVersion.Version.desc())
                .limit(history_limit)
            )
        ).scalars().all()
    )
    if published is None and not history:
        # Read-only callers still receive a useful shape before startup seeding.
        fallback = {
            "id": None,
            "version": 1,
            "status": "published",
            "payload": default_platform_config_payload(),
            "validationErrors": [],
            "createdByAccountId": None,
            "publishedByAccountId": None,
            "rolledBackByAccountId": None,
            "createdAt": "",
            "updatedAt": "",
            "publishedAt": None,
            "rolledBackAt": None,
            "rollbackSourceVersion": None,
        }
        return {"published": fallback, "draft": None, "history": [fallback]}
    return {
        "published": serialize_config_version(published),
        "draft": serialize_config_version(draft),
        "history": [item for item in (serialize_config_version(row) for row in history) if item is not None],
    }


async def save_platform_config_draft(
    db: AsyncSession, *, payload: Any, actor_account_id: str | None
) -> PlatformConfigVersion:
    normalized, errors = validate_platform_config(payload)
    if errors:
        raise PlatformBadRequest("配置校验失败：" + "；".join(errors))
    draft = (
        await db.execute(
            select(PlatformConfigVersion)
            .where(PlatformConfigVersion.Status == "draft")
            .order_by(PlatformConfigVersion.Version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if draft is None:
        latest_version = (
            await db.execute(select(func.max(PlatformConfigVersion.Version)))
        ).scalar_one() or 0
        draft = PlatformConfigVersion(
            Version=int(latest_version) + 1,
            Status="draft",
            Payload=normalized,
            ValidationErrors=[],
            CreatedByAccountId=actor_account_id,
        )
    else:
        draft.Payload = normalized
        draft.ValidationErrors = []
        draft.CreatedByAccountId = actor_account_id
        draft.UpdatedAt = utc_now()
    db.add(draft)
    await db.flush()
    return draft


async def publish_platform_config(db: AsyncSession, *, actor_account_id: str | None) -> PlatformConfigVersion:
    draft = (
        await db.execute(
            select(PlatformConfigVersion)
            .where(PlatformConfigVersion.Status == "draft")
            .order_by(PlatformConfigVersion.Version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if draft is None:
        raise PlatformNotFound("没有可发布的配置草稿")
    if draft.ValidationErrors:
        raise PlatformBadRequest("配置草稿未通过校验")
    current = (
        await db.execute(
            select(PlatformConfigVersion)
            .where(PlatformConfigVersion.Status == "published")
            .order_by(PlatformConfigVersion.Version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    now = utc_now()
    if current is not None:
        current.Status = "rolled_back"
        current.RolledBackAt = now
        current.RollbackSourceVersion = int(draft.Version)
        current.RolledBackByAccountId = actor_account_id
        db.add(current)
    draft.Status = "published"
    draft.PublishedAt = now
    draft.PublishedByAccountId = actor_account_id
    draft.UpdatedAt = now
    db.add(draft)
    await db.flush()
    return draft


async def rollback_platform_config(
    db: AsyncSession, *, version: int, actor_account_id: str | None
) -> PlatformConfigVersion:
    try:
        target_version = int(version)
    except (TypeError, ValueError) as exc:
        raise PlatformBadRequest("回滚版本格式不正确") from exc
    target = (
        await db.execute(
            select(PlatformConfigVersion).where(PlatformConfigVersion.Version == target_version)
        )
    ).scalar_one_or_none()
    if target is None or target.Status == "draft":
        raise PlatformNotFound("目标配置版本不存在或仍是草稿")
    current = (
        await db.execute(
            select(PlatformConfigVersion)
            .where(PlatformConfigVersion.Status == "published")
            .order_by(PlatformConfigVersion.Version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if current is None or int(current.Version) == target_version:
        raise PlatformBadRequest("目标版本已经是当前发布版本")
    now = utc_now()
    current.Status = "rolled_back"
    current.RolledBackAt = now
    current.RollbackSourceVersion = target_version
    current.RolledBackByAccountId = actor_account_id
    target.Status = "published"
    target.PublishedAt = now
    target.PublishedByAccountId = actor_account_id
    target.RolledBackAt = None
    target.RollbackSourceVersion = None
    target.RolledBackByAccountId = None
    target.UpdatedAt = now
    db.add(current)
    db.add(target)
    await db.flush()
    return target


async def create_platform_user(
    db: AsyncSession,
    *,
    name: str,
    phone: str,
    role: str = PlatformRole.CUSTOMER,
    enterprise_id: Optional[str] = None,
    initial_password: Optional[str] = None,
) -> tuple[PlatformUser, str]:
    """Create an account and its platform credential in one transaction.

    The returned password is intentionally only available to the caller that
    performs provisioning. It is never placed in an audit event.
    """
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 255:
        raise PlatformBadRequest("姓名不能为空")
    normalized = normalize_phone(phone)
    role = _validate_role(role)
    if role == PlatformRole.CUSTOMER and not enterprise_id:
        raise PlatformBadRequest("客户账号必须绑定企业")

    duplicate = (
        await db.execute(select(PlatformUser).where(PlatformUser.PhoneNormalized == normalized))
    ).scalar_one_or_none()
    if duplicate is not None:
        raise PlatformBadRequest("该手机号已存在")

    enterprise = None
    if enterprise_id:
        enterprise = (
            await db.execute(select(PlatformEnterprise).where(PlatformEnterprise.Id == enterprise_id))
        ).scalar_one_or_none()
        if enterprise is None or enterprise.Status != EnterpriseStatus.ACTIVE:
            raise PlatformBadRequest("企业不存在或已停用")

    account = Account(
        Name=name.strip(),
        Role=AccountRole.ADMIN if role == PlatformRole.ADMIN else AccountRole.NORMAL,
        Status=AccountStatus.ACTIVE,
    )
    db.add(account)
    await db.flush()

    clear_password = initial_password or generate_initial_password()
    if not re.fullmatch(r"\d{6}", clear_password):
        raise PlatformBadRequest("初始口令必须为 6 位数字")
    salt = _new_salt()
    platform_user = PlatformUser(
        AccountId=account.Id,
        Name=name.strip(),
        PhoneNormalized=normalized,
        PhoneMasked=f"{normalized[:3]}****{normalized[-4:]}",
        Role=role,
        Status=PlatformStatus.ACTIVE,
    )
    db.add(platform_user)
    db.add(
        PlatformCredential(
            AccountId=account.Id,
            PasswordHash=password_hash(clear_password, salt),
            PasswordSalt=salt,
            MustReset=True,
        )
    )
    await db.flush()
    if enterprise is not None:
        db.add(
            PlatformMembership(
                UserId=platform_user.Id,
                EnterpriseId=enterprise.Id,
                MembershipRole=role,
                Active=True,
            )
        )
    return platform_user, clear_password


async def update_platform_user_access(
    db: AsyncSession,
    *,
    user_id: str,
    role: Any = None,
    enterprise_ids: Any = None,
) -> tuple[PlatformUser, list[PlatformMembership]]:
    """Update a user's role and enterprise scope as one revocable change.

    ``enterprise_ids=None`` preserves the current scope; an explicit empty
    list clears it (which is only valid for non-customer roles). Every active
    membership receives the new role, and existing execution contexts are
    revoked so a narrowed scope takes effect immediately.
    """
    normalized_user_id = _validate_uuid_text(user_id, field="用户 ID")
    user = (
        await db.execute(select(PlatformUser).where(PlatformUser.Id == normalized_user_id))
    ).scalar_one_or_none()
    if user is None:
        raise PlatformNotFound("用户不存在")
    account = await _account_for_user(db, user)
    if account is None:
        raise PlatformNotFound("用户账号不存在")

    target_role = _validate_role(role) if role is not None else user.Role
    memberships = list(
        (
            await db.execute(
                select(PlatformMembership).where(PlatformMembership.UserId == user.Id)
            )
        ).scalars().all()
    )

    selected_ids: list[str] | None = None
    if enterprise_ids is not None:
        if not isinstance(enterprise_ids, list):
            raise PlatformBadRequest("enterpriseIds 必须是 JSON 数组")
        if len(enterprise_ids) > 50:
            raise PlatformBadRequest("企业范围不能超过 50 家")
        selected_ids = []
        for enterprise_id in enterprise_ids:
            normalized_id = _validate_uuid_text(enterprise_id, field="企业 ID")
            if normalized_id in selected_ids:
                raise PlatformBadRequest("企业范围不能包含重复项")
            selected_ids.append(normalized_id)

        enterprises = list(
            (
                await db.execute(
                    select(PlatformEnterprise).where(PlatformEnterprise.Id.in_(selected_ids))
                )
            ).scalars().all()
        )
        enterprise_by_id = {str(item.Id): item for item in enterprises}
        if len(enterprise_by_id) != len(selected_ids):
            raise PlatformBadRequest("企业不存在")
        if any(item.Status != EnterpriseStatus.ACTIVE for item in enterprises):
            raise PlatformBadRequest("不能绑定已停用企业")

    current_active_ids = {
        str(item.EnterpriseId) for item in memberships if item.Active
    }
    effective_ids = set(selected_ids) if selected_ids is not None else current_active_ids
    if target_role == PlatformRole.CUSTOMER and not effective_ids:
        raise PlatformBadRequest("客户账号必须绑定至少一家企业")

    user.Role = target_role
    account.Role = AccountRole.ADMIN if target_role == PlatformRole.ADMIN else AccountRole.NORMAL
    db.add(user)
    db.add(account)

    existing_ids: set[str] = set()
    for membership in memberships:
        membership_id = str(membership.EnterpriseId)
        existing_ids.add(membership_id)
        if selected_ids is not None:
            membership.Active = membership_id in effective_ids
        if membership.Active:
            membership.MembershipRole = target_role
        db.add(membership)

    if selected_ids is not None:
        for enterprise_id in selected_ids:
            if enterprise_id not in existing_ids:
                db.add(
                    PlatformMembership(
                        UserId=user.Id,
                        EnterpriseId=enterprise_id,
                        MembershipRole=target_role,
                        Active=True,
                    )
                )

    await revoke_account_execution_contexts(db, str(account.Id))
    await db.flush()
    return user, [item for item in memberships if item.Active]


async def create_enterprise(
    db: AsyncSession, *, name: str, customer_code: str
) -> PlatformEnterprise:
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 255:
        raise PlatformBadRequest("企业名称不能为空")
    if not isinstance(customer_code, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,127}", customer_code.strip()):
        raise PlatformBadRequest("M3 客户编码格式不正确")
    duplicate = (
        await db.execute(
            select(PlatformEnterprise).where(PlatformEnterprise.CustomerCode == customer_code.strip())
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise PlatformBadRequest("M3 客户编码已存在")
    enterprise = PlatformEnterprise(Name=name.strip(), CustomerCode=customer_code.strip())
    db.add(enterprise)
    await db.flush()
    return enterprise


async def find_platform_user_by_phone(db: AsyncSession, phone: str) -> PlatformUser | None:
    normalized = normalize_phone(phone)
    return (
        await db.execute(select(PlatformUser).where(PlatformUser.PhoneNormalized == normalized))
    ).scalar_one_or_none()


async def _account_for_user(db: AsyncSession, user: PlatformUser) -> Account | None:
    return (await db.execute(select(Account).where(Account.Id == user.AccountId))).scalar_one_or_none()


async def authenticate_platform(
    db: AsyncSession, *, phone: str, password: str, ip_address: str | None = None
) -> tuple[str, PlatformContext]:
    """Authenticate a phone credential and issue a revocable platform token."""
    normalized = normalize_phone(phone)
    source = (ip_address or "unknown").strip()[:64] or "unknown"
    rate_key = f"platform-login:{normalized}:{source}"
    if not await _platform_login_rate_limiter.hit(PLATFORM_LOGIN_RATE_LIMIT, rate_key):
        raise RateLimit("登录尝试过于频繁，请稍后再试")
    user = (
        await db.execute(select(PlatformUser).where(PlatformUser.PhoneNormalized == normalized))
    ).scalar_one_or_none()
    account = await _account_for_user(db, user) if user is not None else None
    credential = None
    if user is not None:
        credential = (
            await db.execute(
                select(PlatformCredential)
                .where(PlatformCredential.AccountId == user.AccountId)
                .with_for_update()
            )
        ).scalar_one_or_none()

    now = utc_now()
    invalid = (
        user is None
        or account is None
        or credential is None
        or user.Status != PlatformStatus.ACTIVE
        or account.Status in {AccountStatus.BANNED, AccountStatus.PENDING}
        or (credential.LockedUntil is not None and credential.LockedUntil > now)
        or not isinstance(password, str)
        or not re.fullmatch(r"\d{6}", password)
        or not password_compare(password, credential.PasswordHash, credential.PasswordSalt)
    )
    if invalid:
        if credential is not None and credential.LockedUntil is None:
            credential.FailedAttempts = int(credential.FailedAttempts or 0) + 1
            if credential.FailedAttempts >= AUTH_LOCK_ATTEMPTS:
                credential.LockedUntil = now + timedelta(minutes=AUTH_LOCK_MINUTES)
                credential.FailedAttempts = 0
            db.add(credential)
            await db.commit()
        raise AccountAuthenticationError()

    credential.FailedAttempts = 0
    credential.LockedUntil = None
    db.add(credential)
    account.LastLoginAt = now
    account.LastLoginIp = ip_address
    db.add(account)

    token_id = uuid.uuid4().hex
    expiry = now + timedelta(hours=24)
    payload = {
        "AccountId": str(account.Id),
        "PlatformUserId": str(user.Id),
        "token_source": PLATFORM_TOKEN_SOURCE,
        "jti": token_id,
        "exp": int(expiry.replace(tzinfo=UTC).timestamp()),
    }
    token = SessionToken.create(payload)
    auth_session = PlatformAuthSession(
        AccountId=account.Id,
        TokenId=token_id,
        ExpiresAt=expiry,
    )
    db.add(auth_session)
    await db.commit()
    await db.refresh(auth_session)
    context = PlatformContext(user=user, account=account, session=auth_session, permissions=permissions_for_role(user.Role))
    return token, context


async def load_platform_context(db: AsyncSession, token: str) -> PlatformContext:
    payload = SessionToken.check(token)
    if payload.get("token_source") != PLATFORM_TOKEN_SOURCE or not payload.get("jti"):
        raise AccountUnauthorized("平台登录态无效")
    session = (
        await db.execute(select(PlatformAuthSession).where(PlatformAuthSession.TokenId == payload["jti"]))
    ).scalar_one_or_none()
    now = utc_now()
    if session is None or session.RevokedAt is not None or session.ExpiresAt <= now:
        raise AccountUnauthorized("平台登录态已失效")
    if str(session.AccountId) != str(payload.get("AccountId")):
        raise AccountUnauthorized("平台登录态无效")
    user = (
        await db.execute(select(PlatformUser).where(PlatformUser.AccountId == session.AccountId))
    ).scalar_one_or_none()
    account = (await db.execute(select(Account).where(Account.Id == session.AccountId))).scalar_one_or_none()
    if (
        user is None
        or account is None
        or user.Status != PlatformStatus.ACTIVE
        or account.Status in {AccountStatus.BANNED, AccountStatus.PENDING}
    ):
        raise AccountUnauthorized("账号已停用")
    if str(user.Id) != str(payload.get("PlatformUserId")):
        raise AccountUnauthorized("平台登录态无效")
    session.LastSeenAt = now
    db.add(session)
    return PlatformContext(user=user, account=account, session=session, permissions=permissions_for_role(user.Role))


def create_admin_adp_context_token(
    platform_context: PlatformContext,
    *,
    ttl_seconds: int = ADMIN_ADP_CONTEXT_TTL_SECONDS,
) -> tuple[str, datetime]:
    """Create a short-lived legacy-compatible token for the Admin ADP debugger."""
    lifetime = max(30, min(int(ttl_seconds), 900))
    expires_at = utc_now() + timedelta(seconds=lifetime)
    payload = {
        "AccountId": str(platform_context.account.Id),
        "token_source": ADMIN_ADP_CONTEXT_TOKEN_SOURCE,
        "platform_session_id": str(platform_context.session.Id),
        "jti": uuid.uuid4().hex,
        "exp": int(expires_at.replace(tzinfo=UTC).timestamp()),
    }
    return SessionToken.create(payload), expires_at


def require_permission(context: PlatformContext, permission: str) -> None:
    if permission not in context.permissions:
        raise PlatformForbidden("当前账号没有执行此操作的权限")


async def get_enterprises_for_user(db: AsyncSession, user: PlatformUser) -> list[PlatformEnterprise]:
    result = await db.execute(
        select(PlatformEnterprise)
        .join(PlatformMembership, PlatformMembership.EnterpriseId == PlatformEnterprise.Id)
        .where(PlatformMembership.UserId == user.Id, PlatformMembership.Active.is_(True), PlatformEnterprise.Status == EnterpriseStatus.ACTIVE)
        .order_by(PlatformEnterprise.Name)
    )
    return list(result.scalars().all())


async def get_enterprise_for_user(db: AsyncSession, user: PlatformUser) -> PlatformEnterprise | None:
    enterprises = await get_enterprises_for_user(db, user)
    return enterprises[0] if enterprises else None


async def _membership_for_user(
    db: AsyncSession, *, user_id: str, enterprise_id: str
) -> PlatformMembership | None:
    return (
        await db.execute(
            select(PlatformMembership).where(
                PlatformMembership.UserId == user_id,
                PlatformMembership.EnterpriseId == enterprise_id,
                PlatformMembership.Active.is_(True),
            )
        )
    ).scalar_one_or_none()


async def issue_execution_context(
    db: AsyncSession,
    *,
    platform_context: PlatformContext,
    agent_id: str,
    channel: str = "web",
    enterprise_id: str | None = None,
    conversation_id: str | None = None,
    run_id: str | None = None,
    ttl_seconds: int | None = None,
) -> tuple[str, PlatformExecutionContext]:
    """Issue a short-lived, scoped token for an internal ADP execution.

    The enterprise and permissions are derived from the authenticated platform
    session. An optional enterprise/conversation identifier is accepted only
    after ownership checks; callers cannot use it to widen their scope.
    """
    agent = _validate_context_text(agent_id, field="Agent ID", max_length=128)
    channel_name = _validate_context_text(channel, field="渠道", max_length=32)
    selected_enterprise = None
    if enterprise_id is not None:
        selected_enterprise = (
            await db.execute(
                select(PlatformEnterprise).where(PlatformEnterprise.Id == enterprise_id)
            )
        ).scalar_one_or_none()
        if selected_enterprise is None:
            raise PlatformForbidden("当前账号没有可访问的企业范围")
        membership = await _membership_for_user(
            db, user_id=str(platform_context.user.Id), enterprise_id=str(selected_enterprise.Id)
        )
    else:
        selected_enterprise = await get_enterprise_for_user(db, platform_context.user)
        membership = (
            await _membership_for_user(
                db,
                user_id=str(platform_context.user.Id),
                enterprise_id=str(selected_enterprise.Id),
            )
            if selected_enterprise is not None
            else None
        )
    if selected_enterprise is None or selected_enterprise.Status != EnterpriseStatus.ACTIVE or membership is None:
        raise PlatformForbidden("当前账号没有可访问的企业范围")

    selected_conversation_id: str | None = None
    if conversation_id is not None:
        selected_conversation_id = _validate_context_text(conversation_id, field="会话 ID", max_length=64)
        try:
            uuid.UUID(selected_conversation_id)
        except ValueError as exc:
            raise PlatformBadRequest("会话 ID 格式不正确") from exc
        conversation = (
            await db.execute(
                select(PlatformConversation).where(
                    PlatformConversation.Id == selected_conversation_id,
                    PlatformConversation.AccountId == platform_context.account.Id,
                    PlatformConversation.EnterpriseId == selected_enterprise.Id,
                )
            )
        ).scalar_one_or_none()
        if conversation is None:
            raise PlatformNotFound("会话不存在或无权访问")

    lifetime = 300 if ttl_seconds is None else int(ttl_seconds)
    if lifetime < 30 or lifetime > 900:
        raise PlatformBadRequest("执行上下文有效期不受支持")
    now = utc_now()
    raw_token = f"pct_{secrets.token_urlsafe(32)}"
    execution = PlatformExecutionContext(
        TokenHash=execution_token_hash(raw_token),
        UserId=platform_context.user.Id,
        AccountId=platform_context.account.Id,
        EnterpriseId=selected_enterprise.Id,
        PlatformSessionId=platform_context.session.Id,
        ConversationId=selected_conversation_id,
        AgentId=agent,
        Channel=channel_name,
        RunId=_validate_context_text(run_id, field="执行轮次 ID", max_length=64) if run_id else uuid.uuid4().hex,
        PermissionVersion=_permission_version(platform_context.user, membership),
        ExpiresAt=now + timedelta(seconds=lifetime),
    )
    db.add(execution)
    await db.flush()
    return raw_token, execution


async def load_execution_context(
    db: AsyncSession,
    *,
    token: str,
    tool_name: str,
    request_id: str,
) -> PlatformExecution:
    """Validate token, current identity scope, tool policy and replay state."""
    if not isinstance(token, str) or not token.startswith("pct_") or len(token) < 40:
        raise AccountUnauthorized("执行上下文无效")
    tool = _validate_context_text(tool_name, field="工具名称", max_length=128)
    request = validate_tool_request_id(request_id)
    context = (
        await db.execute(
            select(PlatformExecutionContext).where(
                PlatformExecutionContext.TokenHash == execution_token_hash(token)
            )
        )
    ).scalar_one_or_none()
    now = utc_now()
    if context is None or context.RevokedAt is not None or context.ExpiresAt <= now:
        raise AccountUnauthorized("执行上下文已失效")

    user = (await db.execute(select(PlatformUser).where(PlatformUser.Id == context.UserId))).scalar_one_or_none()
    account = (await db.execute(select(Account).where(Account.Id == context.AccountId))).scalar_one_or_none()
    enterprise = (
        await db.execute(select(PlatformEnterprise).where(PlatformEnterprise.Id == context.EnterpriseId))
    ).scalar_one_or_none()
    session = (
        await db.execute(select(PlatformAuthSession).where(PlatformAuthSession.Id == context.PlatformSessionId))
    ).scalar_one_or_none()
    membership = await _membership_for_user(
        db, user_id=str(context.UserId), enterprise_id=str(context.EnterpriseId)
    )
    if (
        user is None
        or account is None
        or enterprise is None
        or session is None
        or membership is None
        or user.Status != PlatformStatus.ACTIVE
        or account.Status in {AccountStatus.BANNED, AccountStatus.PENDING}
        or enterprise.Status != EnterpriseStatus.ACTIVE
        or session.RevokedAt is not None
        or session.ExpiresAt <= now
        or str(session.AccountId) != str(context.AccountId)
        or _permission_version(user, membership) != context.PermissionVersion
    ):
        raise AccountUnauthorized("执行上下文已失效")

    permissions = permissions_for_role(user.Role)
    definition = (
        await db.execute(
            select(PlatformToolDefinition).where(
                PlatformToolDefinition.Name == tool,
                PlatformToolDefinition.Enabled.is_(True),
                PlatformToolDefinition.ReadOnly.is_(True),
            )
        )
    ).scalar_one_or_none()
    if definition is None or definition.Permission not in permissions:
        raise PlatformForbidden("当前执行上下文没有该工具权限")

    previous = (
        await db.execute(
            select(PlatformToolCall).where(
                PlatformToolCall.ExecutionContextId == context.Id,
                PlatformToolCall.RequestId == request,
            )
        )
    ).scalar_one_or_none()
    # A call left in ``started`` state can be recovered after a transient
    # worker failure. Completed calls remain replay-protected.
    if previous is not None and getattr(previous, "Status", None) != "started":
        raise PlatformForbidden("工具请求已处理")
    return PlatformExecution(
        context=context,
        user=user,
        account=account,
        enterprise=enterprise,
        session=session,
        permissions=permissions,
    )


async def claim_tool_call(
    db: AsyncSession,
    *,
    execution: PlatformExecution,
    tool_name: str,
    request_id: str,
    trace_id: str,
    query: str | None = None,
) -> PlatformToolCall:
    """Claim a request before touching M3; recover an unfinished call safely."""
    request = validate_tool_request_id(request_id)
    existing = (
        await db.execute(
            select(PlatformToolCall).where(PlatformToolCall.RequestId == request)
        )
    ).scalar_one_or_none()
    if existing is not None:
        previous_context = await db.get(PlatformExecutionContext, existing.ExecutionContextId)
        same_scope = (
            previous_context is not None
            and previous_context.UserId == execution.context.UserId
            and previous_context.AccountId == execution.context.AccountId
            and previous_context.EnterpriseId == execution.context.EnterpriseId
            and previous_context.ConversationId == execution.context.ConversationId
            and previous_context.RunId == execution.context.RunId
            and previous_context.AgentId == execution.context.AgentId
            and previous_context.Channel == execution.context.Channel
        )
        if same_scope and existing.Status == "started":
            return existing
        raise PlatformForbidden("工具请求已处理")
    call = PlatformToolCall(
        ExecutionContextId=execution.context.Id,
        ToolName=_validate_context_text(tool_name, field="工具名称", max_length=128),
        RequestId=request,
        QueryHash=hashlib.sha256(query.strip().upper().encode("utf-8")).hexdigest() if query else None,
        TraceId=_validate_context_text(trace_id, field="Trace ID", max_length=64),
        Status="started",
    )
    db.add(call)
    await db.flush()
    return call


async def complete_tool_call(
    db: AsyncSession,
    *,
    call: PlatformToolCall,
    status: str,
    outcome: str,
    evidence: list[dict[str, Any]] | None = None,
) -> None:
    call.Status = _validate_context_text(status, field="工具状态", max_length=32)
    call.Outcome = _validate_context_text(outcome, field="工具结果", max_length=64)
    call.Evidence = evidence or []
    call.CompletedAt = utc_now()
    db.add(call)


async def revoke_account_execution_contexts(db: AsyncSession, account_id: str) -> None:
    await db.execute(
        update(PlatformExecutionContext)
        .where(PlatformExecutionContext.AccountId == account_id, PlatformExecutionContext.RevokedAt.is_(None))
        .values(RevokedAt=func.current_timestamp())
    )


async def create_audit(
    db: AsyncSession,
    *,
    actor_account_id: str | None,
    action: str,
    target_type: str,
    target_id: str | None,
    trace_id: str,
    outcome: str = "success",
    metadata: dict[str, Any] | None = None,
) -> PlatformAuditEvent:
    event = PlatformAuditEvent(
        ActorAccountId=actor_account_id,
        Action=action,
        TargetType=target_type,
        TargetId=target_id,
        TraceId=trace_id,
        Outcome=outcome,
        Metadata=metadata,
    )
    db.add(event)
    return event


async def revoke_account_sessions(db: AsyncSession, account_id: str) -> None:
    await db.execute(
        update(PlatformAuthSession)
        .where(PlatformAuthSession.AccountId == account_id, PlatformAuthSession.RevokedAt.is_(None))
        .values(RevokedAt=func.current_timestamp())
    )


async def revoke_account_delivery_tasks(db: AsyncSession, account_id: str) -> int:
    """Fail queued reply tasks when the account can no longer receive them.

    Reply payloads carry the account scope because the worker runs after the
    request transaction has ended. Only non-terminal tasks are changed; a
    successful or uncertain provider outcome must remain immutable.
    """
    tasks = list(
        (
            await db.execute(
                select(PlatformDeliveryTask).where(
                    PlatformDeliveryTask.TaskType == "platform.reply",
                    PlatformDeliveryTask.Status.in_(("queued", "running")),
                )
            )
        ).scalars().all()
    )
    now = utc_now()
    revoked = 0
    for task in tasks:
        payload = task.Payload if isinstance(task.Payload, dict) else {}
        if str(payload.get("accountId") or "") != str(account_id):
            continue
        task.Status = "failed"
        task.LastError = "authorization_revoked"
        task.CompletedAt = now
        task.LeaseOwner = None
        task.LeaseUntil = None
        db.add(task)
        revoked += 1
    if revoked:
        await db.flush()
    return revoked


async def ensure_platform_tools(db: AsyncSession) -> None:
    definitions = (
        ("shipment.lookup", "1.0", "shipment.read"),
        ("shipment.schedule", "1.0", "shipment.read"),
        ("shipment.milestones", "1.0", "shipment.read"),
    )
    for name, version, permission in definitions:
        current = (
            await db.execute(select(PlatformToolDefinition).where(PlatformToolDefinition.Name == name))
        ).scalar_one_or_none()
        if current is None:
            db.add(PlatformToolDefinition(Name=name, Version=version, Permission=permission, ReadOnly=True, Enabled=True))
    await db.flush()


def serialize_user(user: PlatformUser) -> dict[str, str]:
    return {
        "id": str(user.Id),
        "name": user.Name,
        "phone": user.PhoneMasked,
        "role": user.Role,
        "roleLabel": {
            PlatformRole.CUSTOMER: "客户员工",
            PlatformRole.STAFF: "客服 / 销售",
            PlatformRole.ADMIN: "平台管理员",
            PlatformRole.OPS: "运维人员",
        }.get(user.Role, user.Role),
        "status": user.Status,
    }


def serialize_enterprise(enterprise: PlatformEnterprise, permissions: frozenset[str]) -> dict[str, Any]:
    return {
        "id": str(enterprise.Id),
        "name": enterprise.Name,
        "customerCode": enterprise.CustomerCode,
        "permissions": [
            item for item in ("提单查询", "船期查询", "节点追踪")
            if "shipment.read" in permissions
        ],
    }

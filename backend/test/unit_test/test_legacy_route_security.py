from types import SimpleNamespace

import pytest
from sanic.exceptions import SanicException

from model.account import AccountRole
from router.legacy_security import (
    LEGACY_ADMIN_ACTIONS,
    LEGACY_ADMIN_READ_ACTIONS,
    LEGACY_READ_ACTIONS,
    application_for_conversation,
    legacy_account_is_admin,
    require_allowed_action,
    require_configured_application,
    sanitize_legacy_payload,
    validate_workspace_file_payload,
)


def assert_status(error: SanicException, status: int):
    assert error.status_code == status


def test_legacy_action_allowlist_denies_unknown_and_normal_writes():
    assert "DescribeConversationMessageList" in LEGACY_READ_ACTIONS
    assert "DescribeConversationList" in LEGACY_ADMIN_READ_ACTIONS
    assert "CreateTimerTask" in LEGACY_ADMIN_ACTIONS

    require_allowed_action("DescribeConversationMessageList", is_admin=False)
    require_allowed_action("DescribeConversationList", is_admin=True)
    require_allowed_action("CreateTimerTask", is_admin=True)

    with pytest.raises(SanicException) as normal_management_read_error:
        require_allowed_action("DescribeChannelList", is_admin=False)
    assert_status(normal_management_read_error.value, 403)

    with pytest.raises(SanicException) as normal_error:
        require_allowed_action("CreateTimerTask", is_admin=False)
    assert_status(normal_error.value, 403)

    with pytest.raises(SanicException) as unknown_error:
        require_allowed_action("DeleteEverything", is_admin=True)
    assert_status(unknown_error.value, 403)


def test_configured_application_is_the_only_vendor_boundary():
    app = SimpleNamespace(apps={"configured": object()})

    assert require_configured_application(app, "configured") is app.apps["configured"]

    with pytest.raises(SanicException) as missing_error:
        require_configured_application(app, "unknown")
    assert_status(missing_error.value, 404)

    with pytest.raises(SanicException) as empty_error:
        require_configured_application(app, "")
    assert_status(empty_error.value, 400)


def test_legacy_payload_cannot_override_identity_scope():
    sanitized = sanitize_legacy_payload(
        {
            "AccountId": "attacker",
            "VisitorId": "attacker",
            "CustomerId": "attacker",
            "OpenId": "attacker",
            "UserId": "attacker",
            "ChannelId": "channel-1",
        },
        "account-1",
        "DescribeConversationList",
    )

    assert sanitized == {"ChannelId": "channel-1", "UserId": "account-1"}


@pytest.mark.asyncio
async def test_account_role_is_loaded_from_database(monkeypatch):
    request = SimpleNamespace(ctx=SimpleNamespace(db=object(), account_id="account-1"))
    account = SimpleNamespace(Role=AccountRole.NORMAL)

    async def fake_get(db, account_id):
        assert account_id == "account-1"
        return account

    monkeypatch.setattr("router.legacy_security.CoreAccount.get", fake_get)
    assert await legacy_account_is_admin(request) is False

    account.Role = AccountRole.ADMIN
    assert await legacy_account_is_admin(request) is True


@pytest.mark.asyncio
async def test_streaming_request_without_scoped_db_uses_connection_helper(monkeypatch):
    request = SimpleNamespace(ctx=SimpleNamespace(account_id="account-1"))
    account = SimpleNamespace(Role=AccountRole.NORMAL)

    class FakeDbContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def fake_get(db, account_id):
        assert account_id == "account-1"
        return account

    monkeypatch.setattr("router.legacy_security.db_connection", lambda: FakeDbContext())
    monkeypatch.setattr("router.legacy_security.CoreAccount.get", fake_get)
    assert await legacy_account_is_admin(request) is False


@pytest.mark.asyncio
async def test_conversation_application_is_owned_and_client_id_must_match(monkeypatch):
    request = SimpleNamespace(ctx=SimpleNamespace(db=object(), account_id="account-1"))

    async def fake_get_application_id(db, account_id, conversation_id):
        assert account_id == "account-1"
        assert conversation_id == "conversation-1"
        return "configured"

    monkeypatch.setattr(
        "router.legacy_security.CoreConversation.get_application_id",
        fake_get_application_id,
    )
    assert await application_for_conversation(request, "conversation-1", "configured") == "configured"

    with pytest.raises(SanicException) as mismatch_error:
        await application_for_conversation(request, "conversation-1", "other")
    assert_status(mismatch_error.value, 403)


def test_workspace_file_payload_is_bound_to_configured_vendor_app():
    vendor = SimpleNamespace(config={"AppId": "vendor-app"})
    payload = validate_workspace_file_payload(
        {
            "app_id": "vendor-app",
            "workspace_id": "workspace-1",
            "path": "/workdir/report.txt",
        },
        vendor,
        "configured",
    )
    assert payload["path"] == "/workdir/report.txt"

    with pytest.raises(SanicException) as app_mismatch:
        validate_workspace_file_payload(
            {"app_id": "attacker-app", "workspace_id": "workspace-1", "path": "/workdir/a"},
            vendor,
            "configured",
        )
    assert_status(app_mismatch.value, 403)

    with pytest.raises(SanicException) as traversal:
        validate_workspace_file_payload(
            {"app_id": "vendor-app", "workspace_id": "workspace-1", "path": "/workdir/../secret"},
            vendor,
            "configured",
        )
    assert_status(traversal.value, 400)

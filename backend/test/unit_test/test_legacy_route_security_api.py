"""ASGI regression coverage for the legacy compatibility security boundary."""

import json

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.chat import CoreChat
from core.conversation import CoreConversation
from core.session import SessionToken


def auth_headers(auth_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth_token}"}


def configured_application_id(app) -> str:
    application_id = next(iter(app.apps), None)
    if application_id is None:
        pytest.fail("legacy route security tests require one configured application")
    return application_id


@pytest.mark.asyncio
async def test_normal_account_cannot_call_legacy_management_or_unknown_action(app, auth_token):
    application_id = configured_application_id(app)
    headers = auth_headers(auth_token)

    _, management_response = await app.asgi_client.post(
        "/adp/CreateTimerTask",
        headers=headers,
        data=json.dumps({"ApplicationId": application_id, "Payload": {}}),
    )
    assert management_response.status == 403

    _, unknown_response = await app.asgi_client.post(
        "/adp/DeleteEverything",
        headers=headers,
        data=json.dumps({"ApplicationId": application_id, "Payload": {}}),
    )
    assert unknown_response.status == 403

    for action in (
        "DescribeConversationList",
        "DescribeChannelList",
        "DescribeTimerTaskSummaryList",
        "DescribeAppTriggerSummaryList",
    ):
        _, response = await app.asgi_client.post(
            f"/adp/{action}",
            headers=headers,
            data=json.dumps({"ApplicationId": application_id, "Payload": {}}),
        )
        assert response.status == 403, action


async def create_owned_conversation(app, token: str, application_id: str) -> str:
    """Insert a conversation owned by `token`'s account.

    Uses a throwaway engine instead of `app.config["sessionmaker"]`.  The app's
    pool is first used inside session-scoped async fixtures, i.e. in the session
    event loop; checking one of those connections back out from a test body
    running in its own loop raises "attached to a different loop".  A loop-local
    engine sidesteps that harness defect (ROADMAP M2-TEST-FIX-01) without
    changing what the test asserts.
    """
    account_id = SessionToken.check(token)["AccountId"]
    url = app.config["sessionmaker"].kw["bind"].url
    engine = create_async_engine(url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            conversation = await CoreConversation.create(
                db,
                account_id,
                application_id,
                title="legacy security test",
            )
            return str(conversation.Id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_every_adp_facing_route_requires_admin(app, auth_token):
    """直通 ADP 的路由一律要求管理员（`adp_admin_required`）。

    这些路由会用平台自己的腾讯云凭据打到 ADP CAPI。此前它们只要求
    `login_required`，于是任何持 `login_token` 的普通账号都能触达
    `LEGACY_READ_ACTIONS`（Agent 详情 / 插件 / 技能 / 知识库 / 文件读），
    并且 `AUTO_CREATE_ACCOUNT` 打开时访客自动注册即可拿到该 token。

    本用例逐条锁住「普通账号一律 401/403」，是这条边界唯一的回归网。
    """
    application_id = configured_application_id(app)
    headers = auth_headers(auth_token)
    probes = [
        ("post", "/adp/DescribeConversation", {"ApplicationId": application_id, "Payload": {}}),
        ("post", "/chat/message", {"ApplicationId": application_id, "Contents": [{"Type": "text", "Text": "hi"}]}),
        ("post", "/chat/conversation/delete", {"ConversationId": "00000000-0000-0000-0000-000000000099"}),
        ("post", "/file/parse", {"ApplicationId": application_id, "FileName": "a.txt", "FileType": "txt"}),
        ("post", "/reference/detail", {"ApplicationId": application_id, "ReferenceIds": ["ref-1"]}),
        ("post", "/feedback/rate", {"ApplicationId": application_id, "RecordId": "r-1", "Score": 1}),
        ("post", "/share/create", {"ApplicationId": application_id, "ConversationId": "c-1", "RecordIds": []}),
    ]
    for method, path, payload in probes:
        _, response = await getattr(app.asgi_client, method)(
            path, headers=headers, data=json.dumps(payload)
        )
        assert response.status in {401, 403}, f"{path} 未拒绝普通账号: {response.status}"

    for path in (
        "/chat/messages?ConversationId=00000000-0000-0000-0000-000000000099",
        "/chat/conversations",
        "/file/download?ApplicationId=%s&WorkspaceId=workspace-1&Path=/workdir/a.txt" % application_id,
    ):
        _, response = await app.asgi_client.get(path, headers=headers)
        assert response.status in {401, 403}, f"{path} 未拒绝普通账号: {response.status}"


@pytest.mark.asyncio
async def test_normal_account_payload_identity_is_replaced_by_server_scope(app, admin_auth_token, monkeypatch):
    application_id = configured_application_id(app)
    conversation_id = await create_owned_conversation(app, admin_auth_token, application_id)
    vendor_app = app.apps[application_id]
    account_id = SessionToken.check(admin_auth_token)["AccountId"]
    seen = {}

    async def fake_describe_conversation_message_list(
        ConversationId,
        UserId=None,
        **kwargs,
    ):
        seen.update({
            "ConversationId": ConversationId,
            "UserId": UserId,
            **kwargs,
        })
        return {"Records": []}

    monkeypatch.setattr(
        vendor_app,
        "describe_conversation_message_list",
        fake_describe_conversation_message_list,
    )
    _, response = await app.asgi_client.post(
        "/adp/DescribeConversationMessageList",
        headers=auth_headers(admin_auth_token),
        data=json.dumps(
            {
                "ApplicationId": application_id,
                "Payload": {
                    "ConversationId": conversation_id,
                    "UserId": "attacker-user",
                    "AccountId": "attacker-account",
                },
            }
        ),
    )

    assert response.status == 200
    assert seen == {
        "ConversationId": conversation_id,
        "UserId": account_id,
    }


@pytest.mark.asyncio
async def test_legacy_admin_can_call_explicit_management_action(app, admin_auth_token, monkeypatch):
    application_id = configured_application_id(app)
    vendor_app = app.apps[application_id]
    seen = {}

    async def fake_forward_request(action, payload, service=None, **kwargs):
        seen.update({"action": action, "payload": payload})
        return {"RequestId": "test-request"}

    monkeypatch.setattr(vendor_app, "forward_request", fake_forward_request)
    _, response = await app.asgi_client.post(
        "/adp/CreateTimerTask",
        headers=auth_headers(admin_auth_token),
        data=json.dumps(
            {
                "ApplicationId": application_id,
                "Payload": {"UserId": "attacker-user", "Name": "test"},
            }
        ),
    )

    assert response.status == 200
    assert seen == {"action": "CreateTimerTask", "payload": {"Name": "test"}}


@pytest.mark.asyncio
async def test_admin_channel_fallback_requires_explicit_channel_marker(app, admin_auth_token):
    application_id = configured_application_id(app)
    payload = {
        "ApplicationId": application_id,
        "ConversationId": "00000000-0000-0000-0000-000000000099",
        "FileName": "probe.txt",
        "FileType": "txt",
    }

    _, response = await app.asgi_client.post(
        "/file/parse",
        headers=auth_headers(admin_auth_token),
        data=json.dumps(payload),
    )
    assert response.status == 404


@pytest.mark.asyncio
async def test_legacy_routes_reject_forged_application_and_conversation(app, admin_auth_token):
    headers = auth_headers(admin_auth_token)

    _, application_response = await app.asgi_client.post(
        "/adp/DescribeConversationList",
        headers=headers,
        data=json.dumps({"ApplicationId": "not-configured", "Payload": {}}),
    )
    assert application_response.status == 403

    application_id = configured_application_id(app)
    _, allowed_application_response = await app.asgi_client.post(
        "/adp/DescribeConversationMessageList",
        headers=headers,
        data=json.dumps({
            "ApplicationId": application_id,
            "Payload": {"ConversationId": "00000000-0000-0000-0000-000000000098"},
        }),
    )
    assert allowed_application_response.status == 404

    _, conversation_response = await app.asgi_client.post(
        "/chat/message",
        headers=headers,
        data=json.dumps(
            {
                "ApplicationId": application_id,
                "ConversationId": "00000000-0000-0000-0000-000000000099",
                "Contents": [{"Type": "text", "Text": "probe"}],
            }
        ),
    )
    assert conversation_response.status == 404


@pytest.mark.asyncio
async def test_normal_account_cannot_claim_channel_or_custom_identity(app, auth_token):
    """普通账号连门都进不来：直通 ADP 的路由现在一律要求管理员。

    这里断言的仍是「普通账号不能冒充渠道身份 / 他人身份」，但拒绝点已从
    payload 清洗前移到 `adp_admin_required`。管理员确实允许走渠道兜底，
    因此本用例必须保持普通账号，否则会变成在测管理员的合法路径。
    """
    application_id = configured_application_id(app)
    headers = auth_headers(auth_token)
    base_payload = {
        "ApplicationId": application_id,
        "ConversationId": "00000000-0000-0000-0000-000000000099",
        "Contents": [{"Type": "text", "Text": "probe"}],
    }

    _, channel_response = await app.asgi_client.post(
        "/chat/message",
        headers=headers,
        data=json.dumps({**base_payload, "IsChannel": True}),
    )
    assert channel_response.status == 403

    _, identity_response = await app.asgi_client.post(
        "/chat/message",
        headers=headers,
        data=json.dumps({**base_payload, "CustomVariables": {"OpenId": "other-user"}}),
    )
    assert identity_response.status == 403


@pytest.mark.asyncio
async def test_file_parse_cannot_use_other_account_conversation(app, admin_auth_token):
    application_id = configured_application_id(app)
    headers = auth_headers(admin_auth_token)
    _, response = await app.asgi_client.post(
        "/file/parse",
        headers=headers,
        data=json.dumps(
            {
                "ApplicationId": application_id,
                "FileName": "probe.txt",
                "FileType": "txt",
                "ConversationId": "00000000-0000-0000-0000-000000000099",
            }
        ),
    )
    assert response.status == 404


@pytest.mark.asyncio
async def test_admin_chat_channel_fallback_requires_marker_and_uses_configured_app(
    app,
    admin_auth_token,
    monkeypatch,
):
    application_id = configured_application_id(app)
    conversation_id = "00000000-0000-0000-0000-000000000099"
    seen = {}

    async def fake_message(
        vendor_app,
        account_id,
        contents,
        conversation_id,
        search_network,
        custom_variables,
        *,
        is_channel,
    ):
        seen.update({
            "application_id": vendor_app.application_id,
            "account_id": account_id,
            "conversation_id": conversation_id,
            "is_channel": is_channel,
        })
        yield b"data: {}\n\n"

    monkeypatch.setattr(CoreChat, "message", staticmethod(fake_message))
    payload = {
        "ApplicationId": application_id,
        "ConversationId": conversation_id,
        "Contents": [{"Type": "text", "Text": "probe"}],
        "IsChannel": True,
    }

    _, response = await app.asgi_client.post(
        "/chat/message",
        headers=auth_headers(admin_auth_token),
        data=json.dumps(payload),
    )

    assert response.status == 200
    assert seen["application_id"] == application_id
    assert seen["conversation_id"] == conversation_id
    assert seen["is_channel"] is True


@pytest.mark.asyncio
async def test_admin_file_parse_channel_fallback_uses_configured_app(
    app,
    admin_auth_token,
    monkeypatch,
):
    application_id = configured_application_id(app)
    conversation_id = "00000000-0000-0000-0000-000000000099"
    seen = {}
    vendor_app = app.apps[application_id]

    async def fake_parse_document(**kwargs):
        seen.update(kwargs)
        yield b"data: ok\n\n"

    monkeypatch.setattr(vendor_app, "parse_document", fake_parse_document)
    _, response = await app.asgi_client.post(
        "/file/parse",
        headers=auth_headers(admin_auth_token),
        data=json.dumps({
            "ApplicationId": application_id,
            "ConversationId": conversation_id,
            "FileName": "probe.txt",
            "FileType": "txt",
            "IsChannel": True,
        }),
    )

    assert response.status == 200
    assert seen["account_id"] == SessionToken.check(admin_auth_token)["AccountId"]
    assert seen["conversation_id"] == conversation_id


@pytest.mark.asyncio
async def test_admin_share_and_feedback_channel_fallbacks_use_configured_app(
    app,
    admin_auth_token,
    monkeypatch,
):
    application_id = configured_application_id(app)
    conversation_id = "00000000-0000-0000-0000-000000000099"
    vendor_app = app.apps[application_id]
    seen = {}

    async def fake_get_messages_v2(db, account_id, requested_conversation_id, limit, last_record_id=None):
        seen["share_lookup"] = {
            "account_id": account_id,
            "conversation_id": requested_conversation_id,
            "limit": limit,
        }
        return {"Records": [], "HasMoreBefore": False, "LastRecordId": ""}

    async def fake_rate(db, account_id, requested_conversation_id, record_id, score, comment=None):
        seen["rate"] = {
            "account_id": account_id,
            "conversation_id": requested_conversation_id,
            "record_id": record_id,
            "score": score,
        }

    monkeypatch.setattr(vendor_app, "get_messages_v2", fake_get_messages_v2)
    monkeypatch.setattr(vendor_app, "rate", fake_rate)

    _, share_response = await app.asgi_client.post(
        "/share/create",
        headers=auth_headers(admin_auth_token),
        data=json.dumps({
            "ApplicationId": application_id,
            "ConversationId": conversation_id,
            "RecordIds": [],
            "IsChannel": True,
        }),
    )
    assert share_response.status == 200
    assert json.loads(share_response.body.decode())["ShareId"]

    _, feedback_response = await app.asgi_client.post(
        "/feedback/rate",
        headers=auth_headers(admin_auth_token),
        data=json.dumps({
            "ApplicationId": application_id,
            "ConversationId": conversation_id,
            "RecordId": "record-1",
            "Score": 1,
            "IsChannel": True,
        }),
    )
    assert feedback_response.status == 200
    assert seen["share_lookup"]["conversation_id"] == conversation_id
    assert seen["rate"] == {
        "account_id": SessionToken.check(admin_auth_token)["AccountId"],
        "conversation_id": conversation_id,
        "record_id": "record-1",
        "score": 1,
    }


@pytest.mark.asyncio
async def test_admin_generic_forward_channel_fallback_requires_marker(
    app,
    admin_auth_token,
    monkeypatch,
):
    application_id = configured_application_id(app)
    vendor_app = app.apps[application_id]
    conversation_id = "00000000-0000-0000-0000-000000000099"
    seen = {}

    async def fake_forward_request(action, payload, service=None, **kwargs):
        seen.update({"action": action, "payload": payload})
        return {"Records": []}

    monkeypatch.setattr(vendor_app, "forward_request", fake_forward_request)
    base_payload = {
        "ApplicationId": application_id,
        "Payload": {"ConversationId": conversation_id},
    }

    _, denied_response = await app.asgi_client.post(
        "/adp/DescribeConversation",
        headers=auth_headers(admin_auth_token),
        data=json.dumps(base_payload),
    )
    assert denied_response.status == 404

    _, allowed_response = await app.asgi_client.post(
        "/adp/DescribeConversation",
        headers=auth_headers(admin_auth_token),
        data=json.dumps({**base_payload, "IsChannel": True}),
    )
    assert allowed_response.status == 200
    assert seen == {
        "action": "DescribeConversation",
        "payload": {"ConversationId": conversation_id},
    }


@pytest.mark.asyncio
async def test_normal_account_file_actions_bind_app_and_reject_path_traversal(
    app,
    admin_auth_token,
    monkeypatch,
):
    application_id = configured_application_id(app)
    vendor_app = app.apps[application_id]
    seen = {}

    async def fake_fetch_file(app_id, workspace_id, path):
        seen.update({"app_id": app_id, "workspace_id": workspace_id, "path": path})
        return {"status_code": 200, "content_type": "text/plain", "content": "ok"}

    monkeypatch.setattr(vendor_app, "fetch_file", fake_fetch_file)
    base_payload = {
        "app_id": application_id,
        "workspace_id": "workspace-1",
        "path": "/workdir/report.txt",
    }

    _, valid_response = await app.asgi_client.post(
        "/adp/FetchFile",
        headers=auth_headers(admin_auth_token),
        data=json.dumps({"ApplicationId": application_id, "Payload": base_payload}),
    )
    assert valid_response.status == 200
    assert seen == base_payload

    _, forged_app_response = await app.asgi_client.post(
        "/adp/FetchFile",
        headers=auth_headers(admin_auth_token),
        data=json.dumps({
            "ApplicationId": application_id,
            "Payload": {**base_payload, "app_id": "attacker-app"},
        }),
    )
    assert forged_app_response.status == 403

    _, traversal_response = await app.asgi_client.post(
        "/adp/ListDir",
        headers=auth_headers(admin_auth_token),
        data=json.dumps({
            "ApplicationId": application_id,
            "Payload": {**base_payload, "path": "/workdir/../secret"},
        }),
    )
    assert traversal_response.status == 400


@pytest.mark.asyncio
async def test_file_download_rejects_forged_app_id_and_keeps_valid_proxy_path(
    app,
    admin_auth_token,
    monkeypatch,
):
    application_id = configured_application_id(app)
    vendor_app = app.apps[application_id]
    seen = {}

    async def fake_download_file_content(app_id, workspace_id, path):
        seen.update({"app_id": app_id, "workspace_id": workspace_id, "path": path})
        return b"file-body", "text/plain", "report.txt"

    monkeypatch.setattr(vendor_app, "download_file_content", fake_download_file_content)
    headers = auth_headers(admin_auth_token)

    _, forged_response = await app.asgi_client.get(
        "/file/download?ApplicationId=%s&AppId=attacker-app&WorkspaceId=workspace-1&Path=/workdir/report.txt"
        % application_id,
        headers=headers,
    )
    assert forged_response.status == 403

    _, valid_response = await app.asgi_client.get(
        "/file/download?ApplicationId=%s&AppId=%s&WorkspaceId=workspace-1&Path=/workdir/report.txt"
        % (application_id, application_id),
        headers=headers,
    )
    assert valid_response.status == 200
    assert valid_response.body == b"file-body"
    assert seen == {
        "app_id": application_id,
        "workspace_id": "workspace-1",
        "path": "/workdir/report.txt",
    }

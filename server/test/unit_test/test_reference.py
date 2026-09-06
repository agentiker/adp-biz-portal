import json
import pytest
from vendor.tcadp.tcadp import TCADP
from core.share import CoreShareConversation
from core.session import SessionToken


@pytest.mark.asyncio
async def test_reference_detail_api(app, auth_token, monkeypatch):
    headers = {
        "Authorization": f"Bearer {auth_token}",
    }
    application_id = next(iter(app.apps.keys()))
    vendor_app = app.apps[application_id]

    async def fake_get_reference_details(account_id, reference_ids):
        assert account_id is not None
        assert reference_ids == ["ref-1"]
        return [{"Id": "ref-1", "PageContent": "slice text"}]

    monkeypatch.setattr(vendor_app, "get_reference_details", fake_get_reference_details)

    request, response = await app.asgi_client.post(
        "/reference/detail",
        headers=headers,
        data=json.dumps({
            "ApplicationId": application_id,
            "ReferenceIds": ["ref-1"],
        }),
    )

    assert request.method.lower() == "post"
    assert response.status == 200
    resp_dict = json.loads(response.body.decode())
    assert resp_dict == {
        "References": [{"Id": "ref-1", "PageContent": "slice text"}]
    }


@pytest.mark.asyncio
async def test_reference_detail_public_share_uses_stored_application_and_rejects_unknown_share(
    app,
    auth_token,
    monkeypatch,
):
    application_id = next(iter(app.apps.keys()))
    vendor_app = app.apps[application_id]
    async with app.config["sessionmaker"]() as db:
        shared = await CoreShareConversation.create(
            db,
            SessionToken.check(auth_token)["AccountId"],
            "00000000-0000-0000-0000-000000000010",
            application_id,
            [],
        )
        share_id = str(shared.Id)

    seen = {}

    async def fake_get_reference_details(account_id, reference_ids):
        seen.update({"account_id": account_id, "reference_ids": reference_ids})
        return [{"Id": reference_ids[0]}]

    monkeypatch.setattr(vendor_app, "get_reference_details", fake_get_reference_details)

    _, public_response = await app.asgi_client.post(
        "/reference/detail",
        data=json.dumps({
            "ShareId": share_id,
            "ApplicationId": "attacker-application",
            "ReferenceIds": ["ref-public"],
        }),
    )
    assert public_response.status == 200
    assert json.loads(public_response.body.decode()) == {"References": [{"Id": "ref-public"}]}
    assert seen == {"account_id": None, "reference_ids": ["ref-public"]}

    _, missing_response = await app.asgi_client.post(
        "/reference/detail",
        data=json.dumps({"ShareId": "00000000-0000-0000-0000-000000000011", "ReferenceIds": ["ref"]}),
    )
    assert missing_response.status == 404


@pytest.mark.asyncio
async def test_tcadp_reference_detail_keeps_pascal_case_fields(monkeypatch):
    vendor_app = TCADP(
        config={
            "BotBizId": "bot-1",
        },
        application_id="app-1",
    )

    async def fake_tc_request(config, action, payload):
        assert config == vendor_app.tc_config()
        assert action == "DescribeRefer"
        assert payload == {
            "BotBizId": "bot-1",
            "ReferBizIds": ["2031578623621401536"],
        }
        return {
            "Response": {
                "RequestId": "7c81325a-006b-48bf-8c9e-65297d1f5362",
                "List": [
                    {
                        "OrgData": "文档名：2412.19437v2\n文档片段：# DeepSeek-V3",
                        "PageInfos": [1, 2, 3, 4],
                        "DocName": "2412.19437v2.pdf",
                        "PageContent": "文档名：2412.19437v2\n文档片段：# DeepSeek-V3",
                        "ReferBizId": "2031578623621401536",
                        "SheetInfos": [],
                        "DocType": 2,
                        "KnowledgeBizId": "1946134275584460864",
                        "DocBizId": "1946134403756953088",
                    }
                ],
            }
        }

    monkeypatch.setattr("vendor.tcadp.tcadp.tc_request", fake_tc_request)

    references = await vendor_app.get_reference_details(
        account_id=None,
        reference_ids=["2031578623621401536"],
    )

    assert references == [
        {
            "OrgData": "文档名：2412.19437v2\n文档片段：# DeepSeek-V3",
            "PageInfos": [1, 2, 3, 4],
            "DocName": "2412.19437v2.pdf",
            "PageContent": "文档名：2412.19437v2\n文档片段：# DeepSeek-V3",
            "ReferBizId": "2031578623621401536",
            "SheetInfos": [],
            "DocType": 2,
            "KnowledgeBizId": "1946134275584460864",
            "DocBizId": "1946134403756953088",
            "Id": "2031578623621401536",
            "Name": "2412.19437v2.pdf",
        }
    ]

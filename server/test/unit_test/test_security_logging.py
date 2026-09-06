from __future__ import annotations

import logging

import pytest

from util.security_logging import redact_error, redact_mapping, redact_payload
from util.tca import tc_request
from vendor.tcadp import tcadp as tcadp_module
from vendor.tcadp.tcadp import TCADP


def test_redact_mapping_covers_nested_credentials_and_keeps_safe_fields():
    payload = {
        "AppKey": "app-key-value",
        "Nested": {
            "AccessToken": "access-token-value",
            "Credentials": {
                "TmpSecretId": "tmp-id-value",
                "TmpSecretKey": "tmp-key-value",
                "Token": "tmp-token-value",
            },
            "OrderId": "order-123",
        },
    }

    redacted = redact_mapping(payload)

    assert "app-key-value" not in repr(redacted)
    assert "access-token-value" not in repr(redacted)
    assert "tmp-id-value" not in repr(redacted)
    assert "tmp-key-value" not in repr(redacted)
    assert "tmp-token-value" not in repr(redacted)
    assert redacted["Nested"]["OrderId"] == "order-123"


def test_redact_error_covers_inline_headers_and_signed_urls():
    error = (
        'Authorization: Bearer bearer-value password=plain-password '
        'body={"Token":"json-token"} '
        'url=https://example.test/file?Signature=signed-value'
    )

    redacted = redact_error(error)

    assert "bearer-value" not in redacted
    assert "plain-password" not in redacted
    assert "json-token" not in redacted
    assert "signed-value" not in redacted
    assert "[REDACTED]" in redacted


class _FakeResponse:
    status = 200
    content_type = "application/json"

    async def json(self):
        return {"Response": {"RequestId": "request-1"}}

    async def text(self):
        return ""


class _FakeRequestContext:
    async def __aenter__(self):
        return _FakeResponse()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeClientSession:
    def __init__(self, *args, **kwargs):
        del args, kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def post(self, *args, **kwargs):
        del args, kwargs
        return _FakeRequestContext()


@pytest.mark.asyncio
async def test_tc_request_log_redacts_json_payload(monkeypatch, caplog):
    monkeypatch.setattr("util.tca.aiohttp.ClientSession", _FakeClientSession)
    config = {
        "secret_id": "secret-id-value",
        "secret_key": "secret-key-value",
        "lke": {"url": "https://example.test"},
    }

    with caplog.at_level(logging.INFO):
        await tc_request(
            config,
            "DescribeApp",
            {
                "AppKey": "app-key-value",
                "Credentials": {"AccessToken": "access-token-value"},
                "OrderId": "order-123",
            },
        )

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "app-key-value" not in messages
    assert "access-token-value" not in messages
    assert "secret-key-value" not in messages
    assert "order-123" in messages


@pytest.mark.asyncio
async def test_forward_request_log_redacts_payload_and_upstream_error(monkeypatch, caplog):
    vendor = TCADP(
        {
            "AppKey": "app-key-value",
            "ServiceVendor": "ChinaTencentCloud",
        },
        "application-1",
    )
    monkeypatch.setattr(
        vendor,
        "tc_config",
        lambda: {"secret_id": "secret-id-value", "secret_key": "secret-key-value", "lke": {"url": "https://example.test"}},
    )

    async def fake_tc_request(*args, **kwargs):
        del args, kwargs
        return {
            "Response": {
                "Error": {
                    "Code": "Unauthorized",
                    "Message": "token=upstream-token-value",
                }
            }
        }

    monkeypatch.setattr(tcadp_module, "tc_request", fake_tc_request)

    with caplog.at_level(logging.INFO):
        response = await vendor.forward_request(
            "DescribeApp",
            {
                "AppKey": "app-key-value",
                "Nested": {"Authorization": "Bearer bearer-value"},
                "OrderId": "order-123",
            },
            raise_on_error=False,
        )

    assert response["Error"]["Code"] == "Unauthorized"
    messages = "\n".join(record.getMessage() for record in caplog.records)
    for secret in (
        "app-key-value",
        "bearer-value",
        "upstream-token-value",
        "secret-key-value",
    ):
        assert secret not in messages
    assert "order-123" in messages


def test_redact_payload_parses_json_strings():
    redacted = redact_payload('{"Password":"password-value","Status":"ok"}')

    assert "password-value" not in redacted
    assert '"Status": "ok"' in redacted

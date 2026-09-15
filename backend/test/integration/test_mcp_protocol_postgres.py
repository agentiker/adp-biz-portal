"""MCP wire protocol and database key revocation over real HTTP handlers."""
import uuid
import pytest
from sanic import Sanic
from cryptography.fernet import Fernet
from test.integration.test_platform_worker_postgres import platform_sessionmaker


@pytest.mark.asyncio
async def test_mcp_protocol(platform_sessionmaker, monkeypatch):
    from test.app_bootstrap import ensure_app
    ensure_app()
    from config import tagentic_config
    from core.adp_api_key import create_api_key, delete_api_key
    from router.mcp import McpApi
    monkeypatch.setattr(tagentic_config, 'PLATFORM_CHANNEL_CREDENTIAL_KEY', Fernet.generate_key().decode())
    async with platform_sessionmaker() as db:
        row, key = await create_api_key(db, 'MCP test')
        key_id = str(row.Id)
        await db.commit()
    app = Sanic('mcp_protocol_' + uuid.uuid4().hex)
    app.add_route(McpApi.as_view(), '/mcp')

    @app.middleware('request')
    async def session(request):
        request.ctx.db = platform_sessionmaker()

    @app.middleware('response')
    async def close(request, response):
        await request.ctx.db.rollback()
        await request.ctx.db.close()

    headers = {'Authorization': 'Bearer ' + key, 'Accept': 'application/json, text/event-stream'}

    async def call(body, extra=None):
        return (await app.asgi_client.post('/mcp', headers={**headers, **(extra or {})}, json=body))[1]

    init = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '1'}}}
    response = await call(init)
    assert response.json['result']['protocolVersion'] == '2025-06-18'
    assert response.headers['Cache-Control'] == 'no-store'
    assert (await call({'jsonrpc': '2.0', 'method': 'notifications/initialized'})).status == 202
    listed = await call({'jsonrpc': '2.0', 'id': 'list', 'method': 'tools/list'})
    assert {t['name'] for t in listed.json['result']['tools']} == {'shipment_lookup', 'shipment_schedule', 'shipment_milestones'}
    assert all(set(t['inputSchema']['properties']) == {'query'} for t in listed.json['result']['tools'])
    assert (await call({'jsonrpc': '2.0', 'id': 2, 'method': 'ping'})).json['result'] == {}
    assert (await call({'jsonrpc': '2.0', 'id': 2, 'method': 'unknown'})).json['error']['code'] == -32601
    assert (await call(init, {'Origin': 'https://evil.example'})).status == 403
    assert (await call(init, {'MCP-Protocol-Version': 'invalid'})).status == 400
    assert (await call(init, {'Accept': 'application/json'})).status == 406
    assert (await call([init])).status == 400
    assert (await call({'jsonrpc': '2.0', 'id': False, 'method': 'ping'})).status == 400
    assert (await app.asgi_client.get('/mcp'))[1].status == 405
    _, malformed = await app.asgi_client.post('/mcp', headers={**headers, 'Content-Type': 'application/json'}, content='{')
    assert malformed.json['error']['code'] == -32700
    async with platform_sessionmaker() as db:
        await delete_api_key(db, key_id)
        await db.commit()
    assert (await call(init)).status == 401

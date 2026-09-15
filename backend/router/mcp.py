"""Stateless Streamable HTTP MCP; business identity never comes from tool arguments."""
import json as stdjson
from urllib.parse import urlsplit

from sanic.response import json, empty
from sanic.views import HTTPMethodView
from app_factory import TAgenticApp
from core.adp_api_key import require_connector_key
from core.error import BaseError
from router.platform import AdpShipmentLookupApi, AdpShipmentScheduleApi, AdpShipmentMilestonesApi

VERSIONS = ('2025-11-25', '2025-06-18', '2025-03-26')
TOOLS = {
    'shipment_lookup': (AdpShipmentLookupApi, '查询订单、提单或箱号的物流信息'),
    'shipment_schedule': (AdpShipmentScheduleApi, '查询船名、航次和预计抵港时间'),
    'shipment_milestones': (AdpShipmentMilestonesApi, '查询物流节点和实际抵港时间'),
}


def reply(payload, status=200):
    return json(payload, status=status, headers={'Cache-Control': 'no-store'})


def error(request_id, code, message, status=200):
    return reply({'jsonrpc': '2.0', 'id': request_id, 'error': {'code': code, 'message': message}}, status)


class McpApi(HTTPMethodView):
    async def get(self, request):
        # This server does not offer unsolicited server-to-client SSE messages.
        return empty(status=405, headers={'Allow': 'POST', 'Cache-Control': 'no-store'})

    async def post(self, request):
        origin = request.headers.get('Origin')
        if origin:
            expected = urlsplit(request.url)
            parsed = urlsplit(origin)
            if parsed.scheme not in ('http', 'https') or (parsed.scheme, parsed.netloc) != (expected.scheme, expected.netloc) or parsed.path or parsed.query or parsed.fragment:
                return error(None, -32000, 'Origin rejected', 403)
        auth = request.headers.get('Authorization', '')
        key = auth[7:] if auth.startswith('Bearer ') else request.headers.get('X-ADP-Service-Token')
        try:
            await require_connector_key(request.ctx.db, key)
        except BaseError:
            return error(None, -32000, 'API Key invalid', 401)
        if request.content_type != 'application/json':
            return error(None, -32600, 'Content-Type must be application/json', 415)
        accept = request.headers.get('Accept', '')
        if 'application/json' not in accept or 'text/event-stream' not in accept:
            return error(None, -32600, 'Accept must include application/json and text/event-stream', 406)
        version = request.headers.get('MCP-Protocol-Version')
        if version and version not in VERSIONS:
            return error(None, -32600, 'Unsupported MCP protocol version', 400)
        try:
            body = stdjson.loads(request.body)
        except (ValueError, UnicodeDecodeError):
            return error(None, -32700, 'Parse error', 400)
        if not isinstance(body, dict):
            return error(None, -32600, 'Expected one JSON-RPC message', 400)
        request_id = body.get('id')
        if body.get('jsonrpc') != '2.0' or not isinstance(body.get('method'), str) or ('id' in body and (isinstance(request_id, bool) or not isinstance(request_id, (int, str)))):
            return error(None, -32600, 'Invalid request', 400)
        method, params = body['method'], body.get('params', {})
        if not isinstance(params, dict):
            return error(request_id, -32602, 'Invalid params', 400)
        if 'id' not in body:
            return empty(status=202, headers={'Cache-Control': 'no-store'})
        if method == 'initialize':
            if not isinstance(params.get('protocolVersion'), str) or not isinstance(params.get('capabilities'), dict) or not isinstance(params.get('clientInfo'), dict):
                return error(request_id, -32602, 'Invalid initialization params')
            result = {'protocolVersion': params['protocolVersion'] if params['protocolVersion'] in VERSIONS else VERSIONS[0],
                      'capabilities': {'tools': {'listChanged': False}},
                      'serverInfo': {'name': 'adp-biz-portal', 'version': '1.0.0'},
                      'instructions': '工具调用必须通过可信客户端 Header 传递平台执行上下文，不接受模型指定企业。'}
        elif method == 'ping':
            result = {}
        elif method == 'tools/list':
            result = {'tools': [{'name': name, 'description': description,
                'inputSchema': {'type': 'object', 'properties': {'query': {'type': 'string', 'minLength': 1, 'maxLength': 128}}, 'required': ['query'], 'additionalProperties': False},
                'annotations': {'readOnlyHint': True, 'destructiveHint': False}}
                for name, (_, description) in TOOLS.items()]}
        elif method == 'tools/call':
            name, arguments = params.get('name'), params.get('arguments', {})
            if not isinstance(name, str) or name not in TOOLS:
                return error(request_id, -32602, 'Unknown tool')
            if not isinstance(arguments, dict) or set(arguments) != {'query'} or not isinstance(arguments.get('query'), str) or not 1 <= len(arguments['query'].strip()) <= 128:
                return error(request_id, -32602, 'Only query (1–128 characters) is accepted')
            try:
                response = await TOOLS[name][0]().execute(request, arguments)
                payload = stdjson.loads(response.body)
                result = {'content': [{'type': 'text', 'text': stdjson.dumps(payload, ensure_ascii=False)}],
                          'structuredContent': payload, 'isError': payload.get('status') == 'upstream_error'}
            except BaseError:
                await request.ctx.db.rollback()
                result = {'content': [{'type': 'text', 'text': '工具调用被拒绝，请检查执行上下文、请求 ID 和当前权限。'}], 'isError': True}
        else:
            return error(request_id, -32601, 'Method not found')
        return reply({'jsonrpc': '2.0', 'id': request_id, 'result': result})


TAgenticApp.get_app().add_route(McpApi.as_view(), '/mcp')

import asyncio
import logging

import sanic
from sanic.views import HTTPMethodView
from sanic_restful_api import reqparse
from sanic.request.types import Request
from sanic.response import ResponseStream
from sanic.exceptions import SanicException

from router.legacy_security import adp_admin_required
from core.chat import CoreChat
from core.conversation import CoreConversation
from core.share import CoreShareConversation
from app_factory import TAgenticApp
from router.legacy_security import (
    application_for_conversation,
    legacy_account_is_admin,
    require_configured_application,
)
from core.legacy_binding import list_legacy_bindings, resolve_legacy_binding
app: TAgenticApp = TAgenticApp.get_app()


class ChatMessageApi(HTTPMethodView):
    @adp_admin_required
    async def post(self, request: Request):
        parser = reqparse.RequestParser()
        parser.add_argument("Contents", type=list, required=True, location="json")
        parser.add_argument("ConversationId", type=str, location="json")
        parser.add_argument("ApplicationId", type=str, location="json")
        parser.add_argument("SearchNetwork", type=bool, default=True, location="json")
        parser.add_argument("CustomVariables", type=dict, default={}, location="json")
        # 渠道会话（企微 / 微信 Bot 等）：vendor 侧才是权威数据源，
        # 本地不落地 chat_conversation，避免污染 /chat/conversations 侧栏列表。
        parser.add_argument("IsChannel", type=bool, default=False, location="json")
        args = parser.parse_args(request)
        conversation_id = args['ConversationId']
        supplied_application_id = args['ApplicationId']
        custom_variables = args['CustomVariables'] or {}
        is_channel = bool(args['IsChannel'])
        is_admin = await legacy_account_is_admin(request)
        logging.info(
            "ChatMessageApi: conversation_present=%s application_id=%s content_count=%s "
            "custom_variable_keys=%s is_channel=%s",
            bool(conversation_id),
            supplied_application_id,
            len(args['Contents'] or []),
            sorted(custom_variables.keys()) if is_admin else [],
            is_channel,
        )

        if is_channel and not is_admin:
            raise SanicException("普通账号不能提交渠道会话", status_code=403)
        if custom_variables and not is_admin:
            raise SanicException("普通账号不能提交自定义身份变量", status_code=403)
        if conversation_id:
            try:
                application_id = await application_for_conversation(
                    request, conversation_id, supplied_application_id
                )
            except SanicException as error:
                # Admins retain the old channel/debug path, but even this
                # compatibility fallback may select only a configured app.
                # Do not turn an application mismatch into a fallback: an
                # existing local conversation must keep its stored app.
                if (
                    error.status_code != 404
                    or not is_channel
                    or not is_admin
                    or not supplied_application_id
                ):
                    raise
                application_id = supplied_application_id
                require_configured_application(app, application_id)
        else:
            if is_channel:
                raise SanicException("渠道会话必须提供 ConversationId", status_code=400)
            application_id = supplied_application_id
            require_configured_application(app, application_id)

        binding = await resolve_legacy_binding(
            request,
            app,
            application_id=application_id,
        )
        vendor_app = binding.vendor_app or require_configured_application(app, application_id)

        logging.info(
            "[ChatMessageApi] application_id=%s custom_variable_count=%s "
            "is_channel=%s vendor_type=%s",
            application_id,
            len(custom_variables),
            is_channel,
            type(vendor_app).__name__,
        )

        async def streaming_fn(response):
            chat_gen = CoreChat.message(
                vendor_app,
                request.ctx.account_id,
                args['Contents'],
                args['ConversationId'],
                args['SearchNetwork'],
                custom_variables,
                is_channel=is_channel,
            )
            try:
                async for data in chat_gen:
                    await response.write(data)
            except asyncio.CancelledError:
                logging.info("[ChatMessageApi] Client disconnected, closing upstream")
                await chat_gen.aclose()
                raise
        return ResponseStream(streaming_fn, content_type='text/event-stream; charset=utf-8')


class ChatMessageListApi(HTTPMethodView):
    @adp_admin_required
    async def get(self, request: Request):
        parser = reqparse.RequestParser()
        parser.add_argument("ConversationId", type=str, required=False, location="args")
        parser.add_argument("LastRecordId", type=str, required=False, location="args")
        parser.add_argument("ShareId", type=str, required=False, location="args")
        args = parser.parse_args(request)

        if args["ConversationId"] is not None:
            application_id = await CoreConversation.get_application_id(
                request.ctx.db,
                request.ctx.account_id,
                args['ConversationId']
            )
            binding = await resolve_legacy_binding(request, app, application_id=application_id)
            vendor_app = binding.vendor_app or require_configured_application(app, application_id)

            # 判断是否为 claw 模式：优先从 apps_info 缓存查找，找不到时动态获取
            is_claw = False
            for info in getattr(request.ctx, 'apps_info', []):
                if hasattr(info, 'ApplicationId'):
                    app_id = info.ApplicationId
                else:
                    app_id = info.get('ApplicationId', '')
                pattern = info.Pattern if hasattr(info, 'Pattern') else info.get('Pattern', '')
                if app_id == application_id and pattern == 'ClawAgent':
                    is_claw = True
                    break

            # 缓存中未找到该应用信息时，通过 vendor_app 动态获取 Pattern
            if not is_claw:
                def _get_app_id(info):
                    if hasattr(info, 'ApplicationId'):
                        return info.ApplicationId
                    return info.get('ApplicationId', '')

                found_in_cache = any(
                    _get_app_id(info) == application_id
                    for info in getattr(request.ctx, 'apps_info', [])
                )
                if not found_in_cache and hasattr(vendor_app, 'get_info'):
                    try:
                        app_info = await vendor_app.get_info()
                        if getattr(app_info, 'Pattern', None) == 'ClawAgent':
                            is_claw = True
                    except (OSError, ValueError, KeyError, AttributeError) as e:
                        logging.warning(
                            '[ChatApi] get_info failed for %s: %s',
                            application_id,
                            e,
                        )

            if is_claw and hasattr(vendor_app, 'get_messages_v2'):
                # claw 模式：通过 DescribeConversationMessageList 获取完整 V2 数据
                result = await vendor_app.get_messages_v2(
                    request.ctx.db,
                    request.ctx.account_id,
                    args['ConversationId'],
                    app.config.CHAT_MESSAGE_PAGE_SIZE,
                    args['LastRecordId']
                )
                resp = {
                    'Response': {
                        'ApplicationId': application_id,
                        'Records': result['Records'],
                        'HasMoreBefore': result['HasMoreBefore'],
                        'LastRecordId': result['LastRecordId'],
                    }
                }
            else:
                # standard 模式：通过 GetMsgRecord 获取历史消息
                records = await vendor_app.get_messages(
                    request.ctx.db,
                    request.ctx.account_id,
                    args['ConversationId'],
                    app.config.CHAT_MESSAGE_PAGE_SIZE,
                    args['LastRecordId']
                )
                resp = {
                    'Response': {
                        'ApplicationId': application_id,
                        'Records': records,
                    }
                }
            return sanic.json(resp)

        if args["ShareId"] is not None:
            if args['LastRecordId'] is not None:
                # temporarily disable pagination loading for the share API
                result = []
            else:
                conversation = await CoreShareConversation.list(request.ctx.db, args["ShareId"])
                result = conversation.to_dict()
            return sanic.json({"Response": result})

        raise SanicException('ConversationId or ShareId is required')


class ChatConversationListApi(HTTPMethodView):
    @adp_admin_required
    async def get(self, request: Request):
        parser = reqparse.RequestParser()
        parser.add_argument("ApplicationId", type=str, required=False, location="args")
        args = parser.parse_args(request)

        if args["ApplicationId"]:
            await resolve_legacy_binding(request, app, application_id=args["ApplicationId"])
        else:
            allowed_application_ids = {
                binding.application_id
                for binding in await list_legacy_bindings(request, app)
            }
            conversations = await CoreConversation.list(
                request.ctx.db,
                request.ctx.account_id,
                application_id=None,
            )
            conversations = [
                item for item in conversations if item.ApplicationId in allowed_application_ids
            ]
            return sanic.json([conversation.to_dict() for conversation in conversations])

        conversations = await CoreConversation.list(
            request.ctx.db,
            request.ctx.account_id,
            application_id=args["ApplicationId"],
        )
        return sanic.json([conversation.to_dict() for conversation in conversations])


class ChatConversationDeleteApi(HTTPMethodView):
    @adp_admin_required
    async def post(self, request: Request):
        parser = reqparse.RequestParser()
        parser.add_argument("ConversationId", type=str, required=True, location="json")
        args = parser.parse_args(request)

        await CoreConversation.delete(request.ctx.db, request.ctx.account_id, args["ConversationId"])
        return sanic.json({"Success": 1})


app.add_route(ChatMessageApi.as_view(), "/chat/message")
app.add_route(ChatMessageListApi.as_view(), "/chat/messages")
app.add_route(ChatConversationListApi.as_view(), "/chat/conversations")
app.add_route(ChatConversationDeleteApi.as_view(), "/chat/conversation/delete")

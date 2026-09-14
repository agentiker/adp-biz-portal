from sanic import json
from sanic.views import HTTPMethodView
from sanic_restful_api import reqparse
from sanic.request.types import Request
from sanic.exceptions import SanicException
from router.legacy_security import adp_admin_required
from core.share import CoreShareConversation
from app_factory import TAgenticApp
from router.legacy_security import (
    application_for_conversation,
    legacy_account_is_admin,
    require_configured_application,
)
app: TAgenticApp = TAgenticApp.get_app()


class ShareCreateApi(HTTPMethodView):
    @adp_admin_required
    async def post(self, request: Request):
        parser = reqparse.RequestParser()
        parser.add_argument("ConversationId", type=str, required=True, location="json")
        parser.add_argument("ApplicationId", type=str, required=False, location="json")
        parser.add_argument("RecordIds", type=list[str], required=True, location="json")
        parser.add_argument("IsChannel", type=bool, default=False, location="json")
        args = parser.parse_args(request)

        is_admin = await legacy_account_is_admin(request)
        try:
            application_id = await application_for_conversation(
                request,
                args['ConversationId'],
                args.get('ApplicationId'),
            )
        except SanicException as error:
            if (
                error.status_code != 404
                or not is_admin
                or not args.get('IsChannel')
                or not args.get('ApplicationId')
            ):
                raise
            application_id = args['ApplicationId']
        vendor_app = require_configured_application(app, application_id)

        # 优先用 V2 接口（DescribeConversationMessageList）拉取完整数据，与对话页一致——
        # V2 协议才含 questionnaire（反问澄清）/ tool_call 等内容；v1 GetMsgRecord 不含。
        # 不支持 V2 的 vendor 回退到 v1 get_messages。
        use_v2 = hasattr(vendor_app, 'get_messages_v2')

        # 按 RecordId 聚合 + MessageId 去重合并：
        # DescribeConversationMessageList 的 Limit 是 message 数，分页边界可能把同一
        # RecordId 的 messages 拆到两页 → 每页各自分组产生重复 record。
        # 对话页前端 mergeRecord-v2.upsertMessage 按 MessageId 合并去重，分享后端须对齐。
        merged_by_id: dict = {}
        order: list = []
        last_record_id = None
        while True:
            if use_v2:
                result = await vendor_app.get_messages_v2(
                    request.ctx.db, request.ctx.account_id, args['ConversationId'], 10, last_record_id=last_record_id
                )
                _records = result.get('Records', [])
                next_cursor = result.get('LastRecordId')
            else:
                _records = await vendor_app.get_messages(
                    request.ctx.db, request.ctx.account_id, args['ConversationId'], 10, last_record_id=last_record_id
                )
                next_cursor = None
                if _records:
                    item = _records[0]
                    next_cursor = item.RecordId if hasattr(item, 'RecordId') else item.get("RecordId")

            for rec in _records:
                rec_dict = rec.model_dump() if hasattr(rec, 'model_dump') else rec
                rid = rec_dict.get('RecordId') if isinstance(rec_dict, dict) else getattr(rec_dict, 'RecordId', None)
                if not rid:
                    continue
                if rid not in merged_by_id:
                    merged_by_id[rid] = {
                        **rec_dict,
                        'Messages': list(rec_dict.get('Messages', [])),
                    }
                    merged_by_id[rid]['_seen_msg_ids'] = {
                        m.get('MessageId') for m in rec_dict.get('Messages', []) if m.get('MessageId')
                    }
                    order.append(rid)
                else:
                    target = merged_by_id[rid]
                    seen = target['_seen_msg_ids']
                    for m in rec_dict.get('Messages', []):
                        mid = m.get('MessageId')
                        if mid and mid in seen:
                            continue
                        target['Messages'].append(m)
                        if mid:
                            seen.add(mid)
                    # 顶层状态字段取较新值
                    for k in ('Status', 'StatusDesc', 'Score', 'ExtraInfo'):
                        if rec_dict.get(k) is not None:
                            target[k] = rec_dict[k]

            if not _records or not next_cursor or next_cursor == last_record_id:
                break
            last_record_id = next_cursor

        # 按 RecordIds 筛选并清理临时字段
        records = []
        for rid in order:
            rec = merged_by_id[rid]
            rec.pop('_seen_msg_ids', None)
            if rid in args["RecordIds"]:
                records.append(rec)

        shared = await CoreShareConversation.create(
            request.ctx.db, request.ctx.account_id, args["ConversationId"], application_id, records
        )

        return json({"ShareId": shared.Id})


app.add_route(ShareCreateApi.as_view(), "/share/create")

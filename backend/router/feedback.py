from sanic import json
from sanic.views import HTTPMethodView
from sanic_restful_api import reqparse
from sanic.request.types import Request
from sanic.log import logger
from sanic.exceptions import SanicException
from router.legacy_security import adp_admin_required
from app_factory import TAgenticApp
from router.legacy_security import (
    application_for_conversation,
    legacy_account_is_admin,
    require_configured_application,
)
app: TAgenticApp = TAgenticApp.get_app()


class TCADPFeedbackRateApi(HTTPMethodView):
    @adp_admin_required
    async def post(self, request: Request):
        parser = reqparse.RequestParser()
        parser.add_argument("ConversationId", type=str, required=True, location="json")
        parser.add_argument("RecordId", type=str, required=True, location="json")
        parser.add_argument("Score", type=int, required=True, location="json")
        parser.add_argument("ApplicationId", type=str, required=False, location="json", default="")
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
            # Only legacy admins may rate a vendor-owned channel conversation.
            if (
                error.status_code != 404
                or not is_admin
                or not args.get('IsChannel')
                or not args.get('ApplicationId')
            ):
                raise
            application_id = args['ApplicationId']
            logger.info(
                "feedback/rate admin fallback: conv=%s app_id=%s",
                args['ConversationId'], application_id,
            )

        vendor_app = require_configured_application(app, application_id)
        logger.info(f"feedback/rate: conv={args['ConversationId']} record={args['RecordId']} score={args['Score']} app_id={application_id}")

        await vendor_app.rate(
            request.ctx.db,
            request.ctx.account_id,
            args['ConversationId'],
            args['RecordId'],
            args['Score']
        )

        return json({})


app.add_route(TCADPFeedbackRateApi.as_view(), "/feedback/rate")

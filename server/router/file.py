from sanic import json
from sanic.views import stream
from sanic.views import HTTPMethodView
from sanic_restful_api import reqparse
from sanic.request.types import Request
from router.legacy_security import adp_admin_required
from app_factory import TAgenticApp
from router.legacy_security import require_configured_application
app: TAgenticApp = TAgenticApp.get_app()


class FileUploadApi(HTTPMethodView):
    @stream
    @adp_admin_required
    async def post(self, request: Request):
        parser = reqparse.RequestParser()
        parser.add_argument("ApplicationId", type=str, required=True, location="args")
        parser.add_argument("Type", type=str, default='image/jpeg', location="args")
        parser.add_argument("Mode", type=str, default='standard', location="args")
        args = parser.parse_args(request)
        application_id = args['ApplicationId']
        vendor_app = require_configured_application(app, application_id)

        result = await vendor_app.upload(
            request.ctx.db,
            request,
            request.ctx.account_id,
            args['Type'],
            mode=args['Mode']
        )
        # 兼容返回字典或字符串两种格式
        if isinstance(result, dict):
            return json(result)
        return json({"Url": result})


app.add_route(FileUploadApi.as_view(), "/file/upload")

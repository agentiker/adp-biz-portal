from sanic import json
from sanic.views import HTTPMethodView
from sanic.request.types import Request
from router import login_required
from app_factory import TAgenticApp
from core.legacy_binding import list_legacy_bindings
app = TAgenticApp.get_app()


class ApplicationListApi(HTTPMethodView):
    @login_required
    async def get(self, request: Request):
        bindings = await list_legacy_bindings(request, app)
        info_by_id = {
            getattr(item, "ApplicationId", None): item
            for item in getattr(request.ctx, "apps_info", [])
        }
        apps_info = []
        seen: set[str] = set()
        for binding in bindings:
            if binding.application_id in seen:
                continue
            seen.add(binding.application_id)
            info = info_by_id.get(binding.application_id)
            if info is None:
                info = {"ApplicationId": binding.application_id}
            elif hasattr(info, "__dict__"):
                info = dict(info.__dict__)
                info.pop("_sa_instance_state", None)
            else:
                info = dict(info)
            info["ApplicationId"] = binding.application_id
            apps_info.append(info)
        return json({"Applications": apps_info})


app.add_route(ApplicationListApi.as_view(), "/application/list")

import time
import logging
import asyncio
import re
from datetime import datetime, timezone
from uuid import uuid4

from core.platform import create_audit
from app_factory import TAgenticApp
app = TAgenticApp.get_app()


class CoreApplication:
    _instance = None

    # 单例模式
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    apps_info = []
    apps_info_ts = time.time()
    metadata_status = {}

    @staticmethod
    def _safe_error_message(error: Exception) -> str:
        """Keep provider diagnostics useful without persisting credentials."""
        message = str(error).strip()[:240]
        return re.sub(
            r"(?i)(appkey|secretid|secretkey|token|authorization)\s*[=:]\s*[^,;\s}]+",
            r"\1=REDACTED",
            message,
        )

    async def _record_metadata_failure(self, application_id: str, vendor_app, error: Exception) -> None:
        error_type = type(error).__name__
        error_message = self._safe_error_message(error)
        metadata = {
            "applicationId": application_id,
            "vendor": str((getattr(vendor_app, "config", {}) or {}).get("Vendor", "unknown")),
            "errorType": error_type,
            "errorMessage": error_message,
            "fallback": "last_known_metadata_or_application_id",
            "chatStatus": "unchanged",
        }
        logging.warning(
            "[update_application_info] metadata degraded application=%s errorType=%s error=%s",
            application_id,
            error_type,
            error_message,
        )

        sessionmaker = app.config.get("sessionmaker")
        if sessionmaker is None:
            logging.warning(
                "[update_application_info] audit skipped because database session is unavailable application=%s",
                application_id,
            )
            return
        try:
            async with sessionmaker() as db:
                await create_audit(
                    db,
                    actor_account_id=None,
                    action="adp.metadata.refresh",
                    target_type="legacy_application",
                    target_id=application_id,
                    trace_id=f"adp-metadata-{uuid4().hex}",
                    outcome="degraded",
                    metadata=metadata,
                )
                await db.commit()
        except Exception:
            # Metadata health must never take down the request path or startup.
            logging.exception(
                "[update_application_info] failed to persist metadata degradation application=%s",
                application_id,
            )

    async def hook_application_info(self, request):
        ts = time.time()
        if ts - self.apps_info_ts > 60:
            self.apps_info_ts = ts
            # 异步更新，不阻塞流程
            task = asyncio.create_task(self.update_application_info())
            logging.info(f'[update_application_info] {task}')

        request.ctx.apps_info = self.apps_info

    async def update_application_info(self):
        logging.info('[update_application_info] begin')

        apps = app.apps
        _apps_info = []
        for application_id, vendor_app in apps.items():
            try:
                info = await vendor_app.get_info()
            except Exception as error:
                previous = next(
                    (
                        item for item in self.apps_info
                        if getattr(item, "ApplicationId", None) == application_id
                    ),
                    None,
                )
                if previous is not None:
                    _apps_info.append(previous)
                self.metadata_status[application_id] = {
                    "status": "degraded",
                    "lastFailureAt": datetime.now(timezone.utc).isoformat(),
                    "errorType": type(error).__name__,
                    "errorMessage": self._safe_error_message(error),
                    "chatStatus": "unchanged",
                }
                await self._record_metadata_failure(application_id, vendor_app, error)
                continue

            info.ApplicationId = application_id
            _apps_info.append(info)
            self.metadata_status[application_id] = {
                "status": "healthy",
                "lastSuccessAt": datetime.now(timezone.utc).isoformat(),
                "chatStatus": "unchanged",
            }

        if _apps_info:
            self.apps_info = _apps_info
        logging.info('[update_application_info] done')


@app.listener('before_server_start')
async def init_application_info(app, loop):
    core_app = CoreApplication()
    await core_app.update_application_info()


@app.middleware("request")
async def application_info(request):
    if request.server_path in {"/healthz", "/readyz"}:
        request.ctx.apps_info = CoreApplication().apps_info
        return
    await CoreApplication().hook_application_info(request)

"""Build channel reply senders for a worker process from stored credentials.

Credential plaintext is decrypted here rather than in the API process: the
browser-facing routes only ever need masked metadata, so keeping decryption on
the worker path makes the sensitive boundary explicit.

Senders are resolved lazily per channel instance and cached for the life of the
worker, so a reply does not pay a database read and a token fetch per message.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from core.channel_credentials import (
    ChannelCredentialError,
    load_active_channel_instance_credential,
)
from integrations.channels.wechat_official_account import (
    WECHAT_OFFICIAL_ACCOUNT,
    WechatOfficialAccountSender,
)
from integrations.channels.wechat_transport import (
    WechatAccessTokenCache,
    WechatCustomerServiceTransport,
    WechatSendError,
)


logger = logging.getLogger(__name__)

CREDENTIAL_APP_ID_KEYS = ("appId", "app_id")
CREDENTIAL_APP_SECRET_KEYS = ("appSecret", "app_secret")


def _credential_fields(credential: Any) -> dict[str, str]:
    """Normalize legacy token-only and structured credentials the same way."""
    value = credential.strip() if isinstance(credential, str) else credential
    if isinstance(value, str) and value.startswith("{"):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item.strip() for key, item in value.items() if isinstance(item, str) and item.strip()}


def _first(fields: Mapping[str, str], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = fields.get(key)
        if value:
            return value
    return None


class ChannelSenderResolver:
    """Resolve one sender per ``channel`` / ``channel:instance`` on demand.

    ``process_platform_reply_task`` recognizes this resolver through
    ``is_channel_sender_resolver`` and awaits :meth:`resolve`. The marker is an
    explicit contract rather than duck typing, so a mock or an unrelated object
    that happens to expose ``resolve`` is never mistaken for a resolver.
    """

    is_channel_sender_resolver = True

    def __init__(
        self,
        sessionmaker: Callable[[], AsyncSession],
        *,
        token_cache: WechatAccessTokenCache | None = None,
    ):
        self._sessionmaker = sessionmaker
        self._senders: dict[str, Any] = {}
        self._token_cache = token_cache if token_cache is not None else WechatAccessTokenCache()

    async def resolve(self, *, channel: str, channel_instance_id: str | None) -> Any:
        if channel != WECHAT_OFFICIAL_ACCOUNT or not channel_instance_id:
            return None
        cache_key = f"{channel}:{channel_instance_id}"
        if cache_key in self._senders:
            return self._senders[cache_key]
        sender = await self._build_wechat_sender(channel_instance_id)
        self._senders[cache_key] = sender
        return sender

    async def _build_wechat_sender(self, channel_instance_id: str) -> Any:
        db = self._sessionmaker()
        try:
            credential = await load_active_channel_instance_credential(
                db,
                channel=WECHAT_OFFICIAL_ACCOUNT,
                channel_instance_id=channel_instance_id,
            )
        except ChannelCredentialError:
            # No usable credential: return a sender without a transport so the
            # reply is marked uncertain instead of silently dropped.
            logger.warning(
                "wechat official account credential unavailable for instance %s", channel_instance_id
            )
            return WechatOfficialAccountSender(channel_instance_id=channel_instance_id)
        finally:
            await db.close()

        fields = _credential_fields(credential)
        app_id = _first(fields, CREDENTIAL_APP_ID_KEYS)
        app_secret = _first(fields, CREDENTIAL_APP_SECRET_KEYS)
        if not app_id or not app_secret:
            # Callback-only credentials are valid; they just cannot send.
            logger.info(
                "wechat official account instance %s has no app secret; replies stay uncertain",
                channel_instance_id,
            )
            return WechatOfficialAccountSender(channel_instance_id=channel_instance_id)
        try:
            transport = WechatCustomerServiceTransport(
                app_id=app_id,
                app_secret=app_secret,
                token_cache=self._token_cache,
            )
        except WechatSendError:
            return WechatOfficialAccountSender(channel_instance_id=channel_instance_id)
        return WechatOfficialAccountSender(channel_instance_id=channel_instance_id, transport=transport)

"""WeChat 客服 (WeCom Customer Service) HTTP client: token, sync_msg, send.

Uses the classic ``gettoken`` (corpid + corpsecret) — not the official-account
``stable_token`` — and the ``kf/*`` endpoints. sync_msg returns the raw page so
the pull loop (core.channel_pull) can advance the cursor; send returns a
DeliveryReceipt classified with the same rules as the official-account sender.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Mapping

import aiohttp

from core.delivery import DeliveryRetryableError
from integrations.channels.base import DeliveryReceipt
from integrations.channels.wechat_transport import (
    JSON_UTF8_HEADERS,
    MAX_TEXT_BYTES,
    TEXT_TRUNCATION_NOTICE,
    WechatSendError,
    WechatCustomerServiceTransport,
    _card_text,
    _card_url,
    _truncate_utf8,
    _utf8_json,
)


logger = logging.getLogger(__name__)

QYAPI_BASE = "https://qyapi.weixin.qq.com"
GETTOKEN_PATH = "/cgi-bin/gettoken"
KF_SYNC_MSG_PATH = "/cgi-bin/kf/sync_msg"
KF_SEND_MSG_PATH = "/cgi-bin/kf/send_msg"
DEFAULT_TIMEOUT_SECONDS = 10
TOKEN_EXPIRY_MARGIN_SECONDS = 300
KF_TOKEN_ERROR_CODES = {40001, 40014, 42001}
KF_SYNC_LIMIT = 1000


class WechatCorpTokenCache:
    """Cache one classic ``gettoken`` access token per corp (process-local)."""

    def __init__(self, *, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS, api_base: str = QYAPI_BASE):
        self._timeout_seconds = timeout_seconds
        self._api_base = api_base.rstrip("/")
        self._tokens: dict[str, tuple[str, float]] = {}

    def invalidate(self, corp_id: str) -> None:
        self._tokens.pop(corp_id, None)

    async def token(self, *, corp_id: str, corp_secret: str) -> str:
        cached = self._tokens.get(corp_id)
        if cached is not None and cached[1] > time.time():
            return cached[0]
        value, expires_in = await self._fetch(corp_id=corp_id, corp_secret=corp_secret)
        self._tokens[corp_id] = (value, time.time() + max(60, expires_in - TOKEN_EXPIRY_MARGIN_SECONDS))
        return value

    async def _fetch(self, *, corp_id: str, corp_secret: str) -> tuple[str, int]:
        if not corp_id or not corp_secret:
            raise WechatSendError("corp credentials are incomplete")
        url = f"{self._api_base}{GETTOKEN_PATH}?corpid={corp_id}&corpsecret={corp_secret}"
        timeout = aiohttp.ClientTimeout(total=self._timeout_seconds)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    body = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            raise DeliveryRetryableError("wecom_gettoken_unreachable") from exc
        if not isinstance(body, Mapping) or int(body.get("errcode", -1)) != 0:
            logger.error("wecom gettoken rejected: errcode=%s", (body or {}).get("errcode"))
            raise DeliveryRetryableError("wecom_gettoken_rejected")
        token = str(body.get("access_token") or "")
        if not token:
            raise DeliveryRetryableError("wecom_gettoken_empty")
        return token, int(body.get("expires_in") or 7200)


class WechatKfTransport:
    """Client for one 客服 service account (kf) instance."""

    def __init__(
        self,
        *,
        corp_id: str,
        corp_secret: str,
        open_kfid: str,
        tokens: WechatCorpTokenCache | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        api_base: str = QYAPI_BASE,
    ):
        if not corp_id or not corp_secret:
            raise WechatSendError("corp credentials are incomplete")
        self.corp_id = corp_id
        self._corp_secret = corp_secret
        self.open_kfid = open_kfid
        self._tokens = tokens or WechatCorpTokenCache(timeout_seconds=timeout_seconds, api_base=api_base)
        self._timeout_seconds = timeout_seconds
        self._api_base = api_base.rstrip("/")

    async def sync_msg(self, *, cursor: str, open_kfid: str, callback_token: str | None) -> Mapping[str, Any]:
        """Pull one page. Returns the raw {errcode, next_cursor, has_more, msg_list}."""
        body: dict[str, Any] = {"open_kfid": open_kfid, "limit": KF_SYNC_LIMIT}
        if cursor:
            body["cursor"] = cursor
        elif callback_token:
            # The callback token bootstraps the very first pull only (no cursor).
            body["token"] = callback_token
        return await self._post_json(path=KF_SYNC_MSG_PATH, payload=body)

    async def send_text(self, *, open_kfid: str, external_userid: str, content: str) -> DeliveryReceipt:
        text = (content or "").strip()
        if not text:
            raise WechatSendError("message content is empty")
        if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
            budget = MAX_TEXT_BYTES - len(TEXT_TRUNCATION_NOTICE.encode("utf-8"))
            text = _truncate_utf8(text, budget) + TEXT_TRUNCATION_NOTICE
        payload = {"touser": external_userid, "open_kfid": open_kfid, "msgtype": "text", "text": {"content": text}}
        return await self._send(payload)

    async def send_link(
        self, *, open_kfid: str, external_userid: str, title: str, desc: str, url: str
    ) -> DeliveryReceipt:
        """Send a link card (kf has no ``news`` type; ``link`` is its rich card)."""
        link = {
            "title": _card_text(title, limit=128, field="card title"),
            "desc": _card_text(desc, limit=512, field="card desc"),
            "url": _card_url(url),
        }
        payload = {"touser": external_userid, "open_kfid": open_kfid, "msgtype": "link", "link": link}
        return await self._send(payload)

    async def _send(self, payload: Mapping[str, Any]) -> DeliveryReceipt:
        receipt, _ = self._classify_and_receipt(await self._post_json(path=KF_SEND_MSG_PATH, payload=payload))
        return receipt

    @staticmethod
    def _classify_and_receipt(body: Mapping[str, Any]) -> tuple[DeliveryReceipt, bool]:
        # Reuse the official-account errcode classification (token/retryable/
        # permanent/unmapped), which the KF endpoints share.
        return WechatCustomerServiceTransport._classify(body)

    async def _post_json(self, *, path: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """POST with the access token, refreshing once on an invalid-token errcode."""
        for attempt in (1, 2):
            token = await self._tokens.token(corp_id=self.corp_id, corp_secret=self._corp_secret)
            url = f"{self._api_base}{path}?access_token={token}"
            timeout = aiohttp.ClientTimeout(total=self._timeout_seconds)
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(url, data=_utf8_json(payload), headers=JSON_UTF8_HEADERS) as response:
                        status = response.status
                        body = await response.json(content_type=None)
            except (aiohttp.ClientConnectorError, aiohttp.ClientProxyConnectionError) as exc:
                raise DeliveryRetryableError("wecom_kf_unreachable") from exc
            if status >= 500:
                raise DeliveryRetryableError("wecom_kf_upstream_error")
            if not isinstance(body, Mapping):
                raise DeliveryRetryableError("wecom_kf_result_unknown")
            if int(body.get("errcode", 0)) in KF_TOKEN_ERROR_CODES and attempt == 1:
                self._tokens.invalidate(self.corp_id)
                continue
            return body
        raise DeliveryRetryableError("wecom_kf_token_stale")

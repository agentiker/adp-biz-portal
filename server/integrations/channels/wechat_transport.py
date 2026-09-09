"""Outbound transport for WeChat Official Account customer-service messages.

Sending is separated from the callback adapter because the two directions have
different failure semantics. A callback is verified and acknowledged
synchronously, while a send can fail *after* the request left this process — and
that difference decides whether a retry is safe.

The three outcomes this module distinguishes:

- retryable: nothing was sent (connection refused, DNS failure, token refresh
  failed). Retrying cannot duplicate a message.
- uncertain: the request was written but no verdict came back (read timeout,
  truncated response). The platform must not retry automatically and must not
  claim success, because the user may already have the message.
- rejected: WeChat answered with a permanent error (window closed, account not
  authorized for this API). Retrying would fail the same way.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Mapping

import aiohttp

from core.delivery import DeliveryRetryableError
from integrations.channels.base import DeliveryReceipt


logger = logging.getLogger(__name__)

WECHAT_API_BASE = "https://api.weixin.qq.com"
# The stable-token endpoint returns the same token to every caller instead of
# invalidating the previous one, so several workers can send concurrently
# without knocking each other's token out.
STABLE_TOKEN_PATH = "/cgi-bin/stable_token"
CUSTOM_SEND_PATH = "/cgi-bin/message/custom/send"
DEFAULT_TIMEOUT_SECONDS = 10
# Refresh early so a token cannot expire between the check and the send.
TOKEN_EXPIRY_MARGIN_SECONDS = 300
# WeChat customer-service text is limited by BYTES (~2048), not characters, so
# a Chinese answer must be truncated by encoded length or the provider rejects
# the whole message with errcode 45002.
MAX_TEXT_BYTES = 2000
TEXT_TRUNCATION_NOTICE = "…（完整内容见下方卡片）"
JSON_UTF8_HEADERS = {"Content-Type": "application/json; charset=utf-8"}


def _truncate_utf8(text: str, max_bytes: int) -> str:
    """Truncate to at most ``max_bytes`` UTF-8 bytes on a character boundary."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    # ``errors='ignore'`` drops a trailing byte sequence split mid-character.
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _utf8_json(payload: Mapping[str, Any]) -> bytes:
    """Serialize a request body as raw UTF-8 rather than escaped ASCII.

    ``json.dumps`` defaults to ``ensure_ascii=True``, and aiohttp's ``json=``
    argument uses that default. WeChat does not decode ``\\uXXXX`` escapes in
    message content: it forwards them to the reader literally, so a Chinese
    reply arrives as ``\\u4f60\\u597d``. Sending raw UTF-8 bytes is the only
    form the provider renders correctly.
    """
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


# WeChat error codes that will fail the same way on every retry.
PERMANENT_ERROR_CODES = frozenset({
    40003,  # invalid openid
    45015,  # response outside the customer-service message window
    45047,  # per-session send limit reached
    45072,  # unsupported command
    48001,  # api unauthorized: the account cannot use customer-service messages
    48002,  # user has not subscribed / blocked messages
    50001,  # api unauthorized for this account
    50002,  # user is restricted
})
# Codes that mean "try again later" rather than "this will never work".
RETRYABLE_ERROR_CODES = frozenset({
    -1,     # system busy
    45009,  # api call frequency limit
    45011,  # api rate limit
    48004,  # api interface is temporarily banned
})
# An expired or invalid token is recoverable exactly once per send.
TOKEN_ERROR_CODES = frozenset({40001, 40014, 42001, 42007})


class WechatSendError(RuntimeError):
    """Base error for the customer-service send transport."""


@dataclass(frozen=True)
class _CachedToken:
    value: str
    expires_at: float


def _card_text(value: Any, *, limit: int, field: str) -> str:
    """Bound a card field, keeping it single-line for the provider's layout."""
    if not isinstance(value, str) or not value.strip():
        raise WechatSendError(f"{field} is empty")
    normalized = " ".join(value.split())
    return normalized[:limit]


def _card_url(value: Any) -> str:
    """Require an absolute HTTPS/HTTP link the provider will accept."""
    if not isinstance(value, str) or not value.strip():
        raise WechatSendError("card url is empty")
    normalized = value.strip()
    if not normalized.startswith(("https://", "http://")) or len(normalized) > 1024:
        raise WechatSendError("card url is invalid")
    return normalized


class WechatAccessTokenCache:
    """Cache one stable access token per app.

    The cache is process-local, which is only safe because this module uses the
    stable-token endpoint: a concurrent refresh in another worker returns the
    same token instead of revoking this one. ``M3-REFACTOR-01`` records a
    preference for shared storage plus a lock — that requirement comes from the
    classic ``/cgi-bin/token`` endpoint, which *does* invalidate the previous
    token and would make several workers knock each other out. If this module is
    ever pointed back at ``/cgi-bin/token``, the cache must move to shared
    storage first.
    """

    def __init__(self, *, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS):
        self._tokens: dict[str, _CachedToken] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._timeout_seconds = timeout_seconds

    def _lock_for(self, key: str) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    def invalidate(self, app_id: str) -> None:
        self._tokens.pop(app_id, None)

    async def token(self, *, app_id: str, app_secret: str, now: float | None = None) -> str:
        current = time.time() if now is None else now
        cached = self._tokens.get(app_id)
        if cached is not None and cached.expires_at > current:
            return cached.value
        async with self._lock_for(app_id):
            # Another coroutine may have refreshed while this one waited.
            cached = self._tokens.get(app_id)
            if cached is not None and cached.expires_at > current:
                return cached.value
            token, lifetime = await self._fetch(app_id=app_id, app_secret=app_secret)
            expires_at = current + max(60, lifetime - TOKEN_EXPIRY_MARGIN_SECONDS)
            self._tokens[app_id] = _CachedToken(token, expires_at)
            return token

    async def _fetch(self, *, app_id: str, app_secret: str) -> tuple[str, int]:
        timeout = aiohttp.ClientTimeout(total=self._timeout_seconds)
        payload = {
            "grant_type": "client_credential",
            "appid": app_id,
            "secret": app_secret,
            "force_refresh": False,
        }
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(f"{WECHAT_API_BASE}{STABLE_TOKEN_PATH}", json=payload) as response:
                    if response.status >= 400:
                        raise DeliveryRetryableError("wechat_token_http_error")
                    body = await response.json(content_type=None)
        except DeliveryRetryableError:
            raise
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            # No message was sent, so retrying is safe.
            raise DeliveryRetryableError("wechat_token_unavailable") from exc
        if not isinstance(body, Mapping):
            raise DeliveryRetryableError("wechat_token_invalid_response")
        token = body.get("access_token")
        if not isinstance(token, str) or not token:
            # The secret itself may be wrong; the error code stays out of the
            # message so a credential problem is not echoed to a caller.
            logger.error("wechat stable_token rejected: errcode=%s", body.get("errcode"))
            raise DeliveryRetryableError("wechat_token_rejected")
        try:
            lifetime = int(body.get("expires_in", 7200))
        except (TypeError, ValueError):
            lifetime = 7200
        return token, lifetime


class WechatCustomerServiceTransport:
    """Send one text customer-service message through the WeChat API."""

    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        token_cache: WechatAccessTokenCache | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        api_base: str = WECHAT_API_BASE,
    ):
        if not isinstance(app_id, str) or not app_id.strip():
            raise WechatSendError("app_id is required for customer-service messages")
        if not isinstance(app_secret, str) or not app_secret.strip():
            raise WechatSendError("app_secret is required for customer-service messages")
        self.app_id = app_id.strip()
        self._app_secret = app_secret.strip()
        self._tokens = token_cache if token_cache is not None else WechatAccessTokenCache(
            timeout_seconds=timeout_seconds
        )
        self._timeout_seconds = timeout_seconds
        self._api_base = api_base.rstrip("/")

    async def send_text(self, *, open_id: str, content: str) -> DeliveryReceipt:
        """Deliver one text message, retrying only a stale access token."""
        recipient = self._recipient(open_id)
        body = self._text_body(content)
        for attempt in (1, 2):
            token = await self._tokens.token(app_id=self.app_id, app_secret=self._app_secret)
            receipt, token_stale = await self._post(token=token, payload={"touser": recipient, **body})
            if not token_stale:
                return receipt
            # A stale token is the one recoverable case: drop it and send once
            # more. The message was rejected, so this cannot duplicate.
            self._tokens.invalidate(self.app_id)
            if attempt == 2:
                raise DeliveryRetryableError("wechat_token_stale")
        raise DeliveryRetryableError("wechat_send_not_attempted")

    @staticmethod
    def _recipient(open_id: Any) -> str:
        if not isinstance(open_id, str) or not open_id.strip() or len(open_id.strip()) > 128:
            raise WechatSendError("open_id is invalid")
        return open_id.strip()

    @staticmethod
    def _text_body(content: Any) -> dict[str, Any]:
        if not isinstance(content, str) or not content.strip():
            raise WechatSendError("message content is empty")
        text = content.strip()
        if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
            # A long answer is truncated to a preview here and delivered in full
            # by the closing rich card, which links to the portal result page.
            budget = MAX_TEXT_BYTES - len(TEXT_TRUNCATION_NOTICE.encode("utf-8"))
            text = _truncate_utf8(text, budget) + TEXT_TRUNCATION_NOTICE
        return {"msgtype": "text", "text": {"content": text}}

    async def send_news(
        self,
        *,
        open_id: str,
        title: str,
        description: str,
        url: str,
        picture_url: str = "",
    ) -> DeliveryReceipt:
        """Deliver one rich card.

        A text message cannot render structure, so a result worth reading as a
        record (title, summary, a link back to the full evidence) is sent as a
        ``news`` article instead.
        """
        recipient = self._recipient(open_id)
        article = {
            "title": _card_text(title, limit=64, field="card title"),
            "description": _card_text(description, limit=120, field="card description"),
            "url": _card_url(url),
        }
        if picture_url:
            article["picurl"] = _card_url(picture_url)
        payload = {"touser": recipient, "msgtype": "news", "news": {"articles": [article]}}
        for attempt in (1, 2):
            token = await self._tokens.token(app_id=self.app_id, app_secret=self._app_secret)
            receipt, token_stale = await self._post(token=token, payload=payload)
            if not token_stale:
                return receipt
            self._tokens.invalidate(self.app_id)
            if attempt == 2:
                raise DeliveryRetryableError("wechat_token_stale")
        raise DeliveryRetryableError("wechat_send_not_attempted")

    async def _post(self, *, token: str, payload: Mapping[str, Any]) -> tuple[DeliveryReceipt, bool]:
        timeout = aiohttp.ClientTimeout(total=self._timeout_seconds)
        url = f"{self._api_base}{CUSTOM_SEND_PATH}?access_token={token}"
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, data=_utf8_json(payload), headers=JSON_UTF8_HEADERS) as response:
                    status = response.status
                    body = await response.json(content_type=None)
        except (aiohttp.ClientConnectorError, aiohttp.ClientProxyConnectionError) as exc:
            # The connection never succeeded, so nothing reached WeChat.
            raise DeliveryRetryableError("wechat_send_unreachable") from exc
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            # The request may already have been delivered. Never retry and
            # never report success.
            logger.warning("wechat customer-service send outcome unknown: %s", type(exc).__name__)
            return (
                DeliveryReceipt(status="uncertain", uncertain=True, metadata={"reason": "wechat_send_result_unknown"}),
                False,
            )

        if status >= 500:
            raise DeliveryRetryableError("wechat_send_upstream_error")
        if not isinstance(body, Mapping):
            return (
                DeliveryReceipt(status="uncertain", uncertain=True, metadata={"reason": "wechat_send_result_unknown"}),
                False,
            )
        return self._classify(body)

    @staticmethod
    def _classify(body: Mapping[str, Any]) -> tuple[DeliveryReceipt, bool]:
        try:
            code = int(body.get("errcode", 0))
        except (TypeError, ValueError):
            return (
                DeliveryReceipt(status="uncertain", uncertain=True, metadata={"reason": "wechat_send_result_unknown"}),
                False,
            )
        if code == 0:
            return (
                DeliveryReceipt(
                    status="delivered",
                    provider_message_id=str(body.get("msgid")) if body.get("msgid") else None,
                    metadata={"errcode": 0},
                ),
                False,
            )
        if code in TOKEN_ERROR_CODES:
            return (DeliveryReceipt(status="failed", metadata={"reason": "wechat_token_stale"}), True)
        if code in RETRYABLE_ERROR_CODES:
            raise DeliveryRetryableError(f"wechat_send_retryable_{code}")
        if code in PERMANENT_ERROR_CODES:
            return (DeliveryReceipt(status="failed", metadata={"reason": f"wechat_send_rejected_{code}"}), False)
        # An unknown code is treated as permanent so the queue does not spin on
        # an error this build does not understand; the code is kept for triage.
        logger.warning("wechat customer-service send returned unmapped errcode=%s", code)
        return (DeliveryReceipt(status="failed", metadata={"reason": f"wechat_send_error_{code}"}), False)

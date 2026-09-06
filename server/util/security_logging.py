"""Helpers for keeping secrets and signed URLs out of application logs."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any


_SENSITIVE_KEYS = frozenset(
    {
        "accesskey",
        "access_token",
        "accesstoken",
        "appkey",
        "appsecret",
        "authorization",
        "credential",
        "credentials",
        "downloadurl",
        "fileurl",
        "password",
        "passwd",
        "presignedurl",
        "secret",
        "secretid",
        "secretkey",
        "securitytoken",
        "signedurl",
        "token",
        "tmpsecretid",
        "tmpsecretkey",
        "uploadurl",
    }
)
_NORMALIZED_SENSITIVE_KEYS = frozenset(
    re.sub(r"[^a-z0-9]", "", item.lower()) for item in _SENSITIVE_KEYS
)

_INLINE_SECRET_RE = re.compile(
    r"(?P<prefix>(?:[\"']?)(?:access[_-]?token|app[_-]?key|app[_-]?secret|"
    r"authorization|password|passwd|secret(?:[_-]?(?:id|key))?|security[_-]?token|"
    r"tmp[_-]?secret(?:[_-]?(?:id|key))?|token)(?:[\"']?\s*[:=]\s*[\"']?))"
    r"(?P<value>[^\"'\s,;}\]]+)",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(
    r"(?P<prefix>\bBearer\s+)[^\s,;]+",
    re.IGNORECASE,
)
_SIGNED_QUERY_RE = re.compile(
    r"(?P<prefix>[?&](?:signature|token|x-amz-signature|x-amz-credential)="
    r")[^&\s]+",
    re.IGNORECASE,
)


def _normalized_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def is_sensitive_key(key: Any) -> bool:
    """Return whether a mapping key should have its value fully redacted."""

    normalized = _normalized_key(key)
    if normalized in _NORMALIZED_SENSITIVE_KEYS:
        return True
    return normalized.endswith(
        ("appkey", "appsecret", "token", "secret", "secretid", "secretkey")
    )


def redact_string(value: Any) -> str:
    """Redact common inline key/value and bearer-token forms in text."""

    text = str(value)
    text = _BEARER_RE.sub(lambda match: f"{match.group('prefix')}[REDACTED]", text)
    text = _INLINE_SECRET_RE.sub(lambda match: f"{match.group('prefix')}[REDACTED]", text)
    return _SIGNED_QUERY_RE.sub(lambda match: f"{match.group('prefix')}[REDACTED]", text)


def redact_value(value: Any) -> Any:
    """Recursively redact sensitive mapping values while preserving structure."""

    if isinstance(value, Mapping):
        return {
            key: "[REDACTED]" if is_sensitive_key(key) else redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    if isinstance(value, str):
        return redact_string(value)
    return value


def redact_mapping(value: Any) -> Any:
    """Public alias for recursively redacting a mapping or nested value."""

    return redact_value(value)


def redact_payload(value: Any) -> Any:
    """Redact a payload, parsing JSON strings so nested credentials are covered."""

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return redact_string(value)
        return json.dumps(redact_value(parsed), ensure_ascii=False, sort_keys=True, default=str)
    return redact_value(value)


def redact_error(value: Any) -> Any:
    """Redact an error/response before it is included in a diagnostic log."""

    if isinstance(value, BaseException):
        return redact_string(value)
    return redact_payload(value)

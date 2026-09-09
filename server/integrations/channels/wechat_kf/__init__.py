"""WeChat 客服 (WeCom Customer Service) channel adapter."""

from integrations.channels.wechat_kf.adapter import (
    WECHAT_KF,
    WechatKfAdapter,
    WechatKfInboundEnvelope,
)
from integrations.channels.wechat_kf.outbound import WechatKfSender
from integrations.channels.wechat_kf.transport import WechatCorpTokenCache, WechatKfTransport

__all__ = [
    "WECHAT_KF",
    "WechatKfAdapter",
    "WechatKfInboundEnvelope",
    "WechatKfSender",
    "WechatKfTransport",
    "WechatCorpTokenCache",
]

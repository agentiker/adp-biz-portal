"""WeChat 客服 (WeCom Customer Service) channel adapter."""

from integrations.channels.wechat_kf.adapter import (
    WECHAT_KF,
    WechatKfAdapter,
    WechatKfInboundEnvelope,
)

__all__ = ["WECHAT_KF", "WechatKfAdapter", "WechatKfInboundEnvelope"]

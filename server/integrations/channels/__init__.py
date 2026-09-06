"""Channel protocol adapters for the unified platform."""

from integrations.channels.base import ChannelAdapter, ChannelCapabilities, ChannelSender, DeliveryReceipt, OutboundMessage
from integrations.channels.registry import ChannelAdapterRegistry, channel_registry
from integrations.channels.wechat_official_account import (
    WechatInboundEnvelope,
    WechatOfficialAccountAdapter,
    WechatOfficialAccountSender,
)

__all__ = [
    "ChannelAdapter", "ChannelCapabilities", "ChannelSender", "DeliveryReceipt", "OutboundMessage",
    "ChannelAdapterRegistry", "channel_registry", "WechatInboundEnvelope",
    "WechatOfficialAccountAdapter", "WechatOfficialAccountSender",
]

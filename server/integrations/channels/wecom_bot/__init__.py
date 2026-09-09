"""企业微信智能机器人 (WeCom smart robot) channel adapter (WS real streaming)."""

from integrations.channels.wecom_bot.adapter import (
    WECOM_BOT,
    WecomBotAdapter,
    WecomBotInboundEnvelope,
)

__all__ = ["WECOM_BOT", "WecomBotAdapter", "WecomBotInboundEnvelope"]

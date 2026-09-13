import pytest

from integrations.channels.base import ChannelCapabilities, ChannelAdapter, inbound_from_envelope
from integrations.channels.registry import ChannelAdapterRegistry, ChannelRegistryError
from integrations.channels.web import WebChannelAdapter


def test_web_adapter_is_reference_channel_contract():
    adapter = WebChannelAdapter()
    assert isinstance(adapter, ChannelAdapter)
    assert adapter.capabilities.supports_inbound is True
    assert adapter.capabilities.supports_outbound is True
    assert adapter.capabilities.message_types == frozenset({"text"})


def test_registry_rejects_duplicates_and_unknown_channels():
    registry = ChannelAdapterRegistry()
    registry.register(WebChannelAdapter())
    with pytest.raises(ChannelRegistryError):
        registry.register(WebChannelAdapter())
    with pytest.raises(ChannelRegistryError):
        registry.get("wechat", "official-account")


def test_registry_replace_is_explicit():
    registry = ChannelAdapterRegistry()
    first = WebChannelAdapter()
    second = WebChannelAdapter()
    registry.register(first)
    registry.register(second, replace=True)
    assert registry.get("web", "web-portal") is second


def test_invalid_envelope_fails_closed():
    with pytest.raises(TypeError):
        inbound_from_envelope(object())

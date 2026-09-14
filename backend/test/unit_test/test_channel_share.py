"""Share-token primitives: prefix, entropy, digest determinism, input guards."""

from __future__ import annotations

import hashlib

import pytest

from core import channel_share


def test_generated_token_has_prefix_and_is_unique():
    a = channel_share.generate_shared_result_token()
    b = channel_share.generate_shared_result_token()
    assert a.startswith("psr_")
    assert b.startswith("psr_")
    assert a != b
    assert len(a) > 20  # token_urlsafe(32) is long


def test_token_hash_is_sha256_and_deterministic():
    token = "psr_example-token"
    digest = channel_share.shared_result_token_hash(token)
    assert digest == hashlib.sha256(token.encode("utf-8")).hexdigest()
    assert channel_share.shared_result_token_hash(f"  {token}  ") == digest  # trims


@pytest.mark.parametrize("bad", ["", "   ", None, 123, "x" * 300])
def test_token_hash_rejects_invalid_input(bad):
    with pytest.raises(ValueError):
        channel_share.shared_result_token_hash(bad)

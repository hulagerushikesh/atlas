"""Tests for content hashing utilities."""

from atlas.ingestion.hashing import hash_bytes, hash_text


def test_hash_bytes_deterministic() -> None:
    data = b"hello world"
    assert hash_bytes(data) == hash_bytes(data)


def test_hash_bytes_different_inputs_differ() -> None:
    assert hash_bytes(b"foo") != hash_bytes(b"bar")


def test_hash_text_consistent_with_bytes() -> None:
    text = "hello"
    assert hash_text(text) == hash_bytes(text.encode("utf-8"))


def test_hash_bytes_returns_hex_string() -> None:
    h = hash_bytes(b"test")
    assert isinstance(h, str)
    int(h, 16)  # must be valid hex

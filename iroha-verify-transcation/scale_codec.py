"""Minimal SCALE codec helpers used by the Iroha protocol module."""

from typing import Tuple


def encode_compact_u(value: int) -> bytes:
    """Encode SCALE compact unsigned integer for small/medium values."""
    if value < 0:
        raise ValueError("Compact integer must be non-negative.")
    if value < 1 << 6:
        return bytes([(value << 2) & 0xFF])
    if value < 1 << 14:
        encoded = (value << 2) | 0b01
        return encoded.to_bytes(2, "little")
    if value < 1 << 30:
        encoded = (value << 2) | 0b10
        return encoded.to_bytes(4, "little")
    raise ValueError("Compact integer too large for this script.")


def decode_compact_u(data: bytes, offset: int) -> Tuple[int, int]:
    """Decode SCALE compact unsigned integer and return (value, next_offset)."""
    first = data[offset]
    mode = first & 0b11
    if mode == 0:
        return first >> 2, offset + 1
    if mode == 1:
        raw = int.from_bytes(data[offset : offset + 2], "little")
        return raw >> 2, offset + 2
    if mode == 2:
        raw = int.from_bytes(data[offset : offset + 4], "little")
        return raw >> 2, offset + 4
    byte_len = (first >> 2) + 4
    raw = int.from_bytes(data[offset + 1 : offset + 1 + byte_len], "little")
    return raw, offset + 1 + byte_len


def encode_string(value: str) -> bytes:
    """Encode UTF-8 string as SCALE compact length + bytes."""
    data = value.encode("utf-8")
    return encode_compact_u(len(data)) + data

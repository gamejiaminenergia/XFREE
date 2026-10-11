"""Encode the engine's raw RGB buffer as PNG, with the standard library only.

The engine hands out ``bytes`` (320x200x3, RGB).  A browser cannot read that, and
pulling Pillow into a service that only needs "show these pixels" is not worth a
dependency: zlib is in the stdlib and a PNG is a handful of chunks.
"""

from __future__ import annotations

import struct
import zlib

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _chunk(tag: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + tag
        + payload
        + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
    )


def encode_png(rgb: bytes, width: int, height: int, *, level: int = 6) -> bytes:
    """A truecolour PNG from ``width * height * 3`` bytes of RGB."""

    expected = width * height * 3
    if len(rgb) != expected:
        raise ValueError(f"expected {expected} bytes of RGB, got {len(rgb)}")
    stride = width * 3
    raw = bytearray()
    for row in range(height):
        raw.append(0)  # filter type 0: none, the cheapest for a screenshot
        raw += rgb[row * stride : (row + 1) * stride]
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit truecolour
    return (
        PNG_MAGIC
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), level))
        + _chunk(b"IEND", b"")
    )


def decode_png_size(png: bytes) -> tuple[int, int]:
    """The dimensions declared by a PNG's IHDR.  Used by the tests."""

    if not png.startswith(PNG_MAGIC):
        raise ValueError("not a PNG")
    width, height = struct.unpack(">II", png[16:24])
    return width, height

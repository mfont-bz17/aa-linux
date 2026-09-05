"""Frame read/write — translated from frame.c."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional

import sys

from .constants import (
    AA_ERR_IO,
    AA_FRAME_FIRST,
    AA_FLAG_FRAME_TYPE_MASK,
    AA_MAX_FRAME_PAYLOAD,
    AA_OK,
)


@dataclass
class AAFrame:
    channel_id: int
    flags: int
    payload_len: int
    total_size: int
    is_first: bool
    payload: bytes


def _fully_recv(transport, buf_len: int, timeout_ms: int) -> tuple[int, bytes]:
    """Read exactly buf_len bytes from transport."""
    buf = bytearray()
    total = 0
    while total < buf_len:
        n, data = transport.recv(buf_len - total, timeout_ms)
        if n <= 0:
            return (AA_ERR_IO if n == 0 else n), bytes(buf)
        buf.extend(data)
        total += n
    return total, bytes(buf)


def frame_write(transport, channel_id: int, flags: int,
                payload: bytes, payload_len: int, total_size: int = 0) -> int:
    """Write a frame to the transport."""
    frame_type = flags & AA_FLAG_FRAME_TYPE_MASK

    if payload_len > 65535:
        print(f"[WARN] frame_write: payload too large: {payload_len}B > 65535", file=sys.stderr)
        return AA_ERR_IO
    if frame_type == AA_FRAME_FIRST:
        hdr = struct.pack(">BBHI", channel_id, flags, payload_len, total_size)
    else:
        hdr = struct.pack(">BBH", channel_id, flags, payload_len)

    rc = transport.send(hdr)
    if rc < 0:
        return rc

    if payload_len > 0 and payload:
        rc = transport.send(payload[:payload_len])
        if rc < 0:
            return rc

    return AA_OK


def frame_read(transport, timeout_ms: int) -> tuple[int, Optional[AAFrame]]:
    """Read a frame from the transport."""
    n, hdr = _fully_recv(transport, 4, timeout_ms)
    if n < 0:
        return n, None
    if n != 4:
        return AA_ERR_IO, None

    channel_id = hdr[0]
    flags = hdr[1]
    payload_len = (hdr[2] << 8) | hdr[3]
    is_first = False
    total_size = 0

    frame_type = flags & AA_FLAG_FRAME_TYPE_MASK

    if frame_type == AA_FRAME_FIRST:
        n, ext = _fully_recv(transport, 4, timeout_ms)
        if n != 4:
            return AA_ERR_IO, None
        total_size = (ext[0] << 24) | (ext[1] << 16) | (ext[2] << 8) | ext[3]
        is_first = True

    if payload_len > AA_MAX_FRAME_PAYLOAD:
        return AA_ERR_IO, None

    payload = b""
    if payload_len > 0:
        n, payload = _fully_recv(transport, payload_len, timeout_ms)
        if n < 0:
            return n, None
        if n != payload_len:
            return AA_ERR_IO, None

    return AA_OK, AAFrame(
        channel_id=channel_id,
        flags=flags,
        payload_len=payload_len,
        total_size=total_size,
        is_first=is_first,
        payload=payload,
    )

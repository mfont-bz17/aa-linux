"""FunctionFS USB transport — phone side as a USB gadget (VID 0x18d1, PID 0x2d01).

The DHU's ``--usb`` transport enumerates via libusb and accepts a device
already in Google accessory mode: PID in {0x2d00,0x2d01,0x2d04,0x2d05} with an
interface of class 0xFF/0xFF/0x00 exposing bulk IN + bulk OUT endpoints. This
module registers those descriptors through Linux FunctionFS and exposes the
same transport interface as ``TCPTransport``, so ``protocol.py``/``frame.py``
are transport-agnostic.
"""

from __future__ import annotations

import os
import select
import struct
import threading
import time

from .constants import AA_ERR_IO, AA_ERR_TIMEOUT, AA_OK
from .util import log

# FunctionFS ABI (include/uapi/linux/usb/functionfs.h)
_FFS_DESCRIPTORS_MAGIC_V2 = 3
_FFS_STRINGS_MAGIC = 2
_FFS_HAS_FS_DESC = 1
_FFS_HAS_HS_DESC = 2

# Endpoint files are named ep1..epN in descriptor declaration order
# (ffs_epfiles_create). We declare OUT first (0x02), then IN (0x81).
_OUT_EP = "ep1"
_IN_EP = "ep2"

_READ_CHUNK = 65536
_EP_OPEN_RETRIES = 100
_EP_OPEN_RETRY_DELAY_S = 0.1

_EVENT_NAMES = {0: "BIND", 1: "UNBIND", 2: "ENABLE", 3: "DISABLE",
                4: "SETUP", 5: "SUSPEND", 6: "RESUME"}


def _interface_desc() -> bytes:
    return bytes([9, 4, 0, 0, 2, 0xFF, 0xFF, 0x00, 0])


def _endpoint_desc(addr: int, w_max_packet: int) -> bytes:
    return struct.pack("<BBBBHB", 7, 5, addr, 2, w_max_packet, 0)


def _ffs_descriptors_blob(fs_max_packet: int = 64, hs_max_packet: int = 512) -> bytes:
    fs = _interface_desc() + _endpoint_desc(0x02, fs_max_packet) + _endpoint_desc(0x81, fs_max_packet)
    hs = _interface_desc() + _endpoint_desc(0x02, hs_max_packet) + _endpoint_desc(0x81, hs_max_packet)
    blob = struct.pack("<IIIII", _FFS_DESCRIPTORS_MAGIC_V2, 0,
                       _FFS_HAS_FS_DESC | _FFS_HAS_HS_DESC, 3, 3) + fs + hs
    return struct.pack("<IIIII", _FFS_DESCRIPTORS_MAGIC_V2, len(blob),
                       _FFS_HAS_FS_DESC | _FFS_HAS_HS_DESC, 3, 3) + fs + hs


def _ffs_strings_blob() -> bytes:
    return struct.pack("<IIII", _FFS_STRINGS_MAGIC, 16, 0, 0)


class FunctionFSTransport:
    """FunctionFS transport: bulk transfers on a configfs gadget."""

    def __init__(self, ffs_dir: str = "/dev/aa_linux", verbose: bool = False):
        self.ffs_dir = ffs_dir
        self.verbose = verbose
        self._ep0 = None
        self._out_fd = None
        self._in_fd = None
        self._reader = None
        self._stop = threading.Event()
        self._cond = threading.Condition()
        self._buf = bytearray()
        self._eof = False

    def connect(self) -> int:
        ep0_path = os.path.join(self.ffs_dir, "ep0")
        try:
            self._ep0 = os.open(ep0_path, os.O_RDWR)
        except OSError as e:
            log(f"FFS: cannot open {ep0_path}: {e} "
                f"(gadget not set up? run ./usb_gadget.sh start)")
            return AA_ERR_IO
        os.set_blocking(self._ep0, False)

        descs = _ffs_descriptors_blob()
        if self.verbose:
            log(f"FFS: registering descriptors ({len(descs)} bytes)")
        try:
            os.write(self._ep0, descs)
        except OSError as e:
            log(f"FFS: descriptor write failed: {e}")
            self.close()
            return AA_ERR_IO

        try:
            os.write(self._ep0, _ffs_strings_blob())
        except OSError as e:
            log(f"FFS: strings write failed: {e}")
            self.close()
            return AA_ERR_IO

        ep1 = os.path.join(self.ffs_dir, _OUT_EP)
        ep2 = os.path.join(self.ffs_dir, _IN_EP)
        err = None
        for _ in range(_EP_OPEN_RETRIES):
            try:
                self._out_fd = os.open(ep1, os.O_RDWR)
                self._in_fd = os.open(ep2, os.O_RDWR)
                break
            except OSError as e:
                err = e
                self._out_fd = None
                self._in_fd = None
                time.sleep(_EP_OPEN_RETRY_DELAY_S)
        if self._out_fd is None:
            log(f"FFS: endpoint files not created ({ep1}/{ep2}): {err}")
            self.close()
            return AA_ERR_IO
        os.set_blocking(self._out_fd, False)

        self._stop.clear()
        self._eof = False
        self._buf.clear()
        self._reader = threading.Thread(target=self._reader_loop, daemon=True,
                                        name="ffs-reader")
        self._reader.start()
        log("FFS: USB function registered, endpoints open (waiting for DHU)")
        return AA_OK

    def send(self, data: bytes) -> int:
        if self._in_fd is None:
            return AA_ERR_IO
        total = 0
        while total < len(data):
            try:
                n = os.write(self._in_fd, data[total:])
                if n <= 0:
                    return AA_ERR_IO
                total += n
            except OSError:
                return AA_ERR_IO
        return total

    def recv(self, buf_len: int, timeout_ms: int) -> tuple[int, bytes]:
        with self._cond:
            deadline = time.monotonic() + timeout_ms / 1000.0
            while not self._buf and not self._eof:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return AA_ERR_TIMEOUT, b""
                self._cond.wait(min(remaining, 1.0))
            if not self._buf:
                return AA_ERR_IO, b""
            take = min(buf_len, len(self._buf)) if buf_len > 0 else 0
            if take <= 0:
                return 0, b""
            data = bytes(self._buf[:take])
            del self._buf[:take]
            return take, data

    def close(self) -> None:
        self._stop.set()
        if self._reader is not None and self._reader.is_alive():
            self._reader.join(timeout=2.0)
        self._reader = None
        for fd in (self._ep0, self._out_fd, self._in_fd):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        self._ep0 = None
        self._out_fd = None
        self._in_fd = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _set_eof(self) -> None:
        with self._cond:
            self._eof = True
            self._cond.notify_all()

    def _handle_event(self, etype: int) -> None:
        name = _EVENT_NAMES.get(etype, str(etype))
        if self.verbose:
            log(f"FFS: event {name}")
        if etype in (1, 3):
            log("FFS: DHU disconnected")
            self._set_eof()

    def _reader_loop(self) -> None:
        watch = [fd for fd in (self._out_fd, self._ep0) if fd is not None]
        while not self._stop.is_set():
            try:
                ready, _, _ = select.select(watch, [], [], 0.2)
            except (OSError, ValueError):
                break
            for fd in ready:
                if fd == self._out_fd:
                    try:
                        data = os.read(self._out_fd, _READ_CHUNK)
                    except BlockingIOError:
                        continue
                    except OSError:
                        data = b""
                    if not data:
                        self._set_eof()
                        return
                    with self._cond:
                        self._buf.extend(data)
                        self._cond.notify_all()
                else:
                    try:
                        ev = os.read(self._ep0, 12)
                    except (BlockingIOError, OSError):
                        continue
                    if len(ev) == 12:
                        self._handle_event(ev[8])


def _self_test() -> int:
    import socket

    descs = _ffs_descriptors_blob()
    assert descs[:4] == struct.pack("<I", _FFS_DESCRIPTORS_MAGIC_V2), "magic"
    assert struct.unpack("<I", descs[4:8])[0] == len(descs), "length field"
    assert struct.unpack("<I", descs[8:12])[0] == _FFS_HAS_FS_DESC | _FFS_HAS_HS_DESC, "flags"
    fs_count, hs_count = struct.unpack("<II", descs[12:20])
    assert fs_count == 3 and hs_count == 3, "descriptor counts"
    assert len(descs) == 20 + 23 + 23, f"blob size {len(descs)}"
    assert b"\x09\x04\x00\x00\x02\xff\xff\x00\x00" in descs, "interface 0xFF/0xFF/0x00"
    assert b"\x07\x05\x02\x02\x40\x00\x00" in descs, "OUT bulk FS"
    assert b"\x07\x05\x81\x02\x40\x00\x00" in descs, "IN bulk FS"
    assert b"\x07\x05\x02\x02\x00\x02\x00" in descs, "OUT bulk HS"
    assert b"\x07\x05\x81\x02\x00\x02\x00" in descs, "IN bulk HS"

    strs = _ffs_strings_blob()
    assert struct.unpack("<I", strs[0:4])[0] == _FFS_STRINGS_MAGIC, "strings magic"
    assert struct.unpack("<I", strs[4:8])[0] == len(strs) == 16, "strings length"
    assert struct.unpack("<II", strs[8:16]) == (0, 0), "str/lang counts both zero"
    log("FFS self-test: descriptor/strings blobs OK")

    read_pipe = os.pipe()
    write_pipe = os.pipe()
    t = FunctionFSTransport(verbose=False)
    t._out_fd = read_pipe[0]
    t._in_fd = write_pipe[1]
    t._stop.clear()
    t._eof = False
    t._reader = threading.Thread(target=t._reader_loop, daemon=True)
    t._reader.start()

    from .frame import frame_read, frame_write

    class HostShim:
        def __init__(self, read_fd, write_fd):
            self.read_fd = read_fd
            self.write_fd = write_fd

        def send(self, data: bytes) -> int:
            return os.write(self.write_fd, data)

        def recv(self, buf_len: int, timeout_ms: int) -> tuple[int, bytes]:
            ready, _, _ = select.select([self.read_fd], [], [], timeout_ms / 1000.0)
            if not ready:
                return AA_ERR_TIMEOUT, b""
            data = os.read(self.read_fd, buf_len)
            return len(data), data

    host = HostShim(write_pipe[0], read_pipe[1])
    payload = bytes(range(256)) * 4
    rc = frame_write(t, 3, 0x03, payload, len(payload))
    assert rc == AA_OK, f"frame_write rc={rc}"
    rc2, frame = frame_read(host, 5000)
    assert rc2 == AA_OK, f"host frame_read rc={rc2}"
    assert frame.channel_id == 3 and frame.payload == payload, "framing round-trip"

    t.close()
    os.close(read_pipe[1])
    os.close(write_pipe[0])
    log("FFS self-test: framing over send/recv OK")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(_self_test())

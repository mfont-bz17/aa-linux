"""TCP transport — translated from transport_tcp.c."""

from __future__ import annotations

import select
import socket
from typing import Optional

from .constants import AA_ERR_IO, AA_ERR_TIMEOUT, AA_OK
from .util import log


class TCPTransport:
    """Blocking TCP transport with server/client modes."""

    def __init__(self, host: str = "0.0.0.0", port: int = 5277, server_mode: bool = True):
        self.host = host
        self.port = port
        self.server_mode = server_mode
        self._sock: Optional[socket.socket] = None
        self._stopped = False

    @property
    def interrupted(self) -> bool:
        """True when interrupt() was called (e.g. SIGINT while listening)."""
        return self._stopped

    def interrupt(self) -> None:
        """Ask a blocked connect()/accept() to return so the main loop can
        observe the shutdown flag. Called from the SIGINT/SIGTERM handler."""
        self._stopped = True

    def connect(self) -> int:
        if self.server_mode:
            return self._server_connect()
        return self._client_connect()

    def _server_connect(self) -> int:
        try:
            listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listen_sock.bind((self.host, self.port))
            listen_sock.listen(1)
            log(f"Listening on port {self.port}...")
            while not self._stopped:
                ready, _, _ = select.select([listen_sock], [], [], 0.5)
                if ready:
                    self._sock, addr = listen_sock.accept()
                    break
            listen_sock.close()
            if self._stopped:
                log("Listening interrupted")
                return AA_ERR_IO
            self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            log(f"Client connected from {addr[0]}:{addr[1]}")
            return AA_OK
        except OSError as e:
            log(f"Server connect error: {e}")
            return AA_ERR_IO

    def _client_connect(self) -> int:
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            log(f"Connecting to {self.host}:{self.port}...")
            self._sock.connect((self.host, self.port))
            self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            log("Connected.")
            return AA_OK
        except OSError as e:
            log(f"Client connect error: {e}")
            return AA_ERR_IO

    def send(self, data: bytes) -> int:
        if self._sock is None:
            return AA_ERR_IO
        total = 0
        while total < len(data):
            try:
                n = self._sock.send(data[total:])
                if n <= 0:
                    return AA_ERR_IO
                total += n
            except OSError:
                return AA_ERR_IO
        return total

    def recv(self, buf_len: int, timeout_ms: int) -> tuple[int, bytes]:
        if self._sock is None:
            return AA_ERR_IO, b""
        readable, _, _ = select.select([self._sock], [], [], timeout_ms / 1000.0)
        if not readable:
            return AA_ERR_TIMEOUT, b""
        try:
            data = self._sock.recv(buf_len)
            if not data:
                return AA_ERR_IO, b""
            return len(data), data
        except OSError:
            return AA_ERR_IO, b""

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def __del__(self) -> None:
        self.close()

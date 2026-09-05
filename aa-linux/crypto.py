"""TLS crypto using ssl.MemoryBIO — translated from crypto.c."""

from __future__ import annotations

import ssl
from typing import Optional

from .constants import AA_ERR_TLS, AA_OK
from .util import log


class AACrypto:
    """TLS wrapper using memory BIOs (no socket needed)."""

    def __init__(self, is_server: bool = True):
        self.is_server = is_server
        self.handshake_done = False
        self._ctx: Optional[ssl.SSLContext] = None
        self._ssl: Optional[ssl.SSLObject] = None
        self._bio_out: Optional[ssl.MemoryBIO] = None  # data TO send to peer
        self._bio_in: Optional[ssl.MemoryBIO] = None   # data FROM peer

    @classmethod
    def create_server(cls, cert_path: str, key_path: str) -> "AACrypto":
        c = cls(is_server=True)
        c._ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        c._ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        c._ctx.maximum_version = ssl.TLSVersion.TLSv1_2
        try:
            c._ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
        except FileNotFoundError:
            log(f"Warning: cert/key not found: {cert_path}, {key_path}")
        c._ctx.verify_mode = ssl.CERT_NONE  # We handle cert verification manually

        c._bio_in = ssl.MemoryBIO()
        c._bio_out = ssl.MemoryBIO()
        c._ssl = c._ctx.wrap_bio(c._bio_in, c._bio_out, server_side=True)
        return c

    @classmethod
    def create_client(cls, cert_path: str, key_path: str) -> "AACrypto":
        c = cls(is_server=False)
        c._ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        c._ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        c._ctx.maximum_version = ssl.TLSVersion.TLSv1_2
        c._ctx.check_hostname = False
        c._ctx.verify_mode = ssl.CERT_NONE
        if cert_path and key_path:
            try:
                c._ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
            except Exception:
                pass

        c._bio_in = ssl.MemoryBIO()
        c._bio_out = ssl.MemoryBIO()
        c._ssl = c._ctx.wrap_bio(c._bio_in, c._bio_out, server_side=False)
        return c

    def destroy(self) -> None:
        self._ssl = None
        self._bio_out = None
        self._bio_in = None
        self._ctx = None

    def feed_recv(self, data: bytes) -> int:
        """Feed ciphertext received from the network into the TLS layer."""
        try:
            self._bio_in.write(data)
            return len(data)
        except ssl.SSLError:
            return AA_ERR_TLS

    def drain_send(self) -> bytes:
        """Read any pending ciphertext to send to the network."""
        try:
            return self._bio_out.read()
        except ssl.SSLError:
            return b""

    def accept(self) -> int:
        """Perform one step of the TLS handshake."""
        if self.handshake_done:
            return AA_OK
        try:
            self._ssl.do_handshake()
            self.handshake_done = True
            log(f"TLS handshake complete: {self._ssl.cipher()}")
            return AA_OK
        except ssl.SSLWantReadError:
            return AA_OK
        except ssl.SSLWantWriteError:
            return AA_OK
        except ssl.SSLError as e:
            log(f"TLS handshake error: {e}")
            return AA_ERR_TLS

    def write_encrypted(self, plain: bytes) -> tuple[int, bytes]:
        """Encrypt plaintext, returns (rc, ciphertext)."""
        try:
            self._ssl.write(plain)
        except ssl.SSLWantReadError:
            return AA_OK, b""
        except ssl.SSLWantWriteError:
            return AA_OK, b""
        except ssl.SSLError as e:
            log(f"SSL_write error: {e}")
            return AA_ERR_TLS, b""

        cipher = self.drain_send()
        return AA_OK, cipher

    def read_decrypted(self, cipher: bytes) -> tuple[int, bytes]:
        """Decrypt ciphertext, returns (rc, plaintext)."""
        rc = self.feed_recv(cipher)
        if rc < 0:
            return AA_ERR_TLS, b""

        out = bytearray()
        try:
            while True:
                try:
                    part = self._ssl.read(65535)
                except (ssl.SSLWantReadError, ssl.SSLWantWriteError):
                    break
                if not part:
                    break
                out += part
        except ssl.SSLError as e:
            log(f"SSL_read error: {e}")
            return AA_ERR_TLS, bytes(out)
        return AA_OK, bytes(out)

    def get_cipher(self) -> str:
        if self._ssl:
            try:
                c = self._ssl.cipher()
                return c[0] if c else "unknown"
            except Exception:
                return "unknown"
        return "none"

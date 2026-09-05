"""Wireless transport — phone-side Bluetooth + WiFi setup for a real head unit.

Establishes the same byte stream aa-linux already consumes over TCP, but the
way a real Android phone reaches a car: BT pairing -> SDP discovery of the AA
UUID -> (best-effort) HFP AG presence -> RFCOMM channel 8 -> 5-stage WiFi
credential handshake -> join the HU's WiFi AP via nmcli -> TCP-connect to the
HU's listener. From there the existing GAL phone-side state machine takes over
unchanged (the HU initiates the version exchange; aa-linux is the TLS server).

RFCOMM frame: [length:u16be][msg_id:u16be][protobuf_payload]
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
from typing import Optional

from .constants import AA_ERR, AA_ERR_IO, AA_ERR_TIMEOUT, AA_OK
from .proto import (
    decode_wifi_info_response,
    decode_wifi_start_request,
    decode_wifi_version_request_full,
    encode_wifi_connect_status,
    encode_wifi_info_request,
    encode_wifi_info_response,
    encode_wifi_start_request,
    encode_wifi_start_response,
    encode_wifi_version_request,
    encode_wifi_version_response,
)
from .util import log

# Bluetooth service UUIDs (128-bit AA UUID, 16-bit HFP AG UUID)
AA_SERVICE_UUID = "4de17a00-52cb-11e6-bdf4-0800200c9a66"
AA_SERVICE_UUID_SHORT = "4de17a00"   # sdptool abbreviates 128-bit UUIDs
HFP_AG_UUID_16 = 0x111f

# WifiSetupMessage msgIds (BT RFCOMM WiFi setup)
WIFI_MSG_START_REQUEST = 1
WIFI_MSG_INFO_REQUEST = 2
WIFI_MSG_INFO_RESPONSE = 3
WIFI_MSG_VERSION_REQUEST = 4
WIFI_MSG_VERSION_RESPONSE = 5
WIFI_MSG_CONNECT_STATUS = 6
WIFI_MSG_START_RESPONSE = 7

# WifiVersionStatus wire value for SUCCESS. The APK (17.3, pfu.java) maps the
# internal status index to the wire value as `wire = index - 12`, where the
# compatible branch yields index 12 -> wire 0. (The stale comment in
# WifiVersionStatusEnum.proto claiming 1 = SUCCESS is wrong; 1 is
# STATUS_UNSOLICITED_MESSAGE.)
WIFI_STATUS_SUCCESS = 0

_RFCOMM_AVAILABLE = hasattr(socket, "AF_BLUETOOTH")

_BT_AGENT_PIN_FILE = "/tmp/aa-linux-bt-pin"

# Greppable names for the RFCOMM msgIds (WifiSetupMessageEnum)
WIFI_MSG_NAMES = {
    WIFI_MSG_START_REQUEST: "WifiStartRequest",
    WIFI_MSG_INFO_REQUEST: "WifiInfoRequest",
    WIFI_MSG_INFO_RESPONSE: "WifiInfoResponse",
    WIFI_MSG_VERSION_REQUEST: "WifiVersionRequest",
    WIFI_MSG_VERSION_RESPONSE: "WifiVersionResponse",
    WIFI_MSG_CONNECT_STATUS: "WifiConnectStatus",
    WIFI_MSG_START_RESPONSE: "WifiStartResponse",
    8: "WifiPingRequest",
    9: "WifiPingResponse",
}


def _hexdump(data: bytes, max_len: int = 48) -> str:
    if len(data) > max_len:
        return data[:max_len].hex(" ") + f" ... ({len(data)}B)"
    return data.hex(" ")


class AAWirelessError(Exception):
    pass


# ---------------------------------------------------------------------------
# RFCOMM framing helpers
# ---------------------------------------------------------------------------

def build_rfcomm_frame(msg_id: int, payload: bytes) -> bytes:
    return struct.pack(">HH", len(payload), msg_id) + payload


def parse_rfcomm_frame(data: bytes) -> tuple[int, bytes, bytes]:
    """Return (msg_id, payload, remainder) from a raw byte buffer."""
    if len(data) < 4:
        raise AAWirelessError("RFCOMM frame too short")
    (length, msg_id) = struct.unpack(">HH", data[:4])
    if len(data) < 4 + length:
        raise AAWirelessError("RFCOMM frame truncated")
    return msg_id, data[4:4 + length], data[4 + length:]


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except socket.timeout:
            raise AAWirelessError("RFCOMM read timeout")
        if not chunk:
            raise AAWirelessError("RFCOMM socket closed")
        buf += chunk
    return buf


def _send_all(sock: socket.socket, data: bytes) -> None:
    total = 0
    while total < len(data):
        n = sock.send(data[total:])
        if n <= 0:
            raise AAWirelessError("RFCOMM socket closed on write")
        total += n


# ---------------------------------------------------------------------------
# sdptool output parsing
# ---------------------------------------------------------------------------

def find_rfcomm_channel(sdp_text: str, uuid_fragment: str) -> Optional[int]:
    """RFCOMM channel of the SDP record containing uuid_fragment (the AA UUID
    or the 16-bit HFP AG UUID), parsed from `sdptool browse` output."""
    records = re.split(r"\n(?=Service RecHandle)", sdp_text)
    for rec in records:
        if uuid_fragment.lower() in rec.lower():
            m = re.search(r'"RFCOMM".*?Channel:\s*(\d+)', rec, re.S)
            if m:
                return int(m.group(1))
    return None


def _normalize_mac(mac: str) -> str:
    """Canonicalize a MAC/BSSID to uppercase colon-separated form
    (nmcli lists BSSIDs uppercase; HUs may send either case)."""
    mac = mac.strip()
    if not mac:
        return ""
    try:
        parts = mac.replace("-", ":").split(":")
        if len(parts) != 6:
            return mac
        return ":".join(f"{int(b, 16):02X}" for b in parts)
    except ValueError:
        return mac


# ---------------------------------------------------------------------------
# WirelessTransport
# ---------------------------------------------------------------------------

class WirelessTransport:
    """Wireless (BT + WiFi) transport with the TCPTransport interface.

    connect() runs the whole phone-side wireless setup and leaves a connected
    TCP socket to the HU; send()/recv()/close() then operate on that socket.
    """

    def __init__(self, bt_address: str = "", wlan_interface: str = "wlp3s0",
                 no_hfp: bool = False, timeout_ms: int = 30000,
                 verbose: bool = False, log_file: str = "",
                 rfcomm_channel: int = 0, wifi_timeout_ms: int = 15000):
        self.bt_address = bt_address
        self.wlan_interface = wlan_interface
        self.no_hfp = no_hfp
        self.timeout_ms = timeout_ms
        self.wifi_timeout_ms = wifi_timeout_ms
        self.verbose = verbose
        self.rfcomm_channel = rfcomm_channel
        self._device_serial = (socket.gethostname() or "unknown").replace(" ", "-")[:32] or "unknown"
        self._log_fh = open(log_file, "a") if log_file else None
        self._sock: Optional[socket.socket] = None
        self._rfcomm: Optional[socket.socket] = None
        self._hfp: Optional[socket.socket] = None
        self._bt_agent: Optional[subprocess.Popen] = None
        self._local_bdaddr: str = ""
        self._nm_profile: str = ""

    # -- logging ------------------------------------------------------------

    def _log(self, msg: str) -> None:
        log(msg)
        if self._log_fh is not None:
            try:
                self._log_fh.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
                self._log_fh.flush()
            except OSError:
                pass

    def _log_verbose(self, msg: str) -> None:
        if self.verbose:
            self._log(msg)

    def _stage(self, label: str) -> float:
        self._log(f"[wireless] >>> {label}")
        return time.monotonic()

    def _stage_ok(self, label: str, start: float) -> None:
        self._log(f"[wireless] <<< {label} OK ({time.monotonic() - start:.1f}s)")

    def _stage_fail(self, label: str, start: float, err: str) -> None:
        self._log(f"[wireless] <<< {label} FAIL ({time.monotonic() - start:.1f}s): {err}")

    # -- subprocess helpers ------------------------------------------------

    def _run_cmd(self, cmd: list, timeout_s: float = 30.0) -> tuple[int, str, str]:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=timeout_s)
            return proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "timed out"
        except FileNotFoundError:
            return -127, "", f"command not found: {cmd[0]}"
        except OSError as e:
            return -1, "", str(e)

    def _require(self, exe: str) -> None:
        if shutil.which(exe) is None:
            raise AAWirelessError(f"required tool not installed: {exe}")

    # -- connect() ---------------------------------------------------------

    def connect(self) -> int:
        try:
            if not self.bt_address or ":" not in self.bt_address:
                raise AAWirelessError("no --bt-address (HU Bluetooth MAC) given")
            if not _RFCOMM_AVAILABLE:
                raise AAWirelessError("Python lacks Bluetooth support (AF_BLUETOOTH)")
            for exe in ("bluetoothctl", "bt-agent", "nmcli"):
                self._require(exe)

            self._preflight()
            t = self._stage("BT pair/trust/connect")
            self._start_bt_agent()
            self._pair_bt()
            self._stage_ok("BT pair/trust/connect", t)

            t = self._stage("SDP discovery (AA RFCOMM channel)")
            if self.rfcomm_channel:
                aa_channel = self.rfcomm_channel
                hfp_channel = None
                self._log(f"[wireless] forcing RFCOMM channel {aa_channel} "
                          f"(--rfcomm-channel, SDP skipped)")
            else:
                aa_channel, hfp_channel = self._discover_sdp()
            aa_channel = aa_channel or 8
            self._log(f"[wireless] AA service on RFCOMM channel {aa_channel}")
            self._stage_ok("SDP discovery", t)

            if not self.no_hfp:
                t = self._stage("HFP AG presence (best-effort)")
                self._hfp = self._hfp_connect(hfp_channel)
                self._stage_ok("HFP AG presence", t)

            t = self._stage("RFCOMM connect")
            self._rfcomm = self._open_rfcomm(self.bt_address, aa_channel)
            self._log(f"[wireless] RFCOMM connected on channel {aa_channel}")
            self._stage_ok("RFCOMM connect", t)

            t = self._stage("WiFi credential handshake")
            ip_address, port = self._do_handshake(self._rfcomm, self._join_wifi)
            self._stage_ok("WiFi credential handshake", t)

            try:
                self._rfcomm.close()
            except OSError:
                pass
            self._rfcomm = None

            t = self._stage("TCP connect")
            self._sock = self._tcp_connect(ip_address, port)
            self._log(f"[wireless] local endpoint {self._sock.getsockname()}"
                      f" -> {ip_address}:{port}")
            self._stage_ok("TCP connect", t)
            self._log(f"[wireless] WIRELESS_SETUP: CONNECTED — ready for GAL")
            return AA_OK
        except AAWirelessError as e:
            log(f"Wireless transport error: {e}")
        except OSError as e:
            log(f"Wireless transport I/O error: {e}")
        self.close()
        return AA_ERR

    def _preflight(self) -> None:
        """Cheap sanity checks whose output matters when debugging at the car."""
        for radio in ("bluetooth", "wifi"):
            rc, out, _ = self._run_cmd(["rfkill", "list", radio], 5.0)
            if rc == 0 and "blocked yes" in out.lower():
                self._log(f"[wireless] WARN: rfkill shows {radio} blocked — run "
                          f"`rfkill unblock {radio}`")
        if self.verbose:
            rc, out, _ = self._run_cmd(["bluetoothctl", "list"], 5.0)
            if rc == 0:
                self._log(f"[wireless] BT adapters:\n{out.rstrip()}")
            rc, out, _ = self._run_cmd(["nmcli", "device", "status"], 5.0)
            if rc == 0:
                self._log(f"[wireless] nmcli devices:\n{out.rstrip()}")

    # -- Bluetooth pairing -------------------------------------------------

    def _start_bt_agent(self) -> None:
        with open(_BT_AGENT_PIN_FILE, "w") as f:
            f.write("1234\n")
        try:
            self._bt_agent = subprocess.Popen(
                ["bt-agent", "--capability=DisplayYesNo", "-p", _BT_AGENT_PIN_FILE],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            log(f"bt-agent failed to start (pairing may require manual confirm): {e}")

    def _pair_bt(self) -> None:
        addr = self.bt_address
        commands = (
            f"agent on\ndefault-agent\n"
            f"pair {addr}\ntrust {addr}\nexit\n"
        )
        rc, out, err = self._run_bluetoothctl(commands)
        for line in (out + err).splitlines():
            self._log_verbose(f"[wireless] bluetoothctl: {line.strip()}")
        if "Failed to pair" in out and "AlreadyExists" not in out:
            self._log("[wireless] WARN: BT pairing failed — device may already be paired")
        self._connect_bt()

    def _connect_bt(self) -> None:
        """Bring up the BR/EDR ACL link and wait until BlueZ reports the device
        Connected: yes. SDP over L2CAP PSM 1 needs this link; 'Connected: yes'
        can otherwise reflect an LE/GATT link only, which SDP cannot use."""
        addr = self.bt_address
        rc, out, err = self._run_bluetoothctl(f"connect {addr}\nexit\n")
        for line in (out + err).splitlines():
            self._log_verbose(f"[wireless] bluetoothctl: {line.strip()}")
        # Force a BR/EDR ACL directly (bluetoothctl only connects matched
        # profiles; hcitool cc pages the remote unconditionally).
        rc, out, err = self._run_cmd(["hcitool", "cc", addr], 15.0)
        if rc == 0:
            self._log_verbose(f"[wireless] hcitool cc: ACL link up")
        elif rc not in (-127,):
            self._log_verbose(f"[wireless] hcitool cc: {err.strip() or out.strip()}")
        deadline = time.monotonic() + self.timeout_ms / 1000.0
        while time.monotonic() < deadline:
            rc, out, _ = self._run_cmd(["bluetoothctl", "info", addr], 10.0)
            if "Connected: yes" in out:
                self._log(f"[wireless] BT connected to {addr}")
                return
            time.sleep(1.0)
        self._log(f"[wireless] WARN: BT device {addr} never reported 'Connected: yes' — "
                  f"is the car's head unit ready/ignition on?")

    def _run_bluetoothctl(self, commands: str) -> tuple[int, str, str]:
        try:
            proc = subprocess.run(
                ["bluetoothctl"], input=commands, capture_output=True,
                text=True, timeout=40.0)
            return proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "timed out"
        except FileNotFoundError:
            return -127, "", "bluetoothctl not found"
        except OSError as e:
            return -1, "", str(e)

    # -- SDP discovery -----------------------------------------------------

    def _local_adapters(self) -> list:
        """All local BT adapters as [(hciN, BD_ADDR)]. /sys first, then fall
        back to `bluetoothctl list` (works when sysfs isn't exposed, e.g.
        containers/VMs)."""
        adapters = []
        try:
            for entry in sorted(os.listdir("/sys/class/bluetooth")):
                if not entry.startswith("hci"):
                    continue
                try:
                    with open(f"/sys/class/bluetooth/{entry}/address") as f:
                        bdaddr = f.read().strip()
                except OSError:
                    continue
                if bdaddr:
                    adapters.append((entry, bdaddr))
        except OSError:
            pass
        if adapters:
            return adapters
        rc, out, _ = self._run_cmd(["bluetoothctl", "list"], 10.0)
        if rc == 0:
            for line in out.splitlines():
                if line.startswith("Controller "):
                    parts = line.split()
                    if len(parts) >= 2 and ":" in parts[1]:
                        adapters.append((f"hci{len(adapters)}", parts[1]))
        return adapters

    def _local_adapter(self) -> str:
        """First local BT adapter (hciN); for the sdptool fallback."""
        adapters = self._local_adapters()
        return adapters[0][0] if adapters else ""

    def _discover_sdp(self) -> tuple[Optional[int], Optional[int]]:
        """Discover (aa_channel, hfp_ag_channel). Order:
        1. `sdptool records` — full SDP record dump (finds non-browsable
           records like SPP `SPPAAWL0`),
        2. RFCOMM channel probe,
        3. standard AA channel 8 as last resort."""
        if self.rfcomm_channel:
            # A pinned channel means no SDP at all.
            self._log(f"[wireless] --rfcomm-channel {self.rfcomm_channel} given; "
                      f"SDP discovery skipped")
            return self.rfcomm_channel, None
        adapter = self._local_adapter()
        adapter_opt = ["-i", adapter] if adapter else []
        aa_ch = None
        hfp_ch = None

        rc, out, err = self._run_cmd(
            adapter_opt + ["sdptool", "records", self.bt_address], 20.0)
        if rc == 0:
            aa_ch = find_rfcomm_channel(out, AA_SERVICE_UUID_SHORT)
            hfp_ch = find_rfcomm_channel(out, f"{HFP_AG_UUID_16:04x}")
            if aa_ch or hfp_ch:
                if aa_ch:
                    self._log(f"[wireless] sdptool records: AA on RFCOMM channel {aa_ch}")
                if hfp_ch:
                    self._log(f"[wireless] sdptool records: HFP AG on RFCOMM channel {hfp_ch}")
                return aa_ch or 8, hfp_ch
            self._log("[wireless] sdptool records: connected but no AA/HFP record matched")
        else:
            self._log(f"[wireless] sdptool records failed ({rc}): {err.strip() or out.strip()}")

        self._log("[wireless] SDP unavailable — probing RFCOMM channels for the AA service...")
        probed = self._probe_rfcomm(self.bt_address)
        if probed is not None:
            return probed, hfp_ch
        self._log("[wireless] RFCOMM probe failed — using standard AA channel 8")
        return 8, hfp_ch

    def _probe_rfcomm(self, addr: str) -> Optional[int]:
        """Last-resort channel discovery when SDP is unreachable: probe RFCOMM
        channels 1..30. A channel is the AA service iff it accepts a connection
        and immediately speaks the WiFi setup handshake (WifiStartRequest)."""
        candidates = [8] + [c for c in range(1, 31) if c != 8]
        for ch in candidates:
            try:
                sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM,
                                     socket.BTPROTO_RFCOMM)
                sock.settimeout(2.0)
                if self._local_bdaddr:
                    sock.bind((self._local_bdaddr, 0))
                sock.connect((addr, ch))
            except OSError:
                continue
            try:
                msg_id, _ = self._read_frame(sock, 1500)
                if msg_id == WIFI_MSG_START_REQUEST:
                    self._log(f"[wireless] probe: AA service on RFCOMM channel {ch}")
                    return ch
            except (AAWirelessError, OSError):
                pass
            finally:
                try:
                    sock.close()
                except OSError:
                    pass
        return None

    # -- RFCOMM / HFP ------------------------------------------------------

    def _open_rfcomm(self, addr: str, channel: int) -> socket.socket:
        sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM,
                             socket.BTPROTO_RFCOMM)
        sock.settimeout(self.timeout_ms / 1000.0)
        if self._local_bdaddr:
            sock.bind((self._local_bdaddr, 0))
        sock.connect((addr, channel))
        return sock

    def _hfp_connect(self, channel: Optional[int] = None) -> Optional[socket.socket]:
        try:
            if channel is None:
                self._log("[wireless] no HFP AG channel discovered — skipping")
                return None
            sock = self._open_rfcomm(self.bt_address, channel)
            sock.settimeout(None)
            self._log(f"[wireless] HFP AG connected on channel {channel} (held open)")
            return sock
        except OSError as e:
            self._log(f"[wireless] WARN: HFP AG connect failed (non-fatal): {e}")
            return None

    # -- 5-stage WiFi credential handshake --------------------------------

    def _read_frame(self, sock: socket.socket, timeout_ms: Optional[int] = None) -> tuple[int, bytes]:
        t = timeout_ms if timeout_ms is not None else self.timeout_ms
        prev = sock.gettimeout()
        sock.settimeout(t / 1000.0)
        try:
            (length, msg_id) = struct.unpack(">HH", _recv_exact(sock, 4))
            payload = _recv_exact(sock, length)
            self._log_verbose(f"[wireless] RFCOMM recv msgId={msg_id} "
                              f"({WIFI_MSG_NAMES.get(msg_id, '?')}) len={length} "
                              f"payload={_hexdump(payload)}")
            return msg_id, payload
        finally:
            sock.settimeout(prev)

    def _send_frame(self, sock: socket.socket, msg_id: int, payload: bytes) -> None:
        self._log_verbose(f"[wireless] RFCOMM send msgId={msg_id} "
                          f"({WIFI_MSG_NAMES.get(msg_id, '?')}) len={len(payload)} "
                          f"payload={_hexdump(payload)}")
        _send_all(sock, build_rfcomm_frame(msg_id, payload))

    def _answer_version_request(self, sock: socket.socket, payload: bytes) -> None:
        info = decode_wifi_version_request_full(payload)
        car = " ".join(x for x in (info["manufacturer"], info["model"]) if x)
        self._log(f"[wireless] HU version request {info['major']}.{info['minor']}"
                  f"{(' (' + car + ')') if car else ''} -> respond SUCCESS")
        self._send_frame(sock, WIFI_MSG_VERSION_RESPONSE,
                         encode_wifi_version_response(info["major"], info["minor"],
                                                      WIFI_STATUS_SUCCESS,
                                                      serial=self._device_serial))

    def _do_handshake(self, sock: socket.socket, join_wifi) -> tuple[str, int]:
        # The HU may open with a WifiVersionRequest (msgId 4) BEFORE the
        # WifiStartRequest (msgId 1); answer it and keep reading.
        while True:
            msg_id, payload = self._read_frame(sock)
            if msg_id == WIFI_MSG_VERSION_REQUEST:
                self._answer_version_request(sock, payload)
                continue
            if msg_id == WIFI_MSG_START_REQUEST:
                break
            raise AAWirelessError(f"expected WifiStartRequest (1), got msgId {msg_id}")

        ip_address, port = decode_wifi_start_request(payload)
        self._log(f"[wireless] HU WiFi start request: ip={ip_address} port={port}")

        self._send_frame(sock, WIFI_MSG_START_RESPONSE,
                         encode_wifi_start_response(ip_address, port, WIFI_STATUS_SUCCESS))

        try:
            msg_id, payload = self._read_frame(sock, 500)
        except AAWirelessError:
            msg_id, payload = None, b""
        if msg_id == WIFI_MSG_VERSION_REQUEST:
            self._answer_version_request(sock, payload)

        self._send_frame(sock, WIFI_MSG_INFO_REQUEST, encode_wifi_info_request())

        while True:
            msg_id, payload = self._read_frame(sock)
            if msg_id == WIFI_MSG_VERSION_REQUEST:
                self._answer_version_request(sock, payload)
                continue
            if msg_id == WIFI_MSG_INFO_RESPONSE:
                break
            raise AAWirelessError(f"unexpected msgId {msg_id} during info exchange")

        info = decode_wifi_info_response(payload)
        self._log(f"[wireless] WIFI_CREDENTIALS_RECEIVED ssid={info['ssid']!r} "
                  f"bssid={info['bssid']!r} passphrase=<redacted> "
                  f"security={info['security_mode']} ap_type={info['ap_type']}")

        join_wifi(info)
        self._send_frame(sock, WIFI_MSG_CONNECT_STATUS,
                         encode_wifi_connect_status(WIFI_STATUS_SUCCESS))
        return ip_address, port

    # -- WiFi join (nmcli) -------------------------------------------------

    def _wait_for_wifi(self, ssid: str, timeout_s: float) -> bool:
        """Poll scans until the car's AP is visible, or give up. The HU brings
        its AP up only after the credential exchange, so the network can take
        a few seconds to appear."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            self._run_cmd(["nmcli", "device", "wifi", "rescan"], 10.0)
            rc, out, _ = self._run_cmd(
                ["nmcli", "-g", "SSID", "device", "wifi", "list"], 10.0)
            if rc == 0 and any(line.strip() == ssid for line in out.splitlines()):
                self._log(f"[wireless] SSID '{ssid}' now visible in the scan")
                return True
            time.sleep(1.0)
        return False

    def _join_wifi(self, info: dict) -> None:
        ssid = info.get("ssid")
        if not ssid:
            raise AAWirelessError("HU sent WifiInfoResponse without an SSID")
        name = f"aa-car-{int(time.time())}"
        timeout = str(int(self.timeout_ms / 1000) or 30)
        # The HU only brings its AP up after the credential exchange; poll for
        # it rather than connecting blind (which fails with "no network found").
        if not self._wait_for_wifi(ssid, self.wifi_timeout_ms / 1000.0):
            raise AAWirelessError(
                f"AP '{ssid}' never appeared within "
                f"{self.wifi_timeout_ms / 1000.0:.0f}s — is the car's wireless "
                f"AA active? (wlan: {self.wlan_interface})")
        if self.verbose:
            rc, out, _ = self._run_cmd(
                ["nmcli", "-f", "SSID,BSSID,SIGNAL,CHAN", "device", "wifi", "list"], 10.0)
            if rc == 0:
                self._log(f"[wireless] nmcli wifi list:\n{out.rstrip()}")
        cmd = ["nmcli", "-w", timeout, "device", "wifi", "connect", ssid]
        if info.get("passphrase"):
            cmd += ["password", info["passphrase"]]
        bssid = _normalize_mac(info.get("bssid", ""))
        if bssid:
            cmd += ["bssid", bssid]
        cmd += ["name", name, "hidden", "yes"]
        log_cmd = ["<redacted>" if i and cmd[i - 1] == "password" else value
                   for i, value in enumerate(cmd)]
        self._log_verbose(f"[wireless] nmcli cmd: {' '.join(log_cmd)}")

        rc, out, err = -1, "", ""
        for attempt in range(2):
            rc, out, err = self._run_cmd(cmd, timeout_s=45.0)
            if rc == 0:
                break
            self._log(f"[wireless] nmcli join attempt {attempt + 1}/2 failed: "
                      f"{(out or err).strip()}")
            if attempt == 0:
                time.sleep(2.0)
                self._run_cmd(["nmcli", "device", "wifi", "rescan"], 15.0)
        if rc != 0:
            raise AAWirelessError(f"nmcli join failed: {(out or err).strip()}")
        self._nm_profile = name
        self._log(f"[wireless] joined AP '{ssid}' (profile {name})")

        self._run_cmd(["nmcli", "connection", "modify", name,
                       "connection.autoconnect", "no"], 10.0)

        deadline = time.monotonic() + self.timeout_ms / 1000.0
        while time.monotonic() < deadline:
            rc, out, _ = self._run_cmd(
                ["nmcli", "-g", "GENERAL.STATE", "device", "show", self.wlan_interface], 10.0)
            if rc == 0 and "connected" in out.lower():
                rc, out, _ = self._run_cmd(
                    ["nmcli", "-g", "IP4.ADDRESS", "device", "show", self.wlan_interface], 10.0)
                self._log(f"[wireless] WiFi interface {self.wlan_interface} connected"
                          f" (IP: {out.strip() or '?'})")
                return
            time.sleep(0.25)
        raise AAWirelessError(
            f"interface {self.wlan_interface} not connected to '{ssid}'")

    # -- TCP -----------------------------------------------------------------

    def _tcp_connect(self, ip: str, port: int) -> socket.socket:
        sock = socket.create_connection((ip, port), timeout=self.timeout_ms / 1000.0)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return sock

    # -- send/recv/close ---------------------------------------------------

    def send(self, data: bytes) -> int:
        if self._sock is None:
            return AA_ERR_IO
        try:
            _send_all(self._sock, data)
            return len(data)
        except (AAWirelessError, OSError):
            return AA_ERR_IO

    def recv(self, buf_len: int, timeout_ms: int) -> tuple[int, bytes]:
        if self._sock is None:
            return AA_ERR_IO, b""
        prev = self._sock.gettimeout()
        self._sock.settimeout(timeout_ms / 1000.0)
        try:
            data = self._sock.recv(buf_len)
            if not data:
                return AA_ERR_IO, b""
            return len(data), data
        except socket.timeout:
            return AA_ERR_TIMEOUT, b""
        except OSError:
            return AA_ERR_IO, b""
        finally:
            self._sock.settimeout(prev)

    def close(self) -> None:
        if self._bt_agent is not None:
            try:
                self._bt_agent.terminate()
                self._bt_agent.wait(timeout=5)
            except Exception:
                pass
            self._bt_agent = None
        if self._nm_profile:
            self._run_cmd(["nmcli", "connection", "delete", self._nm_profile], 10.0)
            self._nm_profile = ""
        for attr in ("_hfp", "_rfcomm", "_sock"):
            sock = getattr(self, attr, None)
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
                setattr(self, attr, None)
        if self._log_fh is not None:
            try:
                self._log_fh.close()
            except OSError:
                pass
            self._log_fh = None

    def __del__(self) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Self-test / mock-HU (no Bluetooth or WiFi hardware required)
# ---------------------------------------------------------------------------

def _recv_msg(sock: socket.socket) -> tuple[int, bytes]:
    (length, msg_id) = struct.unpack(">HH", _recv_exact(sock, 4))
    return msg_id, _recv_exact(sock, length)


def _mock_hu_side(sock: socket.socket) -> None:
    """Replays the HU side of the 5-stage handshake over a byte pipe,
    opening with a WifiVersionRequest like real head units do."""
    try:
        _send_all(sock, build_rfcomm_frame(
            WIFI_MSG_VERSION_REQUEST,
            encode_wifi_version_request(4, 1, supported_channels=[5200])))
        msg_id, _ = _recv_msg(sock)
        assert msg_id == WIFI_MSG_VERSION_RESPONSE
        _send_all(sock, build_rfcomm_frame(
            WIFI_MSG_START_REQUEST,
            encode_wifi_start_request("10.0.0.1", 5288)))
        msg_id, _ = _recv_msg(sock)
        assert msg_id == WIFI_MSG_START_RESPONSE
        msg_id, _ = _recv_msg(sock)
        assert msg_id == WIFI_MSG_INFO_REQUEST
        _send_all(sock, build_rfcomm_frame(
            WIFI_MSG_INFO_RESPONSE,
            encode_wifi_info_response(ssid="MockHU", bssid="DC:A6:32:E7:5A:FE",
                                      security_mode=1, ap_type=1)))
        msg_id, _ = _recv_msg(sock)
        assert msg_id == WIFI_MSG_CONNECT_STATUS
        log("mock HU: handshake complete")
    except Exception as e:
        log(f"mock HU: error: {e}")
    finally:
        try:
            sock.close()
        except OSError:
            pass


def _self_test() -> int:
    """Byte-level asserts for RFCOMM framing + WiFi proto messages."""
    assert WIFI_STATUS_SUCCESS == 0, "APK sends wire 0 for SUCCESS (index 12 - 12)"
    assert _normalize_mac("dc:a6:32:e7:5a:fe") == "DC:A6:32:E7:5A:FE"
    assert _normalize_mac("DC-A6-32-E7-5A-FE") == "DC:A6:32:E7:5A:FE"
    assert _normalize_mac("") == ""

    from .proto import (decode_bluetooth_auth_data, encode_bluetooth_auth_result,
                        encode_bluetooth_pairing_response)
    # Bluetooth channel: 0x8003 AUTH_DATA "123456" -> decodes; 0x8004 status 0.
    auth_hex = bytes([0x0a, 6]) + b"123456"
    assert decode_bluetooth_auth_data(auth_hex) == "123456"
    assert encode_bluetooth_auth_result(0) == b"\x08\x00"
    assert encode_bluetooth_pairing_response(status=0, already_paired=True) == b"\x08\x00\x10\x01"

    start_req = bytes.fromhex("0a0831302e302e302e3110a829")
    assert decode_wifi_start_request(start_req) == ("10.0.0.1", 5288)
    assert encode_wifi_start_response("10.0.0.1", 5288, 1) == bytes.fromhex(
        "0a0831302e302e302e3110a8291801")
    assert encode_wifi_info_request() == b""
    assert encode_wifi_connect_status(1) == b"\x08\x01"
    # Wire: ssid=1, passphrase=2, bssid=3 (not bssid=2/passphrase=3 as the
    # stale generated proto has).
    info_bytes = bytes.fromhex(
        "0a084f70656e4175746f12067365637265741a1144433a41363a33323a45373a35413a464520082801")
    info = decode_wifi_info_response(info_bytes)
    assert info["ssid"] == "OpenAuto" and info["bssid"] == "DC:A6:32:E7:5A:FE"
    assert info["passphrase"] == "secret" and info["security_mode"] == 8
    roundtrip = decode_wifi_info_response(
        encode_wifi_info_response(ssid="OpenAuto", bssid="DC:A6:32:E7:5A:FE",
                                  passphrase="secret", security_mode=8, ap_type=1))
    assert roundtrip["bssid"] == "DC:A6:32:E7:5A:FE"
    assert roundtrip["passphrase"] == "secret"

    frame = build_rfcomm_frame(WIFI_MSG_START_RESPONSE,
                               encode_wifi_start_response("10.0.0.1", 5288, 1))
    msg_id, payload, rest = parse_rfcomm_frame(frame)
    assert msg_id == WIFI_MSG_START_RESPONSE
    assert payload == encode_wifi_start_response("10.0.0.1", 5288, 1)
    assert rest == b""

    sdp = 'Service RecHandle: 0x10000\nService Class ID List:\n  "Android Auto" (0x4de17a00)\nProtocol Descriptor List:\n  "L2CAP" (0x0100)\n  "RFCOMM" (0x0003)\n    Channel: 8\n'
    assert find_rfcomm_channel(sdp, "4de17a00") == 8
    assert find_rfcomm_channel(sdp, "111f") is None
    sdp_short = 'Service RecHandle: 0x10005\nService Class ID List:\n  "Unknown" (0x4de17a00)\n  "Android Auto" (0x0100)\nProtocol Descriptor List:\n  "L2CAP" (0x0100)\n  "RFCOMM" (0x0003)\n    Channel: 12\n'
    assert find_rfcomm_channel(sdp_short, AA_SERVICE_UUID_SHORT) == 12

    sdp_sppaawl0 = ('Service Name: SPPAAWL0\n'
                    'Service RecHandle: 0x10009\n'
                    'Service Class ID List:\n'
                    '  UUID 128: 4de17a00-52cb-11e6-bdf4-0800200c9a66\n'
                    'Protocol Descriptor List:\n'
                    '  "L2CAP" (0x0100)\n'
                    '  "RFCOMM" (0x0003)\n'
                    '    Channel: 3\n')
    assert find_rfcomm_channel(sdp_sppaawl0, AA_SERVICE_UUID_SHORT) == 3

    log("self-test: all assertions passed")
    return 0


def _mock_hu(log_file: str = "") -> int:
    """End-to-end handshake over a socketpair (no BT/WiFi needed)."""
    client, server = socket.socketpair()
    thread = threading.Thread(target=_mock_hu_side, args=(server,), daemon=True)
    thread.start()

    def join_wifi(info: dict) -> None:
        assert info["ssid"] == "MockHU", info
        log(f"mock join: ssid={info['ssid']} bssid={info['bssid']}")

    transport = WirelessTransport(bt_address="00:00:00:00:00:00",
                                  wlan_interface="wlp3s0", no_hfp=True,
                                  timeout_ms=3000, verbose=True,
                                  log_file=log_file)
    try:
        ip, port = transport._do_handshake(client, join_wifi)
        assert (ip, port) == ("10.0.0.1", 5288)
        log(f"client handshake OK -> {ip}:{port}")
    finally:
        client.close()
        thread.join(5)
        transport.close()
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    log_file = ""
    if "--log-file" in args:
        i = args.index("--log-file")
        if i + 1 < len(args):
            log_file = args[i + 1]
    if "--mock-hu" in args:
        sys.exit(_mock_hu(log_file))
    sys.exit(_self_test())

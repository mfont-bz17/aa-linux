"""AA protocol state machine — translated from protocol.c."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import List, Optional

from . import audio as _audio_mod
from . import video as _video_mod
from .audio import (
    _audio_latency,
    _make_audio_codec_config_payload,
    _make_audio_frame_payload,
    _stop_ffmpeg_audio,
)
from .video import (
    _frame_latency,
    _make_codec_config_payload,
    _make_video_frame_payload,
    _stop_ffmpeg,
)
from .util import LatencyStats, log, time_ms

from .constants import (
    AA_CHANNEL_CONTROL,
    AA_CHANNEL_TYPE_AV,
    AA_CHANNEL_TYPE_AV_INPUT,
    AA_CHANNEL_TYPE_BLUETOOTH,
    AA_CHANNEL_TYPE_CAR_CONTROL,
    AA_CHANNEL_TYPE_INPUT,
    AA_CHANNEL_TYPE_MEDIA_BROWSER,
    AA_CHANNEL_TYPE_MEDIA_INFO,
    AA_CHANNEL_TYPE_NAVIGATION,
    AA_CHANNEL_TYPE_NONE,
    AA_CHANNEL_TYPE_NOTIFICATION,
    AA_CHANNEL_TYPE_PHONE_STATUS,
    AA_CHANNEL_TYPE_RADIO,
    AA_CHANNEL_TYPE_SENSOR,
    AA_CHANNEL_TYPE_VENDOR_EXT,
    AA_CHANNEL_TYPE_WIFI,
    AA_ERR,
    AA_ERR_TIMEOUT,
    AA_FLAG_CONTROL,
    AA_FLAG_ENCRYPTED,
    AA_FRAME_BULK,
    AA_FRAME_FIRST,
    AA_FRAME_LAST,
    AA_FRAME_MIDDLE,
    AA_MAX_CHANNELS,
    AA_MAX_FRAME_PAYLOAD,
    AA_MSG_AV_MEDIA_ACK,
    AA_MSG_AV_MEDIA_INDICATION,
    AA_MSG_AV_MEDIA_WITH_TS,
    AA_MSG_AV_SETUP_REQUEST,
    AA_MSG_AV_SETUP_RESPONSE,
    AA_MSG_AV_START_INDICATION,
    AA_MSG_AV_STOP_INDICATION,
    AA_MSG_AUTH_COMPLETE,
    AA_MSG_AUDIO_FOCUS_REQUEST,
    AA_MSG_AUDIO_FOCUS_RESPONSE,
    AA_MSG_BT_AUTH_DATA,
    AA_MSG_BT_AUTH_RESULT,
    AA_MSG_BT_PAIRING_REQUEST,
    AA_MSG_BT_PAIRING_RESPONSE,
    AA_MSG_BYEBYE_REQUEST,
    AA_MSG_BYEBYE_RESPONSE,
    AA_MSG_CHANNEL_OPEN_REQUEST,
    AA_MSG_CHANNEL_OPEN_RESPONSE,
    AA_MSG_INPUT_EVENT_INDICATION,
    AA_MSG_PING_REQUEST,
    AA_MSG_PING_RESPONSE,
    AA_MSG_SD_REQUEST,
    AA_MSG_SD_RESPONSE,
    AA_MSG_SENSOR_ERROR,
    AA_MSG_SENSOR_EVENT_INDICATION,
    AA_MSG_SENSOR_REQUEST,
    AA_MSG_SENSOR_START_RESPONSE,
    AA_MSG_SSL_HANDSHAKE,
    AA_MSG_VERSION_REQUEST,
    AA_MSG_VERSION_RESPONSE,
    AA_MSG_VIDEO_FOCUS_INDICATION,
    AA_MSG_VIDEO_FOCUS_REQUEST,
    AA_OK,
    AA_PROTOCOL_VERSION_MAJOR,
    AA_PROTOCOL_VERSION_MINOR,
    AA_RECV_TIMEOUT_MS,
    AA_SHUTDOWN_RECV_TIMEOUT_MS,
    AUDIO_FOCUS_TYPE_GAIN,
    channel_name,
    channel_type_name,
)
from .crypto import AACrypto
from .frame import frame_read, frame_write
from .sensor import SensorBackend
from .x11_input import X11InputInjector

# Media codec types from protobuf enum
MEDIA_CODEC_AUDIO_AAC_LC = 2
MEDIA_CODEC_VIDEO_H264_BP = 3

# AVStreamType enum (SD response av_channel.stream_type)
AV_STREAM_TYPE_AUDIO = 1
AV_STREAM_TYPE_VIDEO = 3

# AudioType enum (SD response av_channel.audio_type)
AUDIO_TYPE_SPEECH = 1
AUDIO_TYPE_SYSTEM = 2
AUDIO_TYPE_MEDIA = 3

# AVChannelSetupStatus enum
AV_SETUP_STATUS_OK = 2

# Video streaming timing
VIDEO_FRAME_INTERVAL_MS = 33  # ~30 fps

# Audio streaming timing (AAC-LC: 1024 samples/frame @ 48 kHz ~= 21.3 ms)
AUDIO_FRAME_INTERVAL_MS = 21

from .proto import (
    SensorEventIndication,
    InputEventIndication,
    decode_auth_complete,
    decode_av_channel_setup_response,
    decode_byebye_request,
    decode_channel_open_request,
    decode_channel_open_response,
    decode_ping_request,
    decode_sensor_error,
    decode_sensor_start_response,
    decode_service_discovery_response,
    decode_version_request,
    encode_av_channel_setup_request,
    encode_av_channel_start_indication,
    encode_audio_focus_request,
    encode_byebye_request,
    encode_byebye_response,
    encode_channel_open_request,
    encode_channel_open_response,
    encode_ping_response,
    encode_sensor_request,
    encode_service_discovery_request,
    encode_version_response,
    decode_audio_focus_response,
    decode_bluetooth_auth_data,
    decode_bluetooth_pairing_request,
    encode_bluetooth_auth_result,
    encode_bluetooth_pairing_response,
)


class AAState(IntEnum):
    CONNECT = 0
    VERSION_RECV = 1
    VERSION_SEND = 2
    TLS_HANDSHAKE = 3
    AUTH_RECV = 4
    SD_SEND = 5
    SD_RECV = 6
    CHANNEL_OPEN = 7
    READY = 8
    SHUTDOWN = 9
    DONE = 10
    ERROR = 11


STATE_NAMES = {s: s.name for s in AAState}

_input_latency = LatencyStats(window=200, name="Input")

_AUDIO_KINDS = ("audio_media", "audio_speech", "audio_sys", "audio")

_AUDIO_KIND_BY_TYPE = {
    AUDIO_TYPE_MEDIA: "audio_media",
    AUDIO_TYPE_SPEECH: "audio_speech",
    AUDIO_TYPE_SYSTEM: "audio_sys",
}

_CONTROL_HANDLERS = {
    AA_MSG_AUTH_COMPLETE: "_handle_auth_complete",
    AA_MSG_SD_RESPONSE: "_handle_service_discovery_response",
    AA_MSG_PING_REQUEST: "_handle_ping_request",
    AA_MSG_PING_RESPONSE: "_handle_ping_response",
    AA_MSG_BYEBYE_REQUEST: "_handle_byebye_request",
    AA_MSG_BYEBYE_RESPONSE: "_handle_byebye_response",
    AA_MSG_CHANNEL_OPEN_REQUEST: "_handle_channel_open_request_from_hu",
    AA_MSG_CHANNEL_OPEN_RESPONSE: "_handle_channel_open_response_from_hu",
    AA_MSG_AUDIO_FOCUS_RESPONSE: "_handle_audio_focus_response",
}


@dataclass
class VideoStreamState:
    channel: int = -1
    streaming: bool = False
    config_sent: bool = False
    capture_codec_sent: bool = False
    next_ts_ms: int = 0
    frame_count: int = 0
    fps_log_ms: int = 0
    bytes_sent: int = 0
    max_unacked: int = 0
    unacked: int = 0
    ticks: int = 0
    empty_count: int = 0
    flowctl_count: int = 0


@dataclass
class AudioStreamState:
    channel: int = -1
    streaming: bool = False
    config_sent: bool = False
    focus_requested: bool = False
    focus_granted: bool = False
    focus_request_ts_ms: int = 0
    focus_warned: bool = False
    next_ts_ms: int = 0
    frame_count: int = 0
    fps_log_ms: int = 0
    bytes_sent: int = 0
    max_unacked: int = 0
    unacked: int = 0
    ticks: int = 0
    empty_count: int = 0
    flowctl_count: int = 0


def _extract_video_resolution(ch) -> int:
    """Return the HU's advertised VideoResolution enum for a channel, or 0."""
    if not ch.HasField("av_channel"):
        return 0
    for vc in ch.av_channel.video_configs:
        if vc.HasField("video_resolution") and vc.video_resolution:
            return vc.video_resolution
    return 0


def _extract_video_margins(ch) -> tuple[int, int]:
    """Return the HU's advertised (margin_width, margin_height), or (0, 0)."""
    if not ch.HasField("av_channel"):
        return 0, 0
    for vc in ch.av_channel.video_configs:
        if vc.HasField("margin_width") or vc.HasField("margin_height"):
            return vc.margin_width, vc.margin_height
    return 0, 0


def _extract_video_fps(ch) -> int:
    """Return the HU's advertised VideoFPS enum for a channel, or 0."""
    if not ch.HasField("av_channel"):
        return 0
    for vc in ch.av_channel.video_configs:
        if vc.HasField("video_fps") and vc.video_fps:
            return vc.video_fps
    return 0


def classify_channel(ch) -> tuple[int, str]:
    """Map a ChannelDescriptor to (channel_type, kind)."""
    ch_type = AA_CHANNEL_TYPE_NONE
    kind = "other"
    if ch.HasField("av_channel"):
        ch_type = AA_CHANNEL_TYPE_AV
        av = ch.av_channel
        # DHU video sinks do not set stream_type — distinguish audio vs video
        # by audio_type presence.
        if av.audio_type in (AUDIO_TYPE_SPEECH, AUDIO_TYPE_SYSTEM, AUDIO_TYPE_MEDIA):
            kind = _AUDIO_KIND_BY_TYPE.get(av.audio_type, "audio")
        elif av.stream_type == AV_STREAM_TYPE_AUDIO:
            kind = _AUDIO_KIND_BY_TYPE.get(av.audio_type, "audio")
        else:
            kind = "video"
    elif ch.HasField("sensor_channel"):
        ch_type = AA_CHANNEL_TYPE_SENSOR
        kind = "sensor"
    elif ch.HasField("input_channel"):
        ch_type = AA_CHANNEL_TYPE_INPUT
        kind = "input"
    elif ch.HasField("av_input_channel"):
        ch_type = AA_CHANNEL_TYPE_AV_INPUT
        kind = "mic"
    elif ch.HasField("bluetooth_channel"):
        ch_type = AA_CHANNEL_TYPE_BLUETOOTH
        kind = "bluetooth"
    elif ch.HasField("radio_channel"):
        ch_type = AA_CHANNEL_TYPE_RADIO
    elif ch.HasField("navigation_channel"):
        ch_type = AA_CHANNEL_TYPE_NAVIGATION
    elif ch.HasField("media_info_channel"):
        ch_type = AA_CHANNEL_TYPE_MEDIA_INFO
    elif ch.HasField("phone_status_channel"):
        ch_type = AA_CHANNEL_TYPE_PHONE_STATUS
    elif ch.HasField("media_browser_channel"):
        ch_type = AA_CHANNEL_TYPE_MEDIA_BROWSER
    elif ch.HasField("vendor_extension_channel"):
        ch_type = AA_CHANNEL_TYPE_VENDOR_EXT
    elif ch.HasField("notification_channel"):
        ch_type = AA_CHANNEL_TYPE_NOTIFICATION
    elif ch.HasField("wifi_channel"):
        ch_type = AA_CHANNEL_TYPE_WIFI
    elif ch.HasField("car_control_channel"):
        ch_type = AA_CHANNEL_TYPE_CAR_CONTROL
    return ch_type, kind


class AAContext:
    """Main protocol context — state machine + message handlers."""

    def __init__(self, transport, cert_path: str, key_path: str, verbose: bool = False,
                 sensor_backend: Optional[SensorBackend] = None):
        self.transport = transport
        self.cert_path = cert_path
        self.key_path = key_path
        self.verbose = verbose
        self.sensor_backend = sensor_backend or SensorBackend()
        self.state = AAState.CONNECT
        self.last_error = 0

        self.peer_major = 0
        self.peer_minor = 0

        self.crypto: Optional[AACrypto] = None

        self.sd_delay_until_ms = 0

        self.channel_open = [False] * AA_MAX_CHANNELS
        self.channel_session_id = [0] * AA_MAX_CHANNELS

        self.pending_channels: List[int] = []
        self.pending_channel_idx = 0

        self.hu_channels = []  # list of (channel_id, channel_type)
        self.channel_kinds = {}  # channel_id -> kind (video/audio_media/.../other)
        self.av_session = 0

        self.video = VideoStreamState()
        self.audio = AudioStreamState()

        self.sensor_channels = []
        self.sensor_subscribed = {}
        self.next_sensor_ts_ms = 0
        self.x11_injector = X11InputInjector(verbose=self.verbose)

    def destroy(self) -> None:
        _stop_ffmpeg()
        _stop_ffmpeg_audio()
        if self.x11_injector:
            self.x11_injector.close()
        if self.crypto:
            self.crypto.destroy()
        if self.transport:
            self.transport.close()

    def get_state(self) -> AAState:
        return self.state

    # ------------------------------------------------------------------
    # Raw send helpers
    # ------------------------------------------------------------------

    def _send_raw(self, channel: int, flags: int, data: bytes, total_size: int = 0) -> int:
        if self.verbose:
            log(f"send_raw: ch={channel} flags=0x{flags:02X} len={len(data)}")
            if len(data) > 48:
                log(f"  {data[:48].hex()}...")
            else:
                log(f"  {data.hex()}")
        return frame_write(self.transport, channel, flags, data, len(data), total_size)

    def _send_encrypted(self, channel: int, plain: bytes, extra_flags: int = 0) -> int:
        """Encrypt and send a channel message, fragmenting large messages.

        Messages with a plaintext length >= AA_MAX_FRAME_PAYLOAD (0x4000) are
        split into fragments of that size; each fragment is encrypted and sent
        as its own frame (FIRST -> MIDDLE* -> LAST). The FIRST frame carries an
        extended header with the total plaintext length. Every fragmented
        message ends with a LAST frame — including an empty one when the size
        is an exact multiple of the fragment size — because the receiver
        reassembles on frame type, not on total_size.
        """
        if len(plain) < AA_MAX_FRAME_PAYLOAD:
            rc, cipher = self.crypto.write_encrypted(plain)
            if rc != AA_OK:
                return rc
            if not cipher:
                return AA_OK
            flags = AA_FLAG_ENCRYPTED | AA_FRAME_BULK | extra_flags
            return self._send_raw(channel, flags, cipher)

        offset = 0
        remaining = len(plain)
        is_first = True
        while True:
            size = min(remaining, AA_MAX_FRAME_PAYLOAD)
            chunk = plain[offset:offset + size]
            rc, cipher = self.crypto.write_encrypted(chunk)
            if rc != AA_OK:
                return rc

            if is_first:
                frame_type = AA_FRAME_FIRST
                is_first = False
            elif remaining - size > 0:
                frame_type = AA_FRAME_MIDDLE
            else:
                frame_type = AA_FRAME_LAST

            flags = AA_FLAG_ENCRYPTED | frame_type | extra_flags
            total_size = len(plain) if frame_type == AA_FRAME_FIRST else 0
            rc = self._send_raw(channel, flags, cipher, total_size)
            if rc != AA_OK:
                return rc

            offset += size
            remaining -= size
            if frame_type == AA_FRAME_LAST:
                return AA_OK

    def _send_control_plain(self, msg_id: int, payload: bytes) -> int:
        buf = msg_id.to_bytes(2, "big") + payload
        return self._send_raw(AA_CHANNEL_CONTROL, AA_FRAME_BULK, buf)

    def _send_control_encrypted(self, msg_id: int, payload: bytes, extra_flags: int = 0) -> int:
        plain = msg_id.to_bytes(2, "big") + payload
        if self.verbose:
            log(f"Sending msg 0x{msg_id:04X} on ch0: plaintext ({len(plain)} bytes)")
        return self._send_encrypted(AA_CHANNEL_CONTROL, plain, extra_flags)

    def _send_channel_encrypted(self, channel: int, msg_id: int, payload: bytes) -> int:
        plain = msg_id.to_bytes(2, "big") + payload
        return self._send_encrypted(channel, plain)

    def _send_channel_control_encrypted(self, channel: int, msg_id: int, payload: bytes) -> int:
        """Send an encrypted control message on a specific (non-zero) channel.

        The DHU routes any frame with the CONTROL flag set on ANY channel to
        MessageRouter::routeChannelControlMsg, which validates channel state
        using the FRAME header channel (not the protobuf field). Control
        messages bypass the Channel-object requirement, so this works even
        before the channel is opened.
        """
        plain = msg_id.to_bytes(2, "big") + payload
        if self.verbose:
            log(f"Sending msg 0x{msg_id:04X} on ch{channel} (control): plaintext ({len(plain)} bytes)")
        return self._send_encrypted(channel, plain, AA_FLAG_CONTROL)

    # ------------------------------------------------------------------
    # Message handlers
    # ------------------------------------------------------------------

    def _handle_version_request(self, data: bytes) -> int:
        major, minor = decode_version_request(data)
        self.peer_major = major
        self.peer_minor = minor
        log(f"HU version: {major}.{minor}")

        resp = encode_version_response(
            AA_PROTOCOL_VERSION_MAJOR, AA_PROTOCOL_VERSION_MINOR, 0
        )
        rc = self._send_control_plain(AA_MSG_VERSION_RESPONSE, resp)
        if rc != AA_OK:
            return rc

        self.state = AAState.TLS_HANDSHAKE
        return AA_OK

    def _handle_tls_frame(self, data: bytes) -> int:
        rc = self.crypto.feed_recv(data)
        if rc < 0:
            return rc

        rc = self.crypto.accept()
        if rc != AA_OK:
            return rc

        out = self.crypto.drain_send()
        if out:
            tls_frame = b"\x00\x03" + out
            rc = self._send_raw(AA_CHANNEL_CONTROL, AA_FRAME_BULK, tls_frame)
            if rc != AA_OK:
                return rc

        if self.crypto.handshake_done and self.state == AAState.TLS_HANDSHAKE:
            self.state = AAState.AUTH_RECV
            log("Waiting for auth complete...")

        return AA_OK

    def _handle_auth_complete(self, data: bytes) -> int:
        status = decode_auth_complete(data)
        log(f"Auth complete: status={status} — waiting 200ms before SD request")
        self.sd_delay_until_ms = time_ms() + 200
        self.state = AAState.SD_SEND
        return AA_OK

    def _send_service_discovery_request(self) -> int:
        payload = encode_service_discovery_request("AA Linux")
        rc = self._send_control_encrypted(AA_MSG_SD_REQUEST, payload)
        if rc != AA_OK:
            return rc
        log("Sent ServiceDiscoveryRequest")
        self.state = AAState.SD_RECV
        return AA_OK

    def _handle_service_discovery_response(self, data: bytes) -> int:
        log(f"Service Discovery Response ({len(data)} bytes):")

        resp = decode_service_discovery_response(data)
        log(resp)
        log(f"  Head unit: {resp.head_unit_name or '?'}")
        log(f"  n_channels={len(resp.channels)} (max={AA_MAX_CHANNELS})")

        self.hu_channels = []
        self.channel_kinds = {}
        for i, ch in enumerate(resp.channels):
            if ch.channel_id:
                ch_type, kind = classify_channel(ch)
                if kind == "sensor":
                    self.sensor_channels.append((ch.channel_id, ch.sensor_channel))
                elif kind == "video":
                    _video_mod.set_video_geometry(
                        _extract_video_resolution(ch),
                        *_extract_video_margins(ch),
                        video_fps=_extract_video_fps(ch),
                    )

                self.hu_channels.append((ch.channel_id, ch_type))
                self.channel_kinds[ch.channel_id] = kind
                log(f"  [{i}] id={ch.channel_id} type={ch_type} ({channel_type_name(ch_type)}) kind={kind}")

        log(f"Parsed {len(self.hu_channels)} channels from HU")

        self.pending_channels = []
        for ch_id, kind in sorted(self.channel_kinds.items()):
            if kind == "video":
                self.pending_channels.append(ch_id)
                log(f"  Queued: channel={ch_id} ({kind})")
                break
        for ch_id, kind in sorted(self.channel_kinds.items()):
            if kind == "sensor":
                self.pending_channels.append(ch_id)
                log(f"  Queued: channel={ch_id} ({kind})")
        for ch_id, kind in sorted(self.channel_kinds.items()):
            if kind == "input":
                self.pending_channels.append(ch_id)
                log(f"  Queued: channel={ch_id} ({kind})")

        if _audio_mod._AUDIO_FILE_SPEC:
            for ch_id, kind in sorted(self.channel_kinds.items()):
                continue
                if kind == "audio_media":
                    self.pending_channels.append(ch_id)
                    log(f"  Queued: channel={ch_id} ({kind})")

        if not self.pending_channels:
            log("No channels to open. Entering READY state.")
            self.state = AAState.READY
            return AA_OK

        log(f"Opening {len(self.pending_channels)} channels sequentially...")
        self.state = AAState.CHANNEL_OPEN
        return self._send_next_channel_open_request()

    def _send_next_channel_open_request(self) -> int:
        while self.pending_channel_idx < len(self.pending_channels):
            ch_id = self.pending_channels[self.pending_channel_idx]

            if not (0 <= ch_id < AA_MAX_CHANNELS):
                log(f"Skipping out-of-range channel id {ch_id}")
                self.pending_channel_idx += 1
                continue

            if self.channel_open[ch_id]:
                self.pending_channel_idx += 1
                continue

            # DHU validates the FRAME header channel against its free-channel
            # table and looks up protobuf field 2 as the service type index.
            # Both must be the advertised channel_id, and the request must be
            # sent on the target channel itself with the control flag set.
            payload = encode_channel_open_request(0, ch_id)
            rc = self._send_channel_control_encrypted(
                ch_id, AA_MSG_CHANNEL_OPEN_REQUEST, payload
            )
            if rc != AA_OK:
                log(f"Failed to send ChannelOpenRequest for ch {ch_id}")
                self.pending_channel_idx += 1
                continue

            log(f">> ChannelOpenRequest: channel={ch_id} ({self.channel_kinds.get(ch_id, '?')})")
            return AA_OK

        log(f"All {len(self.pending_channels)} ChannelOpenRequest(s) sent. Entering READY state.")
        self.pending_channel_idx = 0
        self.pending_channels = []
        self.state = AAState.READY
        return AA_OK

    def _handle_channel_open_request_from_hu(self, data: bytes) -> int:
        priority, channel_id = decode_channel_open_request(data)
        log(f"ChannelOpenRequest: channel={channel_id} ({channel_name(channel_id)}) priority={priority}")

        if 0 <= channel_id < AA_MAX_CHANNELS:
            self.channel_open[channel_id] = True
            self.channel_session_id[channel_id] = channel_id

        payload = encode_channel_open_response(0)
        rc = self._send_control_encrypted(
            AA_MSG_CHANNEL_OPEN_RESPONSE, payload, AA_FLAG_CONTROL
        )
        if rc != AA_OK:
            return rc

        log(f"ChannelOpenResponse: OK for channel {channel_id}")
        return AA_OK

    def _handle_channel_open_response_from_hu(self, data: bytes) -> int:
        status = decode_channel_open_response(data)

        ch_id = -1
        if self.pending_channel_idx < len(self.pending_channels):
            ch_id = self.pending_channels[self.pending_channel_idx]

        log(f"<< ChannelOpenResponse: channel={ch_id} ({channel_name(ch_id) if ch_id >= 0 else '?'}) status={status}")

        if status == 0 and ch_id >= 0:
            self.channel_open[ch_id] = True
            self.channel_session_id[ch_id] = ch_id
            kind = self.channel_kinds.get(ch_id, "other")
            log(f"  Channel {ch_id} ({kind}) opened successfully.")

            # NOTE: the DHU has no ChannelOpenAck — msg 0x8002 on its AV
            # channels is gal::Stop. Send AVChannelSetupRequest directly.
            if kind == "video":
                setup = encode_av_channel_setup_request(MEDIA_CODEC_VIDEO_H264_BP)
                self._send_channel_encrypted(ch_id, AA_MSG_AV_SETUP_REQUEST, setup)
                log(f"  >> AVChannelSetupRequest sent on video channel (codec=H264_BP)")
            elif kind in _AUDIO_KINDS:
                setup = encode_av_channel_setup_request(MEDIA_CODEC_AUDIO_AAC_LC)
                self._send_channel_encrypted(ch_id, AA_MSG_AV_SETUP_REQUEST, setup)
                log(f"  >> AVChannelSetupRequest sent on audio channel {ch_id} (codec=AAC_LC)")
            elif kind == "sensor":
                self._subscribe_sensors(ch_id)
        elif status != 0:
            log(f"  Channel {ch_id} ({channel_name(ch_id) if ch_id >= 0 else '?'}) REJECTED: status={status}")

        self.pending_channel_idx += 1
        return self._send_next_channel_open_request()

    def _handle_ping_request(self, data: bytes) -> int:
        timestamp = decode_ping_request(data)
        log(f"<< Received ping request: ts={timestamp}")

        resp = encode_ping_response(timestamp)
        return self._send_control_encrypted(AA_MSG_PING_RESPONSE, resp)

    def _handle_ping_response(self, data: bytes) -> int:
        log("<< Received ping response")
        return AA_OK

    def _handle_audio_focus_response(self, data: bytes) -> int:
        state, granted = decode_audio_focus_response(data)
        self.audio.focus_granted = granted
        log(f"<< AudioFocusResponse: state={state} granted={granted}")
        if not granted and self.audio.focus_requested:
            log("  Audio focus NOT granted — audio playback remains paused")
        return AA_OK

    def _handle_byebye_request(self, data: bytes) -> int:
        reason = decode_byebye_request(data)
        log(f"<< ByeBye request: reason={reason}")

        resp = encode_byebye_response()
        self._send_control_encrypted(AA_MSG_BYEBYE_RESPONSE, resp)
        self.state = AAState.DONE
        return AA_OK

    def _handle_byebye_response(self, data: bytes) -> int:
        log("<< ByeBye response received")
        if self.state == AAState.SHUTDOWN:
            self.state = AAState.DONE
        return AA_OK

    def _handle_encrypted_control(self, msg_id: int, data: bytes) -> int:
        handler = _CONTROL_HANDLERS.get(msg_id)
        if handler is None:
            if self.verbose:
                log(f"Unhandled encrypted msg 0x{msg_id:04X}")
            return AA_OK
        return getattr(self, handler)(data)

    def _handle_plaintext_control(self, msg_id: int, data: bytes) -> int:
        if msg_id == AA_MSG_VERSION_REQUEST:
            return self._handle_version_request(data)
        if msg_id == AA_MSG_SSL_HANDSHAKE:
            return self._handle_tls_frame(data)
        handler = _CONTROL_HANDLERS.get(msg_id)
        if handler is None:
            if self.verbose:
                log(f"Unhandled plaintext msg 0x{msg_id:04X}")
            return AA_OK
        return getattr(self, handler)(data)

    def _handle_channel_message(self, channel: int, msg_id: int, data: bytes) -> int:
        if self.verbose:
            log(f"Processing channel {channel} ({channel_name(channel)}) msg=0x{msg_id:04X} len={len(data)}")

        kind = self.channel_kinds.get(channel, "other")

        if kind == "video":
            if msg_id == AA_MSG_AV_START_INDICATION:
                log("Video: AV start indication")
            elif msg_id == AA_MSG_AV_STOP_INDICATION:
                log("Video: AV stop indication")
            elif msg_id == AA_MSG_AV_SETUP_RESPONSE:
                status, max_unacked, configs = decode_av_channel_setup_response(data)
                log(f"Video: setup response status={status} max_unacked={max_unacked} configs={configs}")
                if status == AV_SETUP_STATUS_OK:
                    self.video.max_unacked = max_unacked
                    self.video.unacked = 0
                    self._send_av_start(channel, configs)
            elif msg_id == AA_MSG_VIDEO_FOCUS_REQUEST:
                log("Video: focus request")
            elif msg_id == AA_MSG_VIDEO_FOCUS_INDICATION:
                log("Video: focus indication (HU gained/lost focus)")
            elif msg_id == AA_MSG_AV_MEDIA_ACK:
                self.video.unacked = max(0, self.video.unacked - 1)
                if self.verbose:
                    log(f"Video: media ack, unacked now {self.video.unacked}")
            elif self.verbose:
                log(f"Video: unhandled msg 0x{msg_id:04X}")
        elif kind in _AUDIO_KINDS:
            if msg_id == AA_MSG_AV_START_INDICATION:
                log(f"Audio ch{channel}: AV start indication")
            elif msg_id == AA_MSG_AV_STOP_INDICATION:
                log(f"Audio ch{channel}: AV stop indication")
            elif msg_id == AA_MSG_AV_SETUP_RESPONSE:
                status, max_unacked, configs = decode_av_channel_setup_response(data)
                log(f"Audio ch{channel}: setup response status={status} max_unacked={max_unacked} configs={configs}")
                if status == AV_SETUP_STATUS_OK:
                    self.audio.max_unacked = max_unacked
                    self.audio.unacked = 0
                    self._send_av_start(channel, configs)
            elif msg_id == AA_MSG_AV_MEDIA_ACK:
                self.audio.unacked = max(0, self.audio.unacked - 1)
                if self.verbose:
                    log(f"Audio ch{channel}: media ack, unacked now {self.audio.unacked}")
            elif self.verbose:
                log(f"Audio ch{channel}: unhandled msg 0x{msg_id:04X}")
        elif kind == "input":
            if msg_id == AA_MSG_INPUT_EVENT_INDICATION:
                t0 = time_ms()
                ev = InputEventIndication()
                ev.ParseFromString(data)
                if ev.HasField("touch_event"):
                    touch = ev.touch_event
                    for loc in touch.touch_location:
                        self.x11_injector.inject_touch(loc.x, loc.y, touch.touch_action)
                if ev.HasField("relative_input_event"):
                    for re in ev.relative_input_event.relative_input_events:
                        self.x11_injector.inject_scroll(re.delta)
                _input_latency.add(time_ms() - t0)
                if self.verbose:
                    log(f"Input: event on ch{channel} latency={time_ms()-t0:.1f}ms")
            elif self.verbose:
                log(f"Input: msg 0x{msg_id:04X} len={len(data)}")
        elif kind == "sensor":
            if msg_id == AA_MSG_SENSOR_START_RESPONSE:
                status = decode_sensor_start_response(data)
                log(f"Sensor: start response status={status} on ch{channel}")
                self.sensor_backend.on_start_response(channel, status)
            elif msg_id == AA_MSG_SENSOR_EVENT_INDICATION:
                ev = SensorEventIndication()
                ev.ParseFromString(data)
                self.sensor_backend.on_event(channel, ev)
            elif msg_id == AA_MSG_SENSOR_ERROR:
                st, err = decode_sensor_error(data)
                log(f"Sensor: error sensor_type={st} error={err} on ch{channel}")
                self.sensor_backend.on_error(channel, st, err)
            elif self.verbose:
                log(f"Sensor: msg 0x{msg_id:04X} len={len(data)}")
        elif kind == "mic":
            if self.verbose:
                log(f"Mic: msg 0x{msg_id:04X} len={len(data)}")
        elif kind == "bluetooth":
            if msg_id == AA_MSG_BT_PAIRING_REQUEST:
                req = decode_bluetooth_pairing_request(data)
                log(f"BT ch{channel}: pairing request method={req['pairing_method']} "
                    f"phone={req['phone_name']!r}")
                self._send_channel_encrypted(
                    channel, AA_MSG_BT_PAIRING_RESPONSE,
                    encode_bluetooth_pairing_response(status=0, already_paired=True))
                log(f"  >> BluetoothPairingResponse status=0 already_paired=true")
            elif msg_id == AA_MSG_BT_AUTH_DATA:
                auth = decode_bluetooth_auth_data(data)
                # Log hex-encoded, like the real phone's handler does.
                log(f"BT ch{channel}: authentication data "
                    f"(hex={auth.encode('utf-8', 'replace').hex() or '(empty)'})")
                self._send_channel_encrypted(
                    channel, AA_MSG_BT_AUTH_RESULT, encode_bluetooth_auth_result(status=0))
                log(f"  >> BluetoothAuthenticationResult status=0 (success)")
            elif self.verbose:
                log(f"BT ch{channel}: unhandled msg 0x{msg_id:04X} len={len(data)}")
        else:
            log(f"Channel {channel} ({channel_name(channel)}): msg 0x{msg_id:04X} len={len(data)}")
            if data:
                log(f"  data: {data[:128].hex()}")

        return AA_OK

    def _send_av_start(self, channel: int, configs) -> int:
        """Send AVChannelStartIndication (msg 0x8001) to begin streaming.

        On the DHU, the phone drives the AV flow: Setup (0x8000) -> Config
        (0x8003) -> Start (0x8001) with a session id and a config index.
        For the video channel, immediately send the H.264 codec config and
        begin streaming frames.
        """
        self.av_session += 1
        config = configs[0] if configs else 0
        payload = encode_av_channel_start_indication(self.av_session, config)
        rc = self._send_channel_encrypted(channel, AA_MSG_AV_START_INDICATION, payload)
        log(f"  >> AVChannelStartIndication sent on channel {channel} "
            f"(session={self.av_session} config={config})")
        if rc != AA_OK:
            return rc

        kind = self.channel_kinds.get(channel, "other")
        if kind == "video":
            self.video.channel = channel
            self.video.config_sent = False
            self.video.streaming = True
            # Send codec config immediately on video channel
            codec = _make_codec_config_payload()
            rc = self._send_channel_encrypted(channel, AA_MSG_AV_MEDIA_INDICATION, codec)
            log(f"  >> Codec config sent on channel {channel} ({len(codec)} bytes)")
            if rc == AA_OK:
                self.video.config_sent = True
                self.video.next_ts_ms = time_ms() + _video_mod._FRAME_INTERVAL_MS
        elif kind in _AUDIO_KINDS:
            # Audio focus is managed on the control channel (ch0), not the
            # audio channel. The phone must request focus BEFORE starting
            # playback — the HU will not accept audio data without a grant.
            if not self.audio.focus_requested:
                self.audio.focus_requested = True
                self.audio.focus_granted = False
                self.audio.focus_request_ts_ms = time_ms()
                payload = encode_audio_focus_request(AUDIO_FOCUS_TYPE_GAIN)
                rc = self._send_control_encrypted(AA_MSG_AUDIO_FOCUS_REQUEST, payload)
                log(f"  >> AudioFocusRequest sent on ch0 (type=GAIN) rc={rc} "
                    f"— waiting for grant before streaming")
            self.audio.channel = channel
            self.audio.config_sent = False
            self.audio.streaming = True
            # Send AAC codec config immediately on audio channel
            codec = _make_audio_codec_config_payload()
            rc = self._send_channel_encrypted(channel, AA_MSG_AV_MEDIA_INDICATION, codec)
            log(f"  >> Audio codec config sent on channel {channel} ({len(codec)} bytes)")
            if rc == AA_OK:
                self.audio.config_sent = True
                self.audio.next_ts_ms = time_ms() + AUDIO_FRAME_INTERVAL_MS
        return rc

    # ------------------------------------------------------------------
    # Main process loop
    # ------------------------------------------------------------------

    def process(self) -> int:
        if self.state == AAState.CONNECT:
            return self._do_connect()
        if self.state == AAState.SD_SEND:
            return self._maybe_send_service_discovery()
        if self.state == AAState.READY:
            self._process_streams()
        if self.state in (AAState.DONE, AAState.ERROR):
            return AA_OK
        return self._process_recv()

    def _do_connect(self) -> int:
        rc = self.transport.connect()
        if rc != AA_OK:
            if getattr(self.transport, "interrupted", False):
                self.state = AAState.DONE
                return AA_OK
            self.state = AAState.ERROR
            return rc
        self.crypto = AACrypto.create_server(self.cert_path, self.key_path)
        if not self.crypto:
            self.state = AAState.ERROR
            return AA_ERR
        self.state = AAState.VERSION_RECV
        log("Connected. Waiting for version request...")
        return AA_OK

    def _maybe_send_service_discovery(self) -> int:
        if time_ms() < self.sd_delay_until_ms:
            return AA_OK
        return self._send_service_discovery_request()

    def _process_streams(self) -> None:
        now = time_ms()
        self._stream_video(now)
        self._stream_audio(now)
        if self.sensor_subscribed and now >= self.next_sensor_ts_ms:
            self.next_sensor_ts_ms = now + 1000

    def _stream_video(self, now: int) -> None:
        if not (self.video.streaming and self.video.config_sent):
            return
        self._stream_av(self.video, _make_video_frame_payload, _frame_latency,
                        _video_mod._FRAME_INTERVAL_MS, "video", now,
                        resend_config=True, log_input=True)

    def _stream_audio(self, now: int) -> None:
        if not (self.audio.streaming and self.audio.config_sent):
            return
        if not self.audio.focus_granted:
            if self.audio.focus_requested and not self.audio.focus_warned and \
                    now - self.audio.focus_request_ts_ms > 5000:
                self.audio.focus_warned = True
                log("WARN: audio focus requested but not granted — "
                    "playback paused (HU must reply to AudioFocusRequest)")
            return
        self._stream_av(self.audio, _make_audio_frame_payload, _audio_latency,
                        AUDIO_FRAME_INTERVAL_MS, "audio", now)

    def _stream_av(self, st, make_frame, latency, interval_ms, name, now: int,
                   resend_config: bool = False, log_input: bool = False) -> None:
        if now < st.next_ts_ms:
            return
        st.ticks += 1

        # Flow control gate FIRST so a blocked send never consumes a frame:
        # in lossless (GOP) mode the frame must be held for retry, and in
        # all-intra mode it avoids needlessly dropping queued frames.
        max_unacked = st.max_unacked if st.max_unacked > 0 else 3
        if st.unacked >= max_unacked:
            st.flowctl_count += 1
            if self.verbose:
                log(f"{name} flow ctrl: {st.unacked}/{max_unacked} unacked, waiting for ACK")
            st.next_ts_ms = now + interval_ms
            return

        cap_time, frame = make_frame(now)
        if frame is None:
            st.empty_count += 1
            st.next_ts_ms = now + interval_ms
            return

        if resend_config and _video_mod._SCREEN_CAPTURE_SPEC and not st.capture_codec_sent:
            st.capture_codec_sent = True
            codec = _make_codec_config_payload()
            rc2 = self._send_channel_encrypted(st.channel, AA_MSG_AV_MEDIA_INDICATION, codec)
            if self.verbose:
                log(f"  >> Codec config re-sent ({len(codec)}B) rc={rc2}")
        rc = self._send_channel_encrypted(st.channel, AA_MSG_AV_MEDIA_WITH_TS, frame)
        if rc == AA_OK:
            st.unacked += 1
            st.frame_count += 1
            st.bytes_sent += len(frame)
            latency.add(time_ms() - cap_time)
        elif st.unacked > 0:
            log(f"WARN: {name} frame send failed rc={rc} size={len(frame)}B")

        if now - st.fps_log_ms >= 5000:
            elapsed_s = (now - st.fps_log_ms) / 1000 if st.fps_log_ms else 1
            rate = st.frame_count / max(elapsed_s, 0.001)
            mb_s = (st.bytes_sent / 1048576.0) / max(elapsed_s, 0.001)
            log(f"{name.capitalize()}: {st.frame_count} frames sent "
                f"({rate:.1f} fps, {mb_s:.2f} MB/s) latency {latency.stats_str()} "
                f"[ticks={st.ticks} empty={st.empty_count} flowctl={st.flowctl_count}]")
            if log_input:
                log(f"Input latency {_input_latency.stats_str()}")
            st.frame_count = 0
            st.bytes_sent = 0
            st.ticks = 0
            st.empty_count = 0
            st.flowctl_count = 0
            st.fps_log_ms = now

        st.next_ts_ms = now + interval_ms

    def _process_recv(self) -> int:
        # Receive a frame
        recv_timeout = AA_RECV_TIMEOUT_MS
        if self.state == AAState.READY and (self.video.streaming or self.audio.streaming):
            next_ts = self.video.next_ts_ms if self.video.streaming else 0
            if self.audio.streaming:
                next_ts = self.audio.next_ts_ms if next_ts == 0 else min(next_ts, self.audio.next_ts_ms)
            remaining = next_ts - time_ms()
            recv_timeout = max(1, min(remaining + 2, AA_RECV_TIMEOUT_MS))
        elif self.state == AAState.SHUTDOWN:
            recv_timeout = AA_SHUTDOWN_RECV_TIMEOUT_MS
        rc, frame = frame_read(self.transport, recv_timeout)
        if rc == AA_ERR_TIMEOUT:
            return AA_OK
        if rc != AA_OK:
            self.state = AAState.ERROR
            return rc

        if self.verbose:
            log(f"Frame: ch={frame.channel_id} flags=0x{frame.flags:02X} len={frame.payload_len}")

        # Non-control channel data path. Frames with the CONTROL flag set are
        # control messages even on non-zero channels (the DHU sends e.g. the
        # ChannelOpenResponse on the channel being opened), so they fall
        # through to the control-message handlers below.
        if frame.channel_id != AA_CHANNEL_CONTROL and not (frame.flags & AA_FLAG_CONTROL):
            if frame.payload_len < 2:
                return AA_OK

            ch_encrypted = (frame.flags & AA_FLAG_ENCRYPTED) != 0

            if ch_encrypted:
                rc2, plain = self.crypto.read_decrypted(frame.payload[:frame.payload_len])
                if rc2 != AA_OK:
                    return rc2
                if len(plain) < 2:
                    return AA_OK
                msg_id = (plain[0] << 8) | plain[1]
                data = plain[2:]
            else:
                msg_id = (frame.payload[0] << 8) | frame.payload[1]
                data = frame.payload[2:frame.payload_len]

            if self.verbose:
                log(f"Channel {frame.channel_id} ({channel_name(frame.channel_id)}) msg=0x{msg_id:04X} len={len(data)} enc={ch_encrypted}")

            return self._handle_channel_message(frame.channel_id, msg_id, data)

        # Control channel (channel 0)
        encrypted = (frame.flags & AA_FLAG_ENCRYPTED) != 0

        # During TLS handshake, TLS records come with ENCRYPTED flag but are raw TLS
        if self.state == AAState.TLS_HANDSHAKE:
            if frame.payload_len < 2:
                return AA_OK
            msg_id = (frame.payload[0] << 8) | frame.payload[1]
            payload = frame.payload[2:frame.payload_len]
            return self._handle_plaintext_control(msg_id, payload)

        if encrypted:
            rc2, plain = self.crypto.read_decrypted(frame.payload[:frame.payload_len])
            if rc2 != AA_OK:
                return rc2
            if len(plain) < 2:
                return AA_OK

            msg_id = (plain[0] << 8) | plain[1]
            data = plain[2:]

            if self.verbose:
                log(f"Decrypted msg 0x{msg_id:04X}: plaintext ({len(plain)} bytes)")

            return self._handle_encrypted_control(msg_id, data)
        else:
            if frame.payload_len < 2:
                return AA_OK
            msg_id = (frame.payload[0] << 8) | frame.payload[1]
            payload = frame.payload[2:frame.payload_len]
            return self._handle_plaintext_control(msg_id, payload)

    def _subscribe_sensors(self, ch_id: int) -> None:
        sensor_types = []
        for cid, sc in self.sensor_channels:
            if cid == ch_id:
                for s in sc.sensors:
                    sensor_types.append(s.type)
                break
        if not sensor_types:
            sensor_types = list(range(1, 23))
        interval = 200
        for st in sensor_types:
            payload = encode_sensor_request(st, interval)
            self._send_channel_encrypted(ch_id, AA_MSG_SENSOR_REQUEST, payload)
            log(f"  >> SensorRequest: type={st} interval={interval}ms on ch{ch_id}")
        self.sensor_subscribed[ch_id] = sensor_types
        self.next_sensor_ts_ms = time_ms() + 1000

    def send_byebye(self, reason: int = 1) -> int:
        log(f">> Sending ByeBye (reason={reason})...")
        payload = encode_byebye_request(reason)
        plain = AA_MSG_BYEBYE_REQUEST.to_bytes(2, "big") + payload
        self._send_encrypted(AA_CHANNEL_CONTROL, plain)
        self.state = AAState.SHUTDOWN
        return AA_OK

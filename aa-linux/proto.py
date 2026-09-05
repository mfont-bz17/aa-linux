"""Protobuf encode/decode using generated _pb2.py classes."""

from __future__ import annotations

import os
import struct
import sys
from dataclasses import dataclass, field

# Add generated directory and protobuf deps to path
_package_dir = os.path.dirname(os.path.abspath(__file__))
_generated_dir = os.path.join(_package_dir, "generated")
_venv_dir = os.path.join(_package_dir, ".venv")
for d in (_venv_dir, _generated_dir):
    if d not in sys.path:
        sys.path.insert(0, d)

# Generated protobuf message classes
from oaa.control.AuthCompleteIndicationMessage_pb2 import AuthCompleteIndication
from oaa.control.ChannelOpenRequestMessage_pb2 import ChannelOpenRequest
from oaa.control.ChannelOpenResponseMessage_pb2 import ChannelOpenResponse
from oaa.control.PingRequestMessage_pb2 import PingRequest
from oaa.control.PingResponseMessage_pb2 import PingResponse
from oaa.control.ServiceDiscoveryRequestMessage_pb2 import ServiceDiscoveryRequest
from oaa.control.ServiceDiscoveryResponseMessage_pb2 import ServiceDiscoveryResponse
from oaa.control.ServiceDiscoveryUpdateMessage_pb2 import ServiceDiscoveryUpdate
from oaa.control.ShutdownRequestMessage_pb2 import ShutdownRequest
from oaa.audio.AudioFocusRequestMessage_pb2 import AudioFocusRequest
from oaa.audio.AudioFocusResponseMessage_pb2 import AudioFocusResponse
from oaa.generic.ChannelOpenAckMessage_pb2 import ChannelOpenAck
from oaa.av.AVChannelSetupRequestMessage_pb2 import AVChannelSetupRequest
from oaa.av.AVChannelSetupResponseMessage_pb2 import AVChannelSetupResponse
from oaa.av.AVChannelStartIndicationMessage_pb2 import AVChannelStartIndication
from oaa.video.VideoFocusRequestMessage_pb2 import VideoFocusRequest
from oaa.sensor.SensorRequestMessage_pb2 import SensorRequest
from oaa.sensor.SensorStartResponseMessage_pb2 import SensorStartResponseMessage
from oaa.sensor.SensorEventIndicationMessage_pb2 import SensorEventIndication
from oaa.sensor.SensorErrorMessage_pb2 import SensorError
from oaa.input.InputEventIndicationMessage_pb2 import InputEventIndication
from oaa.bluetooth.BluetoothAuthenticationDataMessage_pb2 import BluetoothAuthenticationData
from oaa.bluetooth.BluetoothAuthenticationResultMessage_pb2 import BluetoothAuthenticationResult
from oaa.bluetooth.BluetoothPairingRequestMessage_pb2 import BluetoothPairingRequest
from oaa.bluetooth.BluetoothPairingResponseMessage_pb2 import BluetoothPairingResponse
from oaa.wifi.WifiStartRequestMessage_pb2 import WifiStartRequest
from oaa.wifi.WifiStartResponseMessage_pb2 import WifiStartResponse
from oaa.wifi.WifiInfoRequestMessage_pb2 import WifiInfoRequest
from oaa.wifi.WifiInfoResponseMessage_pb2 import WifiInfoResponse
from oaa.wifi.WifiConnectStatusMessage_pb2 import WifiConnectStatus
from oaa.wifi.WifiVersionRequestMessage_pb2 import WifiVersionRequest
from oaa.wifi.WifiVersionResponseMessage_pb2 import WifiVersionResponse


# ---------------------------------------------------------------------------
# Version exchange (NOT protobuf — raw big-endian)
# ---------------------------------------------------------------------------

def encode_version_response(major: int, minor: int, status: int) -> bytes:
    return struct.pack(">HHH", major, minor, status)


def decode_version_request(data: bytes) -> tuple[int, int]:
    if len(data) < 4:
        raise ValueError("version request too short")
    major = (data[0] << 8) | data[1]
    minor = (data[2] << 8) | data[3]
    return major, minor


# ---------------------------------------------------------------------------
# 1x1 white PNG icon required by real DHU
# ---------------------------------------------------------------------------

ICON_1X1 = bytes([
    0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
    0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,
    0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
    0x08, 0x02, 0x00, 0x00, 0x00,
    0x90, 0x77, 0x53, 0xDE,
    0x00, 0x00, 0x00, 0x0C, 0x49, 0x44, 0x41, 0x54,
    0x08, 0xD7, 0x63, 0xF8, 0xCF, 0xC0, 0x00, 0x00,
    0x00, 0x02, 0x00, 0x01,
    0xE2, 0x21, 0xBC, 0x33,
    0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4E, 0x44,
    0xAE, 0x42, 0x60, 0x82,
])


# ---------------------------------------------------------------------------
# AuthCompleteIndication
# ---------------------------------------------------------------------------

def encode_auth_complete(status: int) -> bytes:
    msg = AuthCompleteIndication()
    msg.status = status
    return msg.SerializeToString()


def decode_auth_complete(data: bytes) -> int:
    msg = AuthCompleteIndication()
    msg.ParseFromString(data)
    return msg.status


# ---------------------------------------------------------------------------
# ServiceDiscoveryRequest
# ---------------------------------------------------------------------------

def encode_service_discovery_request(device_name: str = "AA Linux") -> bytes:
    msg = ServiceDiscoveryRequest()
    msg.device_name = device_name
    msg.device_brand = "AA"
    msg.phone_icon_small = ICON_1X1
    msg.phone_icon_medium = ICON_1X1
    msg.phone_icon_large = ICON_1X1
    msg.session_info.session_uuid = "a0b1c2d-e3f4-5678-9abc-def012345678"
    return msg.SerializeToString()


# ---------------------------------------------------------------------------
# ServiceDiscoveryResponse
# ---------------------------------------------------------------------------

@dataclass
class ServiceDiscoveryResponseData:
    head_unit_name: str = ""
    car_model: str = ""
    headunit_manufacturer: str = ""
    headunit_model: str = ""
    sw_build: str = ""
    sw_version: str = ""
    channels: list = field(default_factory=list)


def decode_service_discovery_response(data: bytes) -> ServiceDiscoveryResponseData:
    msg = ServiceDiscoveryResponse()
    msg.ParseFromString(data)

    resp = ServiceDiscoveryResponseData(
        head_unit_name=msg.head_unit_name,
        car_model=msg.car_model,
        headunit_manufacturer=msg.headunit_manufacturer,
        headunit_model=msg.headunit_model,
        sw_build=msg.sw_build,
        sw_version=msg.sw_version,
    )

    for ch in msg.channels:
        resp.channels.append(ch)

    return resp


# ---------------------------------------------------------------------------
# ServiceDiscoveryUpdate
# ---------------------------------------------------------------------------

def encode_service_discovery_update(channel_id: int) -> bytes:
    msg = ServiceDiscoveryUpdate()
    msg.descriptor.channel_id = channel_id
    return msg.SerializeToString()


# ---------------------------------------------------------------------------
# PingRequest / PingResponse
# ---------------------------------------------------------------------------

def encode_ping_request(timestamp: int) -> bytes:
    msg = PingRequest()
    msg.timestamp = timestamp
    return msg.SerializeToString()


def encode_ping_response(timestamp: int) -> bytes:
    msg = PingResponse()
    msg.timestamp = timestamp
    return msg.SerializeToString()


def decode_ping_request(data: bytes) -> int:
    msg = PingRequest()
    msg.ParseFromString(data)
    return msg.timestamp


# ---------------------------------------------------------------------------
# ShutdownRequest (ByeBye)
# ---------------------------------------------------------------------------

def encode_byebye_request(reason: int) -> bytes:
    msg = ShutdownRequest()
    msg.reason = reason
    return msg.SerializeToString()


def encode_byebye_response() -> bytes:
    return b""


def decode_byebye_request(data: bytes) -> int:
    msg = ShutdownRequest()
    msg.ParseFromString(data)
    return msg.reason


# ---------------------------------------------------------------------------
# ChannelOpenRequest / Response
# ---------------------------------------------------------------------------

def encode_channel_open_request(priority: int, channel_id: int) -> bytes:
    msg = ChannelOpenRequest()
    msg.priority = priority
    msg.channel_id = channel_id
    return msg.SerializeToString()


def decode_channel_open_request(data: bytes) -> tuple[int, int]:
    msg = ChannelOpenRequest()
    msg.ParseFromString(data)
    return msg.priority, msg.channel_id


def encode_channel_open_response(status: int) -> bytes:
    msg = ChannelOpenResponse()
    msg.status = status
    return msg.SerializeToString()


def decode_channel_open_response(data: bytes) -> int:
    msg = ChannelOpenResponse()
    msg.ParseFromString(data)
    return msg.status


# ---------------------------------------------------------------------------
# ChannelOpenAck (empty message)
# ---------------------------------------------------------------------------

def encode_channel_open_ack() -> bytes:
    msg = ChannelOpenAck()
    return msg.SerializeToString()


# ---------------------------------------------------------------------------
# AVChannelSetupRequest / AVChannelSetupResponse
# ---------------------------------------------------------------------------

def encode_av_channel_setup_request(media_codec_type: int) -> bytes:
    msg = AVChannelSetupRequest()
    msg.media_codec_type = media_codec_type
    return msg.SerializeToString()


def decode_av_channel_setup_request(data: bytes) -> int:
    msg = AVChannelSetupRequest()
    msg.ParseFromString(data)
    return msg.media_codec_type


def encode_av_channel_setup_response(status: int, max_unacked: int = 0, configs: list = None) -> bytes:
    msg = AVChannelSetupResponse()
    msg.media_status = status
    if max_unacked:
        msg.max_unacked = max_unacked
    if configs:
        msg.configs.extend(configs)
    return msg.SerializeToString()


def decode_av_channel_setup_response(data: bytes) -> tuple:
    msg = AVChannelSetupResponse()
    msg.ParseFromString(data)
    return msg.media_status, msg.max_unacked, list(msg.configs)


# ---------------------------------------------------------------------------
# AVChannelStartIndication (phone -> HU: starts the stream)
# ---------------------------------------------------------------------------

def encode_av_channel_start_indication(session: int, config: int) -> bytes:
    msg = AVChannelStartIndication()
    msg.session = session
    msg.config = config
    return msg.SerializeToString()


# ---------------------------------------------------------------------------
# VideoFocusRequest (phone -> HU: request/acknowledge focus)
# ---------------------------------------------------------------------------

def encode_video_focus_request(mode: int) -> bytes:
    msg = VideoFocusRequest()
    msg.focus_mode = mode
    return msg.SerializeToString()


# ---------------------------------------------------------------------------
# AudioFocusRequest / AudioFocusResponse (control channel, phone <-> HU)
# ---------------------------------------------------------------------------

# AudioFocusState enum values we treat as "we hold focus"
_AUDIO_FOCUS_STATE_GAINED = (1, 2, 6, 7)  # GAIN, GAIN_TRANSIENT, GAIN_MEDIA_ONLY, GAIN_TRANSIENT_GUIDANCE_ONLY


def encode_audio_focus_request(focus_type: int) -> bytes:
    msg = AudioFocusRequest()
    msg.audio_focus_type = focus_type
    return msg.SerializeToString()


def decode_audio_focus_response(data: bytes) -> tuple[int, bool]:
    msg = AudioFocusResponse()
    msg.ParseFromString(data)
    granted = msg.granted or msg.audio_focus_state in _AUDIO_FOCUS_STATE_GAINED
    return msg.audio_focus_state, granted


# ---------------------------------------------------------------------------
# SensorRequest / SensorStartResponse / SensorEventIndication / SensorError
# ---------------------------------------------------------------------------

def encode_sensor_request(sensor_type: int, refresh_interval: int = 200) -> bytes:
    msg = SensorRequest()
    msg.sensor_type = sensor_type
    msg.refresh_interval = refresh_interval
    return msg.SerializeToString()


def decode_sensor_request(data: bytes) -> tuple:
    msg = SensorRequest()
    msg.ParseFromString(data)
    return msg.sensor_type, msg.refresh_interval


def decode_sensor_start_response(data: bytes) -> int:
    msg = SensorStartResponseMessage()
    msg.ParseFromString(data)
    return msg.status


def encode_sensor_start_response(status: int = 0) -> bytes:
    msg = SensorStartResponseMessage()
    msg.status = status
    return msg.SerializeToString()


def decode_sensor_error(data: bytes) -> tuple:
    msg = SensorError()
    msg.ParseFromString(data)
    return msg.sensor_type, msg.error_status


# ---------------------------------------------------------------------------
# BT RFCOMM WiFi setup messages (wireless AA credential handshake)
# Wire: [len:u16be][msg_id:u16be][protobuf]. msgIds from WifiSetupMessageEnum:
#   1 = WifiStartRequest, 2 = WifiInfoRequest, 3 = WifiInfoResponse,
#   4 = WifiVersionRequest, 5 = WifiVersionResponse, 6 = WifiConnectStatus,
#   7 = WifiStartResponse. Status values follow WifiVersionStatus (SUCCESS=1).
# ---------------------------------------------------------------------------

def decode_wifi_start_request(data: bytes) -> tuple[str, int]:
    msg = WifiStartRequest()
    msg.ParseFromString(data)
    return msg.ip_address, msg.port


def encode_wifi_start_request(ip_address: str, port: int) -> bytes:
    msg = WifiStartRequest()
    msg.ip_address = ip_address
    msg.port = port
    return msg.SerializeToString()


def encode_wifi_start_response(ip_address: str, port: int, status: int) -> bytes:
    msg = WifiStartResponse()
    if ip_address:
        msg.ip_address = ip_address
    msg.port = port
    msg.status = status
    return msg.SerializeToString()


def encode_wifi_info_request() -> bytes:
    return WifiInfoRequest().SerializeToString()


def decode_wifi_info_response(data: bytes) -> dict:
    # Wire order (verified against a VW HU + open-android-auto setup doc):
    #   ssid=1, passphrase=2, bssid=3. The generated WifiInfoResponseMessage
    #   proto has field 2=bssid / 3=passphrase, so the reads are swapped here.
    msg = WifiInfoResponse()
    msg.ParseFromString(data)
    return {
        "ssid": msg.ssid,
        "bssid": msg.passphrase,     # field 3 on the wire
        "passphrase": msg.bssid,     # field 2 on the wire
        "security_mode": msg.security_mode,
        "ap_type": msg.ap_type,
    }


def encode_wifi_info_response(ssid: str = "", bssid: str = "", passphrase: str = "",
                              security_mode: int = 0, ap_type: int = 0) -> bytes:
    # Same wire-order fix as decode: passphrase goes in field 2, bssid in 3.
    msg = WifiInfoResponse()
    if ssid:
        msg.ssid = ssid
    if passphrase:
        msg.bssid = passphrase       # field 2 on the wire
    if bssid:
        msg.passphrase = bssid       # field 3 on the wire
    msg.security_mode = security_mode
    msg.ap_type = ap_type
    return msg.SerializeToString()


def encode_wifi_connect_status(state: int, status_text: str = "") -> bytes:
    msg = WifiConnectStatus()
    msg.state = state
    if status_text:
        msg.status_text = status_text
    return msg.SerializeToString()


def decode_wifi_version_request(data: bytes) -> tuple[int, int]:
    msg = WifiVersionRequest()
    msg.ParseFromString(data)
    return msg.major_version, msg.minor_version


def decode_wifi_version_request_full(data: bytes) -> dict:
    msg = WifiVersionRequest()
    msg.ParseFromString(data)
    return {
        "major": msg.major_version,
        "minor": msg.minor_version,
        "preference": msg.wifi_channel_preference,
        "channels": list(msg.supported_channels),
        "manufacturer": msg.device_info.manufacturer,
        "model": msg.device_info.model,
    }


def encode_wifi_version_request(major: int, minor: int,
                                channel_preference: int = 0,
                                supported_channels: list = None) -> bytes:
    msg = WifiVersionRequest()
    msg.major_version = major
    msg.minor_version = minor
    msg.wifi_channel_preference = channel_preference
    if supported_channels:
        msg.supported_channels.extend(supported_channels)
    return msg.SerializeToString()


def encode_wifi_version_response(major: int, minor: int, status: int,
                                 serial: str = "", channel_type: int = 0) -> bytes:
    msg = WifiVersionResponse()
    msg.major_version = major
    msg.minor_version = minor
    if serial:
        msg.device_serial = serial
    msg.version_status = status
    msg.selected_wifi_channel_type = channel_type
    return msg.SerializeToString()


# ---------------------------------------------------------------------------
# Bluetooth channel (GAL service 9) messages
# 0x8003 AUTH_DATA: HU -> Phone, BluetoothAuthenticationData (auth_data string)
# 0x8004 AUTH_RESULT: Phone -> HU, BluetoothAuthenticationResult (status)
# 0x8001 PAIRING_REQUEST: HU -> Phone; 0x8002 PAIRING_RESPONSE: Phone -> HU
# ---------------------------------------------------------------------------

def decode_bluetooth_auth_data(data: bytes) -> str:
    msg = BluetoothAuthenticationData()
    msg.ParseFromString(data)
    return msg.auth_data


def encode_bluetooth_auth_result(status: int = 0) -> bytes:
    msg = BluetoothAuthenticationResult()
    msg.status = status
    return msg.SerializeToString()


def decode_bluetooth_pairing_request(data: bytes) -> dict:
    msg = BluetoothPairingRequest()
    msg.ParseFromString(data)
    return {
        "phone_address": msg.phone_address,
        "pairing_method": msg.pairing_method,
        "phone_name": msg.phone_name,
    }


def encode_bluetooth_pairing_response(status: int = 0, already_paired: bool = True) -> bytes:
    msg = BluetoothPairingResponse()
    msg.status = status
    msg.already_paired = already_paired
    return msg.SerializeToString()

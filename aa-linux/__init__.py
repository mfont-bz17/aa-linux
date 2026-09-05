"""aa-linux — Android Auto phone-side client (Python port)."""

from .constants import (
    AA_OK,
    AA_ERR,
    AA_ERR_IO,
    AA_ERR_TLS,
    AA_ERR_PROTO,
    AA_ERR_TIMEOUT,
    channel_name,
    channel_type_name,
)
from .transport import TCPTransport
from .usb import FunctionFSTransport
from .wireless import WirelessTransport
from .frame import AAFrame, frame_read, frame_write
from .crypto import AACrypto
from .proto import (
    encode_version_response,
    decode_version_request,
    encode_auth_complete,
    decode_auth_complete,
    encode_service_discovery_request,
    decode_service_discovery_response,
    encode_ping_request,
    encode_ping_response,
    decode_ping_request,
    encode_byebye_request,
    encode_byebye_response,
    decode_byebye_request,
    encode_channel_open_request,
    encode_channel_open_response,
    decode_channel_open_request,
    decode_channel_open_response,
    encode_av_channel_setup_request,
    decode_av_channel_setup_request,
    encode_av_channel_setup_response,
    decode_av_channel_setup_response,
    encode_sensor_request,
    encode_sensor_start_response,
    decode_sensor_request,
    decode_sensor_start_response,
    decode_sensor_error,
    decode_bluetooth_auth_data,
    decode_bluetooth_pairing_request,
    encode_bluetooth_auth_result,
    encode_bluetooth_pairing_response,
)
from .util import LatencyStats
from .sensor import SensorBackend
from .protocol import AAContext, AAState

__all__ = [
    "AA_OK", "AA_ERR", "AA_ERR_IO", "AA_ERR_TLS", "AA_ERR_PROTO", "AA_ERR_TIMEOUT",
    "TCPTransport", "FunctionFSTransport", "WirelessTransport", "AACrypto", "AAFrame", "AAContext", "AAState",
    "SensorBackend",
    "frame_read", "frame_write",
    "channel_name", "channel_type_name",
]

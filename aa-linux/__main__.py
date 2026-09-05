"""CLI entry point — translated from main.c."""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time

from .constants import AA_OK
from .protocol import AAContext, AAState, STATE_NAMES
from .transport import TCPTransport
from .usb import FunctionFSTransport
from .util import log
from .wireless import WirelessTransport

_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_CERT_DIR = os.path.join(_PACKAGE_DIR, "certs")

_BYEBYE_WAIT_TIMEOUT_S = 2.0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="AA Linux — Android Auto phone-side implementation"
    )
    parser.add_argument("-t", "--transport", default="tcp",
                        choices=["tcp", "usb", "wireless"],
                        help="Transport type: tcp, usb (FunctionFS gadget) or "
                             "wireless (Bluetooth + WiFi to a real head unit) "
                             "(default: tcp)")
    parser.add_argument("--ffs", default="/dev/aa_linux",
                        help="FunctionFS mount directory for the USB transport (default: /dev/aa_linux)")
    parser.add_argument("--bt-address", default="",
                        help="Head unit Bluetooth MAC address (required for --transport wireless), "
                             "e.g. AA:BB:CC:DD:EE:FF")
    parser.add_argument("--wlan-interface", default="wlp3s0",
                        help="WiFi interface used to join the head unit's access point (default: wlp3s0)")
    parser.add_argument("--no-hfp", action="store_true",
                        help="Skip the best-effort HFP AG connection to the head unit")
    parser.add_argument("--wireless-timeout", type=int, default=30000,
                        help="Timeout in ms for the wireless BT/WiFi setup steps (default: 30000)")
    parser.add_argument("--rfcomm-channel", type=int, default=0,
                        help="Skip SDP discovery and force this RFCOMM channel for the AA "
                             "service (e.g. 3 for SPPAAWL0 head units; default: auto-discover)")
    parser.add_argument("--wifi-timeout", type=int, default=15000,
                        help="How long to poll for the car's WiFi AP to appear before "
                             "giving up, in ms (default: 15000)")
    parser.add_argument("--log-file", default="",
                        help="Append debug log lines to this file (useful when testing "
                             "in a car with no terminal handy)")
    parser.add_argument("-a", "--address", default="0.0.0.0",
                        help="TCP listen/connect address (default: 0.0.0.0)")
    parser.add_argument("-p", "--port", type=int, default=5277,
                        help="TCP port (default: 5277)")
    parser.add_argument("-c", "--client", action="store_true",
                        help="Client mode: connect to DHU")
    parser.add_argument("-C", "--cert", default=None,
                        help="Server certificate file (required for a real head unit)")
    parser.add_argument("-K", "--key", default=None,
                        help="Server private key file (required for a real head unit)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Verbose output")
    parser.add_argument("-d", "--display", default=None,
                        help="X11 display for screen capture (e.g. :0.0+0,0 or WxH@:0+X,Y)")
    parser.add_argument("--video-encoder", default="auto",
                        choices=["auto", "libx264", "h264_v4l2m2m", "h264_omx"],
                        help="Video encoder: auto (h264_v4l2m2m on ARM if available, else libx264), "
                             "h264_v4l2m2m (RPi hardware), h264_omx (legacy RPi hardware), libx264 (default: auto)")
    parser.add_argument("--video-fps", type=int, default=30,
                        help="Video capture/encode framerate (default: 30)")
    parser.add_argument("--video-bitrate", type=int, default=25000,
                        help="Video target bitrate in kbps (default: 25000)")
    parser.add_argument("--video-crf", type=int, default=15,
                        help="libx264 CRF quality target: lower = better/larger "
                             "(e.g. 12 high, 23 low) (default: 15)")
    parser.add_argument("--video-preset", default="medium",
                        choices=["ultrafast", "superfast", "veryfast", "faster",
                                 "fast", "medium", "slow", "slower", "veryslow"],
                        help="libx264 speed/quality preset (default: medium)")
    parser.add_argument("--video-qp", type=int, default=0,
                        help="Fixed encoder QP for the RPi HW encoder (0 = off). "
                             "The bcm2835 driver ignores -b:v for all-intra, so use "
                             "QP to control quality/size: lower = better/larger "
                             "(e.g. 10 high, 30 low)")
    parser.add_argument("--video-gop", type=int, default=1,
                        help="Video keyframe interval: 1 = all-intra (default), "
                             "N > 1 = GOP of N (much cheaper to encode on weak CPUs; "
                             "enables loss-free delivery so the DHU's decoder sees no "
                             "dropped P-frames)")
    parser.add_argument("--audio-file", default=None,
                        help="Audio file (mp3 etc.) to transcode and stream on the audio_media channel")
    parser.add_argument("--no-audio", action="store_true",
                        help="Disable the audio stream entirely (overrides --audio-file)")
    args = parser.parse_args()

    # Resolve cert paths relative to package certs/ directory
    cert_path = args.cert or os.path.join(_DEFAULT_CERT_DIR, "carservice.pem")
    key_path = args.key or os.path.join(_DEFAULT_CERT_DIR, "carservice.key")

    audio_file = None if args.no_audio else args.audio_file
    if audio_file and not os.path.isfile(audio_file):
        audio_file = os.path.join(_PACKAGE_DIR, audio_file)

    server_mode = not args.client

    # Signal handling
    running = [True]
    transport_ref = [None]

    def sig_handler(sig, frame):
        running[0] = False
        t = transport_ref[0]
        if t is not None:
            interrupt = getattr(t, "interrupt", None)
            if interrupt:
                interrupt()

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    # Enable screen capture mode
    from . import video as aa_video
    if args.display:
        aa_video._SCREEN_CAPTURE_SPEC = args.display
        log(f"Screen capture enabled: {args.display}")

    # Video encoder / rate configuration
    encoder = args.video_encoder
    if encoder == "auto":
        encoder = aa_video.pick_encoder()
    aa_video.set_video_config(encoder=encoder, fps=args.video_fps,
                              bitrate_kbps=args.video_bitrate, gop=args.video_gop,
                              qp=args.video_qp, crf=args.video_crf,
                              preset=args.video_preset)
    log(f"Video config: encoder={encoder} fps={args.video_fps} "
        f"bitrate={args.video_bitrate}kbps crf={args.video_crf} "
        f"preset={args.video_preset} qp={args.video_qp or 'auto'} gop={args.video_gop}")

    # Enable audio source
    from . import audio as aa_audio
    if audio_file:
        aa_audio._AUDIO_FILE_SPEC = audio_file
        log(f"Audio source enabled: {audio_file}")

    # Create transport
    if args.transport == "usb":
        transport = FunctionFSTransport(ffs_dir=args.ffs, verbose=args.verbose)
        log(f"AA Linux — USB (FunctionFS) mode on {args.ffs}")
    elif args.transport == "wireless":
        transport = WirelessTransport(
            bt_address=args.bt_address,
            wlan_interface=args.wlan_interface,
            no_hfp=args.no_hfp,
            timeout_ms=args.wireless_timeout,
            verbose=args.verbose,
            log_file=args.log_file,
            rfcomm_channel=args.rfcomm_channel,
            wifi_timeout_ms=args.wifi_timeout,
        )
        log(f"AA Linux — wireless (BT+WiFi) mode, HU BT {args.bt_address or '?'}, "
            f"WiFi via {args.wlan_interface}")
        if args.log_file:
            log(f"Appending debug log to {args.log_file}")
    else:
        transport = TCPTransport(
            host=args.address,
            port=args.port,
            server_mode=server_mode,
        )
        log(f"AA Linux — {'server' if server_mode else 'client'} mode on {args.address}:{args.port}")

    # Sensor D-Bus service (always on) — publishes readings to org.aalinux.sensors
    # for the sensor debug display (sensor_display.py / sensor_web.py).
    sensor_backend = None
    try:
        from .sensor import DbusSensorBackend
    except ImportError:
        log("Sensor D-Bus service disabled: dbus-fast not importable "
            "(run via the .venv python)")
    else:
        sensor_backend = DbusSensorBackend()
        log("Sensor D-Bus service enabled: org.aalinux.sensors")

    # Create context
    ctx = AAContext(transport, cert_path, key_path, verbose=args.verbose,
                    sensor_backend=sensor_backend)

    transport_ref[0] = transport

    # Main loop
    rc = AA_OK
    while running[0] and ctx.get_state() not in (AAState.DONE, AAState.ERROR):
        rc = ctx.process()
        if rc != AA_OK:
            log(f"Process error: {rc} in state {STATE_NAMES.get(ctx.get_state(), '?')}")
            break

    # Graceful shutdown: send ByeBye if still connected, and (when the user
    # interrupted) wait briefly for the ByeBye response.
    if ctx.get_state() == AAState.READY:
        ctx.send_byebye(1)
        if not running[0]:
            deadline = time.monotonic() + _BYEBYE_WAIT_TIMEOUT_S
            while ctx.get_state() == AAState.SHUTDOWN and time.monotonic() < deadline:
                rc = ctx.process()
                if rc != AA_OK:
                    break

    final_state = ctx.get_state()
    log(f"Final state: {STATE_NAMES.get(final_state, '?')} (rc={rc})")

    ctx.destroy()
    if not running[0]:
        return 0
    return 0 if final_state in (AAState.DONE, AAState.READY, AAState.SHUTDOWN) else 1


if __name__ == "__main__":
    sys.exit(main())

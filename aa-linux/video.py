"""FFmpeg video capture pipeline — H.264 encoding and frame queue."""

from __future__ import annotations

import atexit
import os
import platform
import re
import shutil
import struct
import subprocess
import time

from .ffmpeg_pipe import FFmpegPipe
from .util import LatencyStats, log


# ---------------------------------------------------------------------------
# H.264 AVCC record (codec config payload, msg 0x0001)
# ---------------------------------------------------------------------------

_AVCC_RECORD = bytes.fromhex("0142c01effe100176742c01edc0c83db011000000300100000030020f162f801000568ce0f2c80")

_last_sps = None
_last_pps = None


def _update_avcc_from_annexb(data: bytes = b""):
    """Build the AVCC record from the last SPS/PPS seen in the stream.

    SPS/PPS are captured continuously by the segmenter, so the config reflects
    the encoder's actual parameter sets even when (like most hardware encoders)
    they appear only at stream start rather than before every keyframe.
    """
    global _AVCC_RECORD
    sps, pps = _last_sps, _last_pps
    if sps and pps and len(sps) > 4:
        avcc = bytes([1, sps[1], sps[2], sps[3], 0xFF, 0xE1])
        avcc += len(sps).to_bytes(2, 'big') + sps
        avcc += bytes([1]) + len(pps).to_bytes(2, 'big') + pps
        _AVCC_RECORD = avcc


def _make_codec_config_payload() -> bytes:
    return _AVCC_RECORD


# ---------------------------------------------------------------------------
# Capture state
# ---------------------------------------------------------------------------

_SCREEN_CAPTURE_SPEC = None
_avcc_updated = False
_segmented_once = False

# Encoder / rate config (set from CLI; auto-detected on low-power ARM boards)
_VIDEO_ENCODER = "libx264"          # libx264 | h264_v4l2m2m | h264_omx
_VIDEO_BITRATE_KBPS = 25000
_VIDEO_CRF = 15                     # libx264 quality target (lower = better)
_VIDEO_PRESET = "medium"            # libx264 speed/quality tradeoff
_VIDEO_QP = 0                       # fixed encoder QP (0 = off); HW encoders ignore -b:v for all-intra
_CAPTURE_FPS = 30
_FRAME_INTERVAL_MS = int(1000 / _CAPTURE_FPS)
_VIDEO_GOP = 1                      # keyint: 1 = all-intra, N = GOP of N
_LOSSLESS = False                   # in-order loss-free delivery (for GOP > 1)

# NAL types that start a new segment. libx264 repeats SPS/PPS before every IDR
# (repeat-headers=1) so keyframes start at the SPS. Hardware encoders emit
# SPS/PPS once at stream start, so IDR slices (type 5) are the boundaries for
# all-intra; a GOP stream needs non-IDR slices (types 1/2) as boundaries too.
_FRAME_BOUNDARY_NAL_TYPES = (1, 2, 7)


def _level_for_bitrate(kbps: int) -> str:
    """Smallest H.264 level whose MaxBR admits the VBV rate (40=20M, 41=50M)."""
    for level, max_br in ((40, 20000), (41, 50000), (50, 135000)):
        if kbps <= max_br:
            return str(level)
    return "51"


def set_video_config(encoder=None, fps=None, bitrate_kbps=None, gop=None, qp=None,
                     crf=None, preset=None) -> None:
    """Apply runtime video config: encoder, fps, bitrate, GOP, fixed QP, CRF, preset."""
    global _VIDEO_ENCODER, _VIDEO_BITRATE_KBPS, _VIDEO_CRF, _VIDEO_PRESET
    global _CAPTURE_FPS
    global _FRAME_INTERVAL_MS, _FRAME_BOUNDARY_NAL_TYPES, _VIDEO_GOP, _LOSSLESS
    global _VIDEO_QP
    if encoder is not None:
        _VIDEO_ENCODER = encoder
    if fps is not None and fps > 0:
        _CAPTURE_FPS = fps
    if bitrate_kbps is not None and bitrate_kbps > 0:
        _VIDEO_BITRATE_KBPS = bitrate_kbps
    if crf is not None:
        _VIDEO_CRF = crf if crf > 0 else 15
    if preset is not None:
        _VIDEO_PRESET = preset
    if qp is not None:
        _VIDEO_QP = qp if qp > 0 else 0
    if gop is not None and gop > 0:
        _VIDEO_GOP = gop
        _LOSSLESS = gop > 1
    _FRAME_INTERVAL_MS = int(1000 / _CAPTURE_FPS)
    if _VIDEO_ENCODER in ("h264_v4l2m2m", "h264_omx"):
        _FRAME_BOUNDARY_NAL_TYPES = (1, 2, 5, 7) if _VIDEO_GOP > 1 else (5, 7)
    else:
        _FRAME_BOUNDARY_NAL_TYPES = (1, 2, 7)


def _probe_ffmpeg_encoders() -> set:
    try:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return set()
        r = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True, timeout=10,
        )
        encs = set()
        for ln in r.stdout.decode(errors="replace").splitlines():
            parts = ln.split()
            if len(parts) > 1 and parts[0].startswith(("V", "A", "S")):
                encs.add(parts[1])
        return encs
    except Exception:
        return set()


def _probe_all_intra(encoder: str) -> bool:
    """Encode a short test clip with the encoder and verify it produces pure
    all-intra (every frame a keyframe). Some hardware encoders/drivers ignore
    the GOP setting and emit P-frames, which the DHU's OpenH264 decoder
    hard-fails on — so `auto` only selects an encoder that passes this."""
    try:
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        if not ffmpeg or not ffprobe:
            return False
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".h264", delete=False) as tf:
            path = tf.name
        try:
            r = subprocess.run(
                [ffmpeg, "-v", "error", "-f", "lavfi",
                 "-i", "testsrc2=size=320x240:rate=30",
                 "-frames:v", "12", "-c:v", encoder, "-g", "1",
                 "-b:v", "500k", "-pix_fmt", "yuv420p",
                 "-f", "h264", "-y", path],
                capture_output=True, timeout=30,
            )
            if r.returncode != 0:
                return False
            p = subprocess.run(
                [ffprobe, "-v", "error", "-select_streams", "v:0",
                 "-show_frames", "-show_entries", "frame=key_frame",
                 "-of", "csv=p=0", path],
                capture_output=True, timeout=30, text=True,
            )
            keys = p.stdout.split()
            return len(keys) >= 3 and all(k == "1" for k in keys)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
    except Exception:
        return False


def pick_encoder() -> str:
    """Auto-select the best encoder: an all-intra-capable RPi hardware encoder
    (v4l2m2m/omx) on ARM, else libx264."""
    machine = platform.machine().lower()
    is_arm = machine.startswith("arm") or machine == "aarch64"
    if not is_arm:
        try:
            with open("/proc/device-tree/model", "rb") as f:
                is_arm = b"raspberry" in f.read().lower()
        except OSError:
            pass
    if is_arm:
        encs = _probe_ffmpeg_encoders()
        for enc in ("h264_v4l2m2m", "h264_omx"):
            if enc in encs:
                if _probe_all_intra(enc):
                    return enc
                log(f"WARN: {enc} did not produce all-intra frames (GOP>1) — skipping")
        log("WARN: no hardware H.264 encoder with all-intra support — falling back to libx264")
    return "libx264"

# Stream/capture geometry — default until the HU advertises one in its SD response.
# The stream frame is what the HU expects (advertised resolution). When the HU
# advertises margin_width/height, the content area is the stream size minus the
# margins: the capture display runs at content size and ffmpeg pads the captured
# frames back to the stream size (letterbox/pillarbox on the phone side).
_CAPTURE_WIDTH = 1280
_CAPTURE_HEIGHT = 720
_STREAM_WIDTH = 1280
_STREAM_HEIGHT = 720
_PAD_X = 0
_PAD_Y = 0

# VideoResolution enum (VideoResolutionEnum.proto) -> (width, height)
_VIDEO_RESOLUTION_MAP = {
    1: (800, 480),
    2: (1280, 720),
    3: (1920, 1080),
    4: (2560, 1440),
    5: (3840, 2160),
    6: (720, 1280),
    7: (1080, 1920),
    8: (1440, 2560),
    9: (2160, 3840),
}

# VideoFPS enum (VideoFPSEnum.proto) -> fps
_VIDEO_FPS_MAP = {
    1: 60,
    2: 30,
}


def _set_capture_fps(fps: int):
    """Set capture/encode framerate (also paces the send loop)."""
    global _CAPTURE_FPS, _FRAME_INTERVAL_MS
    if fps > 0 and fps != _CAPTURE_FPS:
        _CAPTURE_FPS = fps
        _FRAME_INTERVAL_MS = int(1000 / _CAPTURE_FPS)
        log(f"Capture fps from HU: {_CAPTURE_FPS}")


def set_video_geometry(video_resolution: int, margin_width: int = 0,
                       margin_height: int = 0, video_fps: int = 0) -> tuple[int, int]:
    """Set stream/capture geometry from the HU's SD VideoConfig.

    The stream frame stays at the advertised resolution while the capture area
    shrinks to (stream - margins); the ffmpeg pad filter re-expands it back to
    the stream size with black margins. Margins are split evenly (remainder on
    the right/bottom). Ensures the capture display is up at the content size
    (auto-starting Xephyr if needed). Returns (stream_w, stream_h)."""
    global _CAPTURE_WIDTH, _CAPTURE_HEIGHT, _STREAM_WIDTH, _STREAM_HEIGHT, _PAD_X, _PAD_Y
    sw, sh = _VIDEO_RESOLUTION_MAP.get(video_resolution, (_STREAM_WIDTH, _STREAM_HEIGHT))
    cw, ch = sw - margin_width, sh - margin_height
    if cw <= 0 or ch <= 0:
        log(f"WARN: invalid margins {margin_width}x{margin_height} for {sw}x{sh} — ignoring")
        cw, ch, margin_width, margin_height = sw, sh, 0, 0
    fps = _VIDEO_FPS_MAP.get(video_fps, 0)
    if fps:
        _set_capture_fps(fps)
    changed = (cw, ch, sw, sh, margin_width // 2, margin_height // 2) != (
        _CAPTURE_WIDTH, _CAPTURE_HEIGHT, _STREAM_WIDTH, _STREAM_HEIGHT, _PAD_X, _PAD_Y)
    _CAPTURE_WIDTH, _CAPTURE_HEIGHT = cw, ch
    _STREAM_WIDTH, _STREAM_HEIGHT = sw, sh
    _PAD_X = margin_width // 2
    _PAD_Y = margin_height // 2
    if changed:
        log(f"Stream geometry from HU: {sw}x{sh} content {cw}x{ch} "
            f"pad {_PAD_X},{_PAD_Y} fps={_CAPTURE_FPS}")
        _stop_ffmpeg()  # apply new geometry on next (re)start
    _ensure_display(cw, ch)
    return sw, sh


def _display_name(spec: str) -> str:
    """:99.0+0,0 -> :99; test -> ''."""
    if not spec or spec == "test":
        return ""
    d = spec.split("+")[0]
    return d.split(".")[0]


def _display_alive(display: str) -> bool:
    try:
        r = subprocess.run(
            ["xrandr", "-q"],
            env={**os.environ, "DISPLAY": display},
            timeout=2, capture_output=True,
        )
        return r.returncode == 0
    except Exception:
        return False


def _resize_display(width: int, height: int):
    """Best-effort xrandr resize of a running capture display to match the HU."""
    display = _display_name(_SCREEN_CAPTURE_SPEC or "")
    if not display:
        return
    try:
        r = subprocess.run(
            ["xrandr", "--output", "default", "--mode", f"{width}x{height}"],
            env={**os.environ, "DISPLAY": display},
            timeout=3, capture_output=True,
        )
        if r.returncode == 0:
            log(f"Resized display {display} to {width}x{height}")
        else:
            log(f"WARN: xrandr resize to {width}x{height} on {display} failed "
                f"(rc={r.returncode}): {r.stderr.decode(errors='replace').strip()[:120]}")
    except Exception as e:
        log(f"WARN: xrandr resize on {display} failed: {e}")


_XVIRT_PROC = None


def _start_virtual_display(display: str, width: int, height: int) -> bool:
    """Start Xephyr on `display` at width x height; wait until alive."""
    global _XVIRT_PROC
    args = ["Xephyr", display, "-screen", f"{width}x{height}",
            "-br", "-ac", "-nolisten", "tcp"]
    if not shutil.which("Xephyr"):
        log("WARN: Xephyr not found — cannot auto-start the display")
        return False
    log(f"Starting Xephyr on {display} at {width}x{height}")
    _XVIRT_PROC = subprocess.Popen(
        args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(20):
        if _display_alive(display):
            log(f"Xephyr ready on {display}")
            return True
        time.sleep(0.1)
    log("WARN: Xephyr did not become ready")
    return True


def _ensure_display(width: int, height: int):
    """Make sure the capture display is up at width x height.

    If the capture display is already running, resize it. Otherwise auto-start
    one Xephyr instance when the capture display is unavailable. No-op without
    --display. Xephyr requires a running parent X server."""
    display = _display_name(_SCREEN_CAPTURE_SPEC or "")
    if not display:
        return
    if _display_alive(display):
        _resize_display(width, height)
        return
    _start_virtual_display(display, width, height)

_frame_latency = LatencyStats(window=500, name="Video")


# 3- and 4-byte Annex-B start codes. A 4-byte code contains the 3-byte prefix,
# so the longer alternative must come first. Regex matching runs at C speed —
# the Python byte-walk it replaced made segmentation the reader bottleneck.
_NAL_SC = re.compile(b"\x00\x00\x00\x01|\x00\x00\x01")


def _nal_matches(buf: bytes):
    """Yield (start_code_pos, nal_type) for every NAL in buf."""
    n = len(buf)
    for m in _NAL_SC.finditer(buf):
        hdr = m.end()
        if hdr < n:
            yield m.start(), buf[hdr] & 0x1f


def _capture_sps_pps(buf: bytes):
    """Remember the most recent SPS/PPS NALs anywhere in the stream buffer."""
    global _last_sps, _last_pps
    n = len(buf)
    matches = list(_NAL_SC.finditer(buf))
    for i, m in enumerate(matches):
        hdr = m.end()
        if hdr >= n:
            continue
        nt = buf[hdr] & 0x1f
        en = matches[i + 1].start() if i + 1 < len(matches) else n
        if nt == 7:
            _last_sps = buf[hdr:en]
        elif nt == 8:
            _last_pps = buf[hdr:en]


def _has_nal_type(buf: bytes, target: int) -> bool:
    """True if the segment contains a NAL of the given type."""
    for _, nt in _nal_matches(buf):
        if nt == target:
            return True
    return False


def _has_vcl(buf: bytes) -> bool:
    """True if the segment contains a coded slice NAL (I/P/B)."""
    for _, nt in _nal_matches(buf):
        if nt in (1, 2, 5):
            return True
    return False


def _sps_pps_prefix() -> bytes:
    """Start-code-prefixed SPS/PPS from the last parameter sets seen, or b''."""
    out = b""
    for nal in (_last_sps, _last_pps):
        if nal:
            out += b"\x00\x00\x00\x01" + nal
    return out


def _find_boundaries(buf: bytes) -> list:
    """Start-code positions of every boundary NAL (single C-speed pass)."""
    out = []
    types = _FRAME_BOUNDARY_NAL_TYPES
    for pos, nt in _nal_matches(buf):
        if nt in types:
            out.append(pos)
    return out


def _segment_h264(buf: bytes):
    global _segmented_once
    w0 = time.monotonic()
    c0 = time.process_time()
    frames = []
    _capture_sps_pps(buf)
    boundaries = _find_boundaries(buf)
    if boundaries:
        for i in range(len(boundaries) - 1):
            frame_data = buf[boundaries[i]:boundaries[i + 1]]
            if len(frame_data) > 20 and _has_vcl(frame_data):
                # Hardware encoders emit SPS/PPS only once at stream start, so
                # prepend them to every frame that lacks them. This makes each
                # message (SPS+PPS+IDR) structurally identical to the libx264
                # repeat-headers stream the DHU's OpenH264 decoder is known to
                # accept, instead of relying solely on the AVCC config message.
                if not _has_nal_type(frame_data, 7):
                    prefix = _sps_pps_prefix()
                    if prefix:
                        frame_data = prefix + frame_data
                if not _segmented_once:
                    _segmented_once = True
                    log(f"Video: first frame NAL types: {_list_nal_types(frame_data)} "
                        f"({len(frame_data)} bytes)")
                frames.append(frame_data)
        buf = buf[boundaries[-1]:]
    wt = (time.monotonic() - w0) * 1000
    if wt > 100:
        ct = (time.process_time() - c0) * 1000
        log(f"SLOW seg: wall={wt:.0f}ms cpu={ct:.0f}ms bytes={len(buf)+sum(len(f) for f in frames)} "
            f"boundaries={len(boundaries)} frames={len(frames)}")
    return buf, frames


def _list_nal_types(buf: bytes) -> list:
    types = []
    pos = 0
    n = len(buf)
    while pos < n - 3:
        if buf[pos] == 0 and buf[pos + 1] == 0:
            sc = 3 if buf[pos + 2] == 1 else (
                4 if pos + 3 < n and buf[pos + 2] == 0 and buf[pos + 3] == 1 else 0
            )
            if sc and pos + sc < n:
                types.append(buf[pos + sc] & 0x1f)
                pos += sc
                continue
        pos += 1
    return types


_ffmpeg_pipe = FFmpegPipe(name="video", maxsize=2, segment=_segment_h264)


def _start_ffmpeg_capture(width=None, height=None):
    if width is None:
        width = _CAPTURE_WIDTH
    if height is None:
        height = _CAPTURE_HEIGHT
    if _ffmpeg_pipe.running():
        return True

    spec = _SCREEN_CAPTURE_SPEC
    if not spec:
        return False

    if spec == "test":
        # -re paces the lavfi source at the configured rate. Without it ffmpeg
        # bursts frames as fast as it can into the (small) pipe, and the
        # back-pressure through the queue settles at a fraction of the target
        # fps. Pacing the source matches the send loop (audio already uses -re).
        input_cmd = ["-re", "-f", "lavfi",
                     "-i", f"testsrc2=size={width}x{height}:rate={_CAPTURE_FPS}"]
    else:
        display = os.environ.get("DISPLAY", ":0")
        input_spec = f"{display}{spec}" if ":" not in spec else spec
        input_cmd = [
            "-f", "x11grab",
            "-framerate", str(_CAPTURE_FPS),
            "-video_size", f"{width}x{height}",
            "-i", input_spec,
        ]
        log(f"Capture: x11grab on {input_spec}")

    # The DHU renders decoded YUV via SDL, which picks its conversion matrix
    # from the video height (BT.709 for >= 720p, else BT.601). ffmpeg's default
    # RGB->YUV conversion is BT.601 regardless of resolution, so force the
    # capture matrix to match or colors shift (e.g. red renders dull/orange).
    vf = []
    if _PAD_X or _PAD_Y or (_STREAM_WIDTH, _STREAM_HEIGHT) != (width, height):
        vf.append(f"pad={_STREAM_WIDTH}:{_STREAM_HEIGHT}:{_PAD_X}:{_PAD_Y}:black")
    vf.append(f"scale=out_color_matrix={'bt709' if _STREAM_HEIGHT >= 720 else 'bt601'}")
    vf_args = ["-vf", ",".join(vf)]
    _ffmpeg_pipe.lossless = _LOSSLESS
    qp_args = ["-qmin", str(_VIDEO_QP), "-qmax", str(_VIDEO_QP)] if _VIDEO_QP > 0 else []
    if _VIDEO_ENCODER == "h264_v4l2m2m":
        cmd = ["-filter_threads", "4"] + input_cmd + vf_args + [
            "-c:v", "h264_v4l2m2m",
            "-pix_fmt", "yuv420p",
            "-b:v", f"{_VIDEO_BITRATE_KBPS}k",
        ] + qp_args + [
            "-g", str(_VIDEO_GOP),
            "-muxdelay", "0",
            "-muxpreload", "0",
            "-f", "h264",
            "-",
        ]
    elif _VIDEO_ENCODER == "h264_omx":
        cmd = ["-filter_threads", "4"] + input_cmd + vf_args + [
            "-c:v", "h264_omx",
            "-pix_fmt", "yuv420p",
            "-b:v", f"{_VIDEO_BITRATE_KBPS}k",
        ] + qp_args + [
            "-g", str(_VIDEO_GOP),
            "-muxdelay", "0",
            "-muxpreload", "0",
            "-f", "h264",
            "-",
        ]
    else:
        cmd = input_cmd + vf_args + [
            "-c:v", "libx264",
            "-profile", "baseline",
            "-level", _level_for_bitrate(_VIDEO_BITRATE_KBPS),
            "-pix_fmt", "yuv420p",
            "-crf", str(_VIDEO_CRF),
            "-preset", _VIDEO_PRESET,
            "-tune", "zerolatency",
            "-x264-params",
            f"keyint={_VIDEO_GOP}:min-keyint={_VIDEO_GOP}:no-scenecut=1:repeat-headers=1:"
            f"vbv-maxrate={_VIDEO_BITRATE_KBPS}:vbv-bufsize={_VIDEO_BITRATE_KBPS}",
            "-muxdelay", "0",
            "-muxpreload", "0",
            "-f", "h264",
            "-",
        ]
    log(f"Video: encoder={_VIDEO_ENCODER} fps={_CAPTURE_FPS} "
        f"bitrate={_VIDEO_BITRATE_KBPS}kbps crf={_VIDEO_CRF if _VIDEO_ENCODER == 'libx264' else 'n/a'} "
        f"preset={_VIDEO_PRESET if _VIDEO_ENCODER == 'libx264' else 'n/a'} "
        f"stream={_STREAM_WIDTH}x{_STREAM_HEIGHT} content={width}x{height} pad={_PAD_X},{_PAD_Y} "
        f"matrix={'bt709' if _STREAM_HEIGHT >= 720 else 'bt601'} qp={_VIDEO_QP or 'auto'} gop={_VIDEO_GOP} "
        f"{'lossless' if _LOSSLESS else 'all-intra'}")
    log(f"Video ffmpeg: {' '.join(cmd)}")
    return _ffmpeg_pipe.start(cmd)


def _stop_ffmpeg():
    global _avcc_updated, _last_sps, _last_pps, _segmented_once
    _ffmpeg_pipe.stop()
    _avcc_updated = False
    _last_sps = None
    _last_pps = None
    _segmented_once = False


atexit.register(_stop_ffmpeg)


def _capture_screen_h264(width=None, height=None):
    if width is None:
        width = _CAPTURE_WIDTH
    if height is None:
        height = _CAPTURE_HEIGHT
    global _avcc_updated
    if not _ffmpeg_pipe.running():
        if not _start_ffmpeg_capture(width, height):
            return None, None
        return None, None

    cap_time, data = (_ffmpeg_pipe.pop_first() if _LOSSLESS
                      else _ffmpeg_pipe.pop_latest())
    if data is None:
        return None, None
    if not _avcc_updated:
        _update_avcc_from_annexb(data)
        _avcc_updated = True
    return cap_time, data


def _make_video_frame_payload(timestamp_ms: int):
    cap_time, h264 = _capture_screen_h264()
    if h264 is None:
        return None, None
    ts = struct.pack(">Q", timestamp_ms)
    return cap_time, ts + h264

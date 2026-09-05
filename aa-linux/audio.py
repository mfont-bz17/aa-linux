"""FFmpeg AAC audio pipeline — transcodes an audio file to raw AAC frames."""

from __future__ import annotations

import atexit
import os
import struct

from .ffmpeg_pipe import FFmpegPipe
from .util import LatencyStats, log


# ---------------------------------------------------------------------------
# AAC-LC AudioSpecificConfig (codec config payload, msg 0x0001)
# ---------------------------------------------------------------------------

# AAC-LC, 48 kHz, stereo: audioObjectType=2, samplingFrequencyIndex=3,
# channelConfiguration=2 -> 0x1190
_AAC_AUDIO_SPECIFIC_CONFIG = bytes.fromhex("1190")


def _make_audio_codec_config_payload() -> bytes:
    return _AAC_AUDIO_SPECIFIC_CONFIG


# ---------------------------------------------------------------------------
# Audio state
# ---------------------------------------------------------------------------

_AUDIO_FILE_SPEC = None

_audio_latency = LatencyStats(window=500, name="Audio")


def _find_adts(data: bytes, start: int = 0) -> int:
    pos = start
    while pos < len(data) - 1:
        if data[pos] == 0xFF and (data[pos + 1] & 0xF0) == 0xF0:
            return pos
        pos += 1
    return -1


def _adts_frame_length(data: bytes, start: int) -> int:
    b3 = data[start + 3]
    b4 = data[start + 4]
    b5 = data[start + 5]
    return ((b3 & 0x03) << 11) | (b4 << 3) | ((b5 & 0xE0) >> 5)


def _segment_adts(buf: bytes):
    frames = []
    while True:
        s = _find_adts(buf)
        if s < 0:
            break
        if s + 7 > len(buf):
            break
        frame_len = _adts_frame_length(buf, s)
        if frame_len < 7:
            buf = buf[s + 1:]
            continue
        end = s + frame_len
        if end > len(buf):
            break
        frame = buf[s:end]
        buf = buf[end:]
        header_len = 9 if not (frame[1] & 0x01) else 7
        payload = frame[header_len:]
        if payload:
            frames.append(payload)
    return buf, frames


_ffmpeg_pipe = FFmpegPipe(name="audio", maxsize=8, segment=_segment_adts)


def _start_ffmpeg_audio():
    if _ffmpeg_pipe.running():
        return True

    spec = _AUDIO_FILE_SPEC
    if not spec:
        return False
    if not os.path.isfile(spec):
        log(f"WARN: audio file not found: {spec}")
        return False

    cmd = ["-re", "-i", spec, "-vn",
           "-c:a", "aac",
           "-ar", "48000",
           "-ac", "2",
           "-b:a", "192k",
           "-muxdelay", "0",
           "-muxpreload", "0",
           "-f", "adts",
           "-"]
    log(f"Audio: ffmpeg transcoding {spec} -> AAC-LC 48kHz stereo")
    return _ffmpeg_pipe.start(cmd)


def _stop_ffmpeg_audio():
    _ffmpeg_pipe.stop()


atexit.register(_stop_ffmpeg_audio)


def _make_audio_frame_payload(timestamp_ms: int):
    if not _ffmpeg_pipe.running():
        if not _start_ffmpeg_audio():
            return None, None
        return None, None

    if _ffmpeg_pipe.poll_dead():
        return None, None

    cap_time, data = _ffmpeg_pipe.pop_latest()
    if data is None:
        return None, None
    return cap_time, struct.pack(">Q", timestamp_ms) + data

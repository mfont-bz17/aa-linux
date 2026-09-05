"""Shared ffmpeg subprocess lifecycle — start/stop/reader-thread/restart-throttle.

The caller supplies a ``segment`` callback that consumes complete frames from a
byte buffer: ``segment(buf) -> (remaining_buf, [frame_bytes])``.  The pipe owns
the process, its stderr capture, the reader thread, the frame queue, and the
2-second restart throttle.  Each frame is enqueued as ``(cap_time_ms, bytes)``.
"""

from __future__ import annotations

import os
import queue
import signal
import subprocess
import tempfile
import threading

from .constants import FFMPEG_RESTART_INTERVAL_MS
from .util import find_ffmpeg, log, time_ms


class FFmpegPipe:
    def __init__(self, name: str, maxsize: int, segment,
                 restart_interval_ms: int = FFMPEG_RESTART_INTERVAL_MS):
        self.name = name
        self.maxsize = maxsize
        self.segment = segment
        self.restart_interval_ms = restart_interval_ms
        self.proc: subprocess.Popen = None
        self.stderr = None
        self.queue: queue.Queue = None
        self.last_death_ms = 0
        self._stopping = False
        self.bytes_read = 0
        self.frames_produced = 0
        # Lossless mode: every frame is delivered in order (blocking enqueue,
        # FIFO pop) so a GOP stream with P-frames never loses references. With
        # keyint=1 (all-intra) the lossy drain-to-newest path is safe instead.
        # Small queue on purpose: in lossless mode the blocking enqueue back-
        # pressures ffmpeg, so steady-state dwell = queue depth x frame interval.
        self.lossless = False
        self.lossless_queue_size = 3

    def running(self) -> bool:
        return self.proc is not None

    def start(self, cmd: list) -> bool:
        if self.proc is not None:
            return True
        if time_ms() - self.last_death_ms < self.restart_interval_ms:
            return False
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            return False

        self._stopping = False
        try:
            self.stderr = tempfile.NamedTemporaryFile(
                prefix=f"aa-ffmpeg-{self.name}-", suffix=".log", delete=False
            )
            self.proc = subprocess.Popen(
                [ffmpeg] + cmd, stdout=subprocess.PIPE, stderr=self.stderr,
                bufsize=0, start_new_session=True,
            )
        except Exception as e:
            log(f"WARN: ffmpeg {self.name} start error: {e}")
            self._close_stderr()
            return False

        qsize = self.lossless_queue_size if self.lossless else self.maxsize
        self.queue = queue.Queue(maxsize=qsize)
        threading.Thread(target=self._reader, daemon=True, name=f"ffmpeg-{self.name}").start()
        log(f"FFmpeg {self.name} started: pid={self.proc.pid}")
        return True

    def _reader(self):
        proc = self.proc
        buf = b""
        fd = proc.stdout.fileno()
        last_log_ms = time_ms()
        last_bytes = 0
        last_frames = 0
        max_buf = 0
        max_read_ms = 0
        max_seg_ms = 0
        while True:
            try:
                # os.read on a pipe returns as soon as ANY data is available;
                # BufferedReader.read(n) would block until n bytes accumulate,
                # stalling delivery for large/variable frame sizes.
                t0 = time_ms()
                chunk = os.read(fd, 65536)
                max_read_ms = max(max_read_ms, time_ms() - t0)
            except Exception:
                break
            if not chunk:
                break
            self.bytes_read += len(chunk)
            buf += chunk
            max_buf = max(max_buf, len(buf))
            t0 = time_ms()
            buf, frames = self.segment(buf)
            max_seg_ms = max(max_seg_ms, time_ms() - t0)
            self.frames_produced += len(frames)
            for frame in frames:
                if self.lossless:
                    self.queue.put((time_ms(), frame))
                else:
                    try:
                        self.queue.put_nowait((time_ms(), frame))
                    except queue.Full:
                        pass
            now = time_ms()
            if now - last_log_ms >= 5000:
                dt = (now - last_log_ms) / 1000.0
                fps = (self.frames_produced - last_frames) / max(dt, 0.001)
                mbs = (self.bytes_read - last_bytes) / 1048576.0 / max(dt, 0.001)
                log(f"{self.name} pipe: {fps:.1f} fps, {mbs:.2f} MB/s, "
                    f"buf={max_buf}B read={max_read_ms}ms seg={max_seg_ms}ms")
                last_log_ms = now
                last_bytes = self.bytes_read
                last_frames = self.frames_produced
                max_buf = 0
                max_read_ms = 0
                max_seg_ms = 0
        if not self._stopping:
            self._log_exit(proc.poll())
            self.last_death_ms = time_ms()
        self.proc = None

    def poll_dead(self) -> bool:
        if self.proc is None:
            return False
        if self.proc.poll() is not None:
            return self.queue is None or self.queue.empty()
        return False

    def pop_latest(self):
        if self.queue is None:
            return None, None
        try:
            cap_time, data = self.queue.get_nowait()
            while True:
                try:
                    cap_time, data = self.queue.get_nowait()
                except queue.Empty:
                    break
            return cap_time, data
        except queue.Empty:
            return None, None

    def pop_first(self):
        """FIFO pop — oldest frame first, never drops. Used in lossless mode so
        a GOP stream's P-frame references are preserved in order."""
        if self.queue is None:
            return None, None
        try:
            return self.queue.get_nowait()
        except queue.Empty:
            return None, None

    def stop(self):
        proc = self.proc
        if proc is not None:
            self._stopping = True
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGTERM)
                proc.wait(timeout=1)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=1)
                except Exception:
                    pass
            self.proc = None
        self.queue = None
        self._close_stderr()

    def _close_stderr(self):
        if self.stderr:
            try:
                self.stderr.close()
            except Exception:
                pass
            try:
                os.unlink(self.stderr.name)
            except OSError:
                pass
            self.stderr = None

    def _log_exit(self, rc):
        detail = ""
        if self.stderr:
            try:
                self.stderr.flush()
                self.stderr.seek(0)
                data = self.stderr.read()
                if data:
                    tail = data.decode(errors="replace").strip().splitlines()[-5:]
                    detail = " stderr: " + " | ".join(tail)
            except Exception:
                pass
            self._close_stderr()
        log(f"WARN: ffmpeg {self.name} exited rc={rc}{detail}")

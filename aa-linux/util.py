"""Shared helpers — logging, time, stats, and subprocess discovery."""

from __future__ import annotations

import shutil
import sys
import time
from collections import deque


def log(msg: str) -> None:
    print(f"[INFO] {msg}", file=sys.stderr)


def time_ms() -> int:
    return int(time.monotonic() * 1000)


def find_ffmpeg() -> str:
    return shutil.which("ffmpeg") or ""


class LatencyStats:
    def __init__(self, window: int = 500, name: str = ""):
        self.name = name
        self.window = window
        self.samples: deque = deque(maxlen=window)
        self.total = 0.0
        self.count = 0

    def add(self, value_ms: float):
        self.samples.append(value_ms)
        self.total += value_ms
        self.count += 1

    def avg(self) -> float:
        if not self.samples:
            return 0.0
        return sum(self.samples) / len(self.samples)

    def min(self) -> float:
        return min(self.samples) if self.samples else 0.0

    def max(self) -> float:
        return max(self.samples) if self.samples else 0.0

    def report(self) -> str:
        return f"{self.name}: {self.stats_str()}"

    def stats_str(self) -> str:
        if not self.samples:
            return "no samples"
        return f"min={self.min():.1f} avg={self.avg():.1f} max={self.max():.1f}ms ({len(self.samples)} samples)"

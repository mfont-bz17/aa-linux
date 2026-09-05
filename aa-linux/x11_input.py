"""X11 input event injection via xdotool subprocess."""
import os
import shutil
import subprocess

from .util import log


class X11InputInjector:
    def __init__(self, display=":99", verbose=False):
        self.env = {**os.environ, "DISPLAY": display}
        self.touch_active = False
        self.verbose = verbose
        self.available = shutil.which("xdotool") is not None
        if not self.available:
            log("WARN: xdotool not found — input events will be logged but not injected")

    def _xd(self, args):
        if not self.available:
            return
        try:
            subprocess.run(["xdotool"] + args, env=self.env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            log(f"WARN: xdotool failed ({e}) — disabling input injection")
            self.available = False

    def inject_touch(self, x, y, action):
        if not self.available:
            if self.verbose:
                log(f"Input: touch action={action} x={x} y={y} (xdotool missing)")
            return
        if action == 0:
            self._xd(["mousemove", str(x), str(y)])
            self._xd(["mousedown", "1"])
            self.touch_active = True
        elif action == 1:
            self._xd(["mouseup", "1"])
            self.touch_active = False
        elif action == 2:
            self._xd(["mousemove", str(x), str(y)])

    def inject_scroll(self, delta):
        if not self.available:
            if self.verbose:
                log(f"Input: scroll delta={delta} (xdotool missing)")
            return
        btn = "4" if delta < 0 else "5"
        self._xd(["click", btn])

    def close(self):
        if self.touch_active:
            self._xd(["mouseup", "1"])
            self.touch_active = False

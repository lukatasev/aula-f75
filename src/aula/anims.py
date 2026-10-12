"""Live animations, ported from src/animations.js.

Frame results are ('all', (r,g,b)) or ('keys', {led: (r,g,b)}).
Wireless sends grouped realtime packets (sub 1) or whole-board (sub 2).
Wired streams direct-mode (0x08) frames: temporary live overlay with
~1s auto-revert, no config writes, nothing stored to restore.
"""

from __future__ import annotations

import math
import random
import threading
import time

from . import protocol as P
from .transport import CommError

ANIM_INFO = {
    "wave": ("Rainbow wave", "colors flowing across the keyboard", False),
    "spin": ("Spinning rainbow", "a color wheel around the center", False),
    "gradient": ("Gradient", "color 1 and color 2 blending in waves", False),
    "scanner": ("Scanner", "a color 1 bar sweeping back and forth", False),
    "fire": ("Fire", "flames rising from the bottom row", False),
    "stars": ("Stars", "color 1 keys twinkling at random", False),
    "type": ("Typing ripples", "every key press sends out a ripple", False),
    "eq": ("Equalizer", "bars rising with the sound", True),
    "pulse": ("Beat pulse", "the keyboard pulses with the bass", True),
    "cycle": ("Color cycle", "the whole keyboard fading through colors",
              False),
    "meteor": ("Meteor", "a comet sweeping back and forth", False),
}
AUDIO_ANIMS = {k for k, v in ANIM_INFO.items() if v[2]}
TYPING_ANIM = "type"


def encode_groups(keys: dict) -> bytes | None:
    """Group leds by color with progressive quantization (<= RT_MAX)."""
    for q in (1, 8, 16, 24, 32, 48, 64, 85, 128):
        groups: dict = {}
        for led, c in keys.items():
            if q == 1:
                qc = tuple(max(0, min(255, round(v))) for v in c)
            else:
                qc = tuple(max(0, min(255, round(v / q) * q)) for v in c)
            if P.is_black(qc):
                continue
            groups.setdefault((qc[0] << 16) | (qc[1] << 8) | qc[2],
                              []).append(led)
        size = sum(4 + len(v) for v in groups.values())
        if size > P.RT_MAX:
            continue
        out = bytearray(size)
        o = 0
        for key, leds in groups.items():
            out[o] = (key >> 16) & 0xFF
            out[o + 1] = (key >> 8) & 0xFF
            out[o + 2] = key & 0xFF
            out[o + 3] = len(leds)
            out[o + 4:o + 4 + len(leds)] = bytes(leds)
            o += 4 + len(leds)
        return bytes(out)
    return None


# ---------------------------------------------------------------- frames
def _frame_wave(tt, _dt, st, _fx):
    return ("keys", {e[6]: P.hsv(P.kx(e) * 0.8 - tt * 0.25, 1, 1)
                     for e in P.LAYOUT})


def _frame_spin(tt, _dt, st, _fx):
    out = {}
    for e in P.LAYOUT:
        ang = math.atan2((P.ky(e) - 0.5) * 0.4, P.kx(e) - 0.5) / (2 * math.pi)
        out[e[6]] = P.hsv(ang - tt * 0.2, 1, 1)
    return ("keys", out)


def _frame_gradient(tt, _dt, st, fx):
    a, b = fx["c1"], fx["c2"]
    return ("keys", {e[6]: P.mix(a, b, 0.5 + 0.5 * math.sin(
        P.kx(e) * 5 + P.ky(e) * 2 - tt * 1.5)) for e in P.LAYOUT})


def _frame_scanner(tt, _dt, st, fx):
    p = 0.5 + 0.5 * math.sin(tt * 1.6)
    a, b = fx["c1"], P.scale(fx["c2"], 0.15)
    out = {}
    for e in P.LAYOUT:
        d = (P.kx(e) - p) / 0.07
        out[e[6]] = P.mix(b, a, math.exp(-(d * d)))
    return ("keys", out)


def _frame_fire(tt, _dt, st, _fx):
    out = {}
    for e in P.LAYOUT:
        x, y = P.kx(e), P.ky(e)
        n = 0.5 + 0.25 * math.sin(x * 17 + tt * 6.1) + \
            0.25 * math.sin(x * 7.3 - tt * 3.7 + y * 4)
        heat = P.clamp01(y * 1.25 - 0.35 + (n - 0.5) * 0.9)
        out[e[6]] = (255 * P.clamp01(heat * 1.6),
                     255 * P.clamp01(heat * heat * 1.1 - 0.05),
                     255 * P.clamp01(heat - 0.85) * 3)
    return ("keys", out)


def _frame_stars(_tt, dt, st, fx):
    a = fx["c1"]
    b = P.scale(fx["c2"], 0.2)
    sp = fx["speed"]
    tw = st.setdefault("tw", {})
    for e in P.LAYOUT:
        if random.random() < dt * 0.35 * sp:
            tw[e[6]] = 1.0
    for led in list(tw):
        nv = tw[led] - dt * 1.2 * sp
        if nv <= 0:
            del tw[led]
        else:
            tw[led] = nv
    return ("keys", {e[6]: P.mix(b, a, tw.get(e[6], 0.0))
                     for e in P.LAYOUT})


def _frame_type(_tt, _dt, st, fx):
    a = fx["c1"]
    b = P.scale(fx["c2"], 0.12)
    sp = fx["speed"]
    now = st.get("now", 0.0)
    rip = [r for r in st.setdefault("rip", []) if now - r[2] < 1.6 / sp]
    st["rip"] = rip
    out = {}
    for e in P.LAYOUT:
        v = 0.0
        for rx, ry, rt in rip:
            age = (now - rt) * sp
            d = math.hypot(P.kx(e) - rx, (P.ky(e) - ry) * 0.4)
            v += math.exp(-(((d - age * 0.55) / 0.05) ** 2)) * \
                max(0.0, 1 - age / 1.6)
        out[e[6]] = P.mix(b, a, P.clamp01(v))
    return ("keys", out)


def _frame_eq(_tt, dt, st, fx):
    feed = fx["feed"]
    cols = 14
    lv = []
    for c in range(cols):
        f0 = 60 * 150 ** (c / cols)
        f1 = 60 * 150 ** ((c + 1) / cols)
        lv.append(P.clamp01(feed.band(f0, f1) * fx["gain"] - 0.08))
    sp = fx["speed"]
    if fx.get("peak_fall", True):
        # smooth-fall bars (fast attack, slow release) + slower peak caps
        disp = st.setdefault("disp", [0.0] * cols)
        peaks = st.setdefault("peaks", [0.0] * cols)
        for c in range(cols):
            disp[c] = lv[c] if lv[c] > disp[c] \
                else max(0.0, disp[c] - dt * 0.9 * sp)
            peaks[c] = max(disp[c], peaks[c] - dt * 0.5 * sp)
    else:
        disp, peaks = lv, lv
    style = fx.get("eq_style", "rainbow")
    out = {}
    for e in P.LAYOUT:
        col = min(cols - 1, int(P.kx(e) * cols))
        h = 1 - P.ky(e)
        if h <= disp[col] + 0.04:
            if style == "solid":
                out[e[6]] = fx["c1"]
            elif style == "gradient":
                out[e[6]] = P.mix(fx["c1"], fx["c2"], h)
            else:
                out[e[6]] = P.hsv(0.33 * (1 - h), 1, 1)
        elif fx.get("peak_fall", True) and abs(h - peaks[col]) < 0.035:
            out[e[6]] = (255, 255, 255)
        else:
            out[e[6]] = (0, 0, 0)
    return ("keys", out)


def _frame_pulse(_tt, _dt, _st, fx):
    feed = fx["feed"]
    lvl = P.clamp01(feed.band(40, 160) * fx["gain"] - 0.05) ** 1.5
    return ("all", P.scale(fx["c1"], 0.06 + 0.94 * lvl))


def _frame_cycle(tt, _dt, _st, _fx):
    return ("all", P.hsv(tt * 0.06, 1, 1))


def _frame_meteor(_tt, dt, st, fx):
    """Example custom animation: meteors falling with fading trails,
    spawning at random columns. Copy this shape for your own: take
    (tt, dt, st, fx), return ("keys", {led: rgb}) or ("all", rgb)."""
    import random
    sp = fx["speed"]
    meteors = st.setdefault("meteors", [])
    if random.random() < dt * 1.2 * sp and len(meteors) < 6:
        meteors.append([random.random(), -0.1, 0.5 + random.random() * 0.5])
    alive = []
    for x, y, v in meteors:
        y += v * dt * sp
        if y < 1.3:
            alive.append([x, y, v])
    st["meteors"] = alive
    a = fx["c1"]
    b = P.scale(fx["c2"], 0.12)
    out = {}
    for e in P.LAYOUT:
        kx, ky = P.kx(e), P.ky(e)
        glow = 0.0
        for x, y, _v in alive:
            behind = y - ky  # trail extends upward behind the falling head
            if behind >= -0.02:
                d = ((kx - x) / 0.05) ** 2 + (max(0.0, behind) / 0.3) ** 2
                glow = max(glow, 1.0 - d ** 0.5)
        out[e[6]] = P.mix(b, a, P.clamp01(glow))
    return ("keys", out)


FRAMES = {
    "wave": _frame_wave, "spin": _frame_spin, "gradient": _frame_gradient,
    "scanner": _frame_scanner, "fire": _frame_fire, "stars": _frame_stars,
    "type": _frame_type, "eq": _frame_eq, "pulse": _frame_pulse,
    "cycle": _frame_cycle, "meteor": _frame_meteor,
}


# ---------------------------------------------------------------- key input
_EVDEV_MAP = {
    "KEY_ESC": "Esc", "KEY_F1": "F1", "KEY_F2": "F2", "KEY_F3": "F3",
    "KEY_F4": "F4", "KEY_F5": "F5", "KEY_F6": "F6", "KEY_F7": "F7",
    "KEY_F8": "F8", "KEY_F9": "F9", "KEY_F10": "F10", "KEY_F11": "F11",
    "KEY_F12": "F12", "KEY_GRAVE": "`", "KEY_1": "1", "KEY_2": "2",
    "KEY_3": "3", "KEY_4": "4", "KEY_5": "5", "KEY_6": "6", "KEY_7": "7",
    "KEY_8": "8", "KEY_9": "9", "KEY_0": "0", "KEY_MINUS": "-",
    "KEY_EQUAL": "=", "KEY_BACKSPACE": "Backspace", "KEY_DELETE": "Delete",
    "KEY_TAB": "Tab", "KEY_Q": "Q", "KEY_W": "W", "KEY_E": "E",
    "KEY_R": "R", "KEY_T": "T", "KEY_Y": "Y", "KEY_U": "U", "KEY_I": "I",
    "KEY_O": "O", "KEY_P": "P", "KEY_LEFTBRACE": "[", "KEY_RIGHTBRACE": "]",
    "KEY_BACKSLASH": "\\", "KEY_PAGEUP": "PgUp", "KEY_CAPSLOCK": "CapsLock",
    "KEY_A": "A", "KEY_S": "S", "KEY_D": "D", "KEY_F": "F", "KEY_G": "G",
    "KEY_H": "H", "KEY_J": "J", "KEY_K": "K", "KEY_L": "L",
    "KEY_SEMICOLON": ";", "KEY_APOSTROPHE": "'", "KEY_ENTER": "Enter",
    "KEY_LEFTSHIFT": "LShift", "KEY_Z": "Z", "KEY_X": "X", "KEY_C": "C",
    "KEY_V": "V", "KEY_B": "B", "KEY_N": "N", "KEY_M": "M",
    "KEY_COMMA": ",", "KEY_DOT": ".", "KEY_SLASH": "/",
    "KEY_RIGHTSHIFT": "RShift", "KEY_UP": "Up", "KEY_LEFTCTRL": "LCtrl",
    "KEY_LEFTMETA": "LWin", "KEY_LEFTALT": "LAlt", "KEY_SPACE": "Space",
    "KEY_RIGHTCTRL": "RCtrl", "KEY_FN": "FN", "KEY_LEFT": "Left",
    "KEY_DOWN": "Down", "KEY_RIGHT": "Right", "KEY_PAGEDOWN": "PgDn",
    "KEY_END": "End",
}


class TypingSource:
    """Feeds (x, y, t) ripples: evdev when usable, else auto-ripples."""

    def __init__(self):
        self.events: list = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.mode = "auto"

    def start(self):
        if _try_evdev(self):
            self.mode = "evdev"
        else:
            self.mode = "auto"
            self._thread = threading.Thread(target=self._auto, daemon=True)
            self._thread.start()

    def _auto(self):
        while not self._stop.wait(0.4):
            e = random.choice(P.LAYOUT)
            with self._lock:
                self.events.append((P.kx(e), P.ky(e), time.monotonic()))

    def drain(self, now):
        with self._lock:
            evs = self.events
            self.events = []
        return [(x, y, now - (time.monotonic() - t)) for x, y, t in evs]

    def stop(self):
        self._stop.set()


def _try_evdev(src: TypingSource) -> bool:
    try:
        import evdev
    except ImportError:
        return False
    devs = []
    try:
        for path in evdev.list_devices():
            try:
                d = evdev.InputDevice(path)
            except OSError:
                continue
            caps = d.capabilities()
            keys = caps.get(evdev.ecodes.EV_KEY, [])
            flat = set()
            for k in keys:
                if isinstance(k, (list, tuple)):
                    flat.update(k)
                else:
                    flat.add(k)
            if evdev.ecodes.KEY_A in flat and evdev.ecodes.KEY_SPACE in flat:
                devs.append(d)
    except Exception:
        return False
    if not devs:
        return False

    def _loop():
        from evdev import ecodes
        for d in devs:
            try:
                d.grab()
            except OSError:
                pass
        try:
            while not src._stop.is_set():
                for d in devs:
                    try:
                        ev = d.read_one()
                    except OSError:
                        ev = None
                    if ev is None or ev.type != ecodes.EV_KEY:
                        continue
                    if ev.value != 1:  # key down only
                        continue
                    try:
                        name = ecodes.KEY[ev.code]
                    except KeyError:
                        continue
                    disp = _EVDEV_MAP.get(name)
                    if not disp:
                        continue
                    try:
                        led = P.resolve_key(disp)
                    except KeyError:
                        continue
                    e = P.LED_BY_POS.get(led)
                    if e is None:
                        continue
                    with src._lock:
                        src.events.append(
                            (P.kx(e), P.ky(e), time.monotonic()))
        finally:
            for d in devs:
                try:
                    d.ungrab()
                except OSError:
                    pass

    src._thread = threading.Thread(target=_loop, daemon=True)
    src._thread.start()
    return True


# ---------------------------------------------------------------- runner
class AnimRunner:
    def __init__(self, kind, dev, anim_id: str, speed: float = 1.0,
                 brightness: float = 1.0, c1=(255, 42, 0),
                 c2=(0, 80, 255), gain: float = 1.0,
                 source: str = "monitor", duration: float = 0,
                 verbose: bool = False, device: str | None = None,
                 eq_style: str = "rainbow", peak_fall: bool = True):
        if anim_id not in FRAMES:
            raise ValueError(f"unknown animation {anim_id!r}")
        self.kind = kind
        self.dev = dev
        self.anim_id = anim_id
        self.stop_flag = threading.Event()
        self.fx = {"speed": speed, "c1": tuple(map(float, c1)),
                   "c2": tuple(map(float, c2)), "gain": gain,
                   "feed": None, "source": source, "device": device,
                   "eq_style": eq_style, "peak_fall": peak_fall}
        self.brightness = brightness
        self.duration = duration
        self.verbose = verbose
        self._feed = None
        self._typing = None

    def run(self, restore):
        from .audio import AudioFeed
        if self.anim_id in AUDIO_ANIMS:
            self._feed = AudioFeed(self.fx["source"], self.fx["gain"],
                                   self.fx["device"])
            self._feed.start()
            self.fx["feed"] = self._feed
            if self.verbose:
                print(f"[anim] audio in: {self._feed.device_name} "
                      f"(gain {self.fx['gain']})")
        if self.anim_id == TYPING_ANIM:
            self._typing = TypingSource()
            self._typing.start()
            if self.verbose:
                print(f"[anim] typing input: {self._typing.mode}")
        frame = FRAMES[self.anim_id]
        st: dict = {}
        t0 = time.monotonic()
        last = t0
        tt = 0.0
        try:
            while not self.stop_flag.is_set():
                if self.duration and time.monotonic() - t0 >= self.duration:
                    break
                now = time.monotonic()
                dt = min(0.2, now - last)
                last = now
                tt += dt * self.fx["speed"]
                st["now"] = now - t0
                if self._feed is not None:
                    self._feed.poll()
                if self._typing is not None:
                    for rx, ry, rt in self._typing.drain(st["now"]):
                        st.setdefault("rip", []).append((rx, ry, rt))
                try:
                    kind, payload = frame(tt, dt, st, self.fx)
                except Exception as e:
                    raise CommError(f"animation error: {e}")
                self._emit(kind, payload)
                if self.kind == "2g":
                    self.dev.queue = []
                wait = P.FRAME_INTERVAL_S - (time.monotonic() - now)
                if wait > 0:
                    self.stop_flag.wait(wait)
        finally:
            t0 = time.monotonic() if self.verbose else 0
            if self._feed is not None:
                self._feed.stop()
            if self.verbose:
                print(f"[anim] +{time.monotonic() - t0:.2f}s audio stopped")
            if self._typing is not None:
                self._typing.stop()
            if self.verbose:
                print(f"[anim] +{time.monotonic() - t0:.2f}s input stopped")
            try:
                restore()
            except CommError as e:
                if str(e) == "interrupted":
                    print("restore skipped (interrupted)")
                else:
                    print(f"warning: lighting restore failed ({e}) — the "
                          "keyboard may be asleep; it keeps its stored "
                          "lighting, so wake it and re-run if it looks wrong")
            if self.verbose:
                print(f"[anim] +{time.monotonic() - t0:.2f}s restore done")

    def _emit(self, kind, payload):
        if kind == "all":
            rgb = P.to_int8(P.scale(payload, self.brightness))
            if self.kind == "2g":
                self.dev.send_realtime(2, bytes(rgb))
            else:
                self._emit_wired({led: tuple(rgb)
                                  for led in P.WIRELESS_TO_WIRED_PLANE})
        else:
            scaled = {led: P.to_int8(P.scale(c, self.brightness))
                      for led, c in payload.items()}
            if self.kind == "2g":
                enc = encode_groups(scaled)
                if enc:
                    self.dev.send_realtime(1, enc)
                else:
                    self.dev.send_realtime(2, bytes((0, 0, 0)))
            else:
                self._emit_wired(scaled)

    def _emit_wired(self, scaled: dict):
        from . import transport as T
        from .transport import ABORT
        plane = {}
        for led, rgb in scaled.items():
            pos = P.WIRELESS_TO_WIRED_PLANE.get(led)
            if pos is not None:
                plane[pos] = tuple(rgb)
        pkt = T.u_build_direct_frame(plane)
        # f87-style recovery: settle + exponential backoff, abort only on
        # a dead link. Direct mode re-engages on the next good frame and
        # auto-reverts when we stop, so transient errors are harmless.
        backoff = 0.02
        for _ in range(7):
            if ABORT.is_set():
                raise CommError("interrupted")
            try:
                self.dev.send(pkt)
                self._wFails = 0
                break
            except CommError as e:
                if str(e) == "interrupted" or ABORT.is_set():
                    raise
                self._wFails = getattr(self, "_wFails", 0) + 1
                if self._wFails > 30:
                    raise CommError("wired link lost (30 failed frames)")
                time.sleep(backoff)
                backoff = min(backoff * 2, 0.64)
        time.sleep(P.U_CMD_DELAY_S)

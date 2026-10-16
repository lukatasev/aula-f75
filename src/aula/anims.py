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
    "meteor": ("Meteor", "a comet shower with fading trails", False),
    "matrix": ("Matrix rain", "green code raining down", False),
    "plasma": ("Plasma", "slow morphing color blobs", False),
    "radar": ("Radar sweep", "a beam circling from the center", False),
    "lightning": ("Lightning", "random bolts flashing", False),
    "vu": ("VU meter", "loudness bar with peak cap", True),
    "energy": ("Energy", "the board breathes with loudness", True),
    "freqmap": ("Frequency map", "each pitch glowing at its key", True),
    "life": ("Game of Life", "conway cells evolving on the keys", False),
    "keyheat": ("Key heat", "keys glow hotter the more you type", False),
    "typewriter": ("Typewriter", "a cursor runs as you type", False),
}
AUDIO_ANIMS = {k for k, v in ANIM_INFO.items() if v[2]}
TYPING_ANIMS = {"type", "keyheat", "typewriter"}


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


_LED_XY = None


def _nearest_led(x, y):
    global _LED_XY
    if _LED_XY is None:
        _LED_XY = [(e[6], P.kx(e), P.ky(e)) for e in P.LAYOUT]
    return min(_LED_XY, key=lambda t: (t[1] - x) ** 2 + (t[2] - y) ** 2)[0]


def _fresh_keys(st, window):
    now = st.get("now", 0.0)
    evs = [ev for ev in st.get("keys", []) if now - ev[2] < window]
    st["keys"] = evs
    return evs


def _frame_keyheat(_tt, dt, st, fx):
    sp = fx["speed"]
    evs = _fresh_keys(st, 30.0)
    heat = st.setdefault("heat", {})
    for rx, ry, _rt in evs:
        led = _nearest_led(rx, ry)
        heat[led] = min(1.5, heat.get(led, 0.0) + 0.6)
    for led in list(heat):
        heat[led] -= dt * 0.25 * sp
        if heat[led] <= 0:
            del heat[led]
    st["keys"] = []
    a = fx["c1"]
    b = P.scale(fx["c2"], 0.1)
    return ("keys", {e[6]: P.mix(b, a, P.clamp01(heat.get(e[6], 0.0)))
                     for e in P.LAYOUT})


def _frame_typewriter(_tt, _dt, st, fx):
    path = _snake_path()
    n = len(path)
    evs = _fresh_keys(st, 30.0)
    if evs:
        st["cursor"] = (st.get("cursor", 0) + len(evs)) % n
        flash = st.setdefault("flash", {})
        for rx, ry, _rt in evs:
            flash[_nearest_led(rx, ry)] = 1.0
        st["keys"] = []
    flash = st.get("flash", {})
    for led in list(flash):
        flash[led] -= 0.05
        if flash[led] <= 0:
            del flash[led]
    a = fx["c1"]
    b = P.scale(fx["c2"], 0.08)
    cur = path[st.get("cursor", 0) % n]
    out = {}
    for e in P.LAYOUT:
        if e[6] == cur:
            out[e[6]] = (255.0, 255.0, 255.0)
        elif e[6] in flash:
            out[e[6]] = P.scale(a, P.clamp01(flash[e[6]]))
        else:
            out[e[6]] = b
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


def _frame_cycle(tt, _dt, _st, _fx):
    return ("all", P.hsv(tt * 0.06, 1, 1))


# ---------------------------------------------------------------- custom set
def _frame_matrix(_tt, dt, st, fx):
    import random
    sp = fx["speed"]
    drops = st.setdefault("drops", [])
    if random.random() < dt * 6 * sp:
        drops.append([random.random(), -0.1, 0.6 + random.random() * 0.8])
    alive = []
    for x, y, v in drops:
        y += v * dt * sp
        if y < 1.4:
            alive.append([x, y, v])
    st["drops"] = alive
    a = (120.0, 255.0, 120.0)
    b = (0.0, 8.0, 0.0)
    out = {}
    for e in P.LAYOUT:
        kx, ky = P.kx(e), P.ky(e)
        v = 0.0
        for x, y, _ in alive:
            if abs(kx - x) < 0.035:
                behind = y - ky
                if behind >= 0:
                    v = max(v, 1.0 - behind / 0.5)
        out[e[6]] = P.mix(b, a, P.clamp01(v))
    return ("keys", out)


def _frame_plasma(tt, _dt, _st, fx):
    a, b = fx["c1"], fx["c2"]
    out = {}
    for e in P.LAYOUT:
        x, y = P.kx(e) * 6.283, P.ky(e) * 6.283
        v = (math.sin(x * 0.8 + tt * 0.7) + math.sin(y * 1.1 - tt * 0.9) +
             math.sin((x + y) * 0.7 + tt * 0.5)) / 6.0 + 0.5
        out[e[6]] = P.mix(a, b, P.clamp01(v))
    return ("keys", out)


def _frame_radar(tt, _dt, _st, fx):
    ang = tt * 1.5
    a = fx["c1"]
    b = P.scale(fx["c2"], 0.1)
    out = {}
    for e in P.LAYOUT:
        dx, dy = P.kx(e) - 0.5, (P.ky(e) - 0.5) * 0.6
        ea = math.atan2(dy, dx)
        diff = abs((ea - ang + math.pi) % (2 * math.pi) - math.pi)
        r = min(1.0, math.hypot(dx, dy) * 2)
        v = math.exp(-(diff ** 2) / 0.15) * (1 - r * 0.5)
        out[e[6]] = P.mix(b, a, P.clamp01(v))
    return ("keys", out)


_SNAKE_PATH = None


def _snake_path():
    global _SNAKE_PATH
    if _SNAKE_PATH is None:
        rows = []
        for e in sorted(P.LAYOUT, key=lambda e: e[3]):
            if not rows or abs(e[3] - rows[-1][0][3]) > 15:
                rows.append([])
            rows[-1].append(e)
        path = []
        for i, row in enumerate(rows):
            row = sorted(row, key=lambda e: e[2], reverse=(i % 2 == 0))
            path.extend(x[6] for x in row)
        _SNAKE_PATH = path
    return _SNAKE_PATH


def _frame_lightning(_tt, dt, st, fx):
    import random
    sp = fx["speed"]
    bolts = st.setdefault("bolts", [])
    if random.random() < dt * 0.8 * sp and len(bolts) < 3:
        x = random.random()
        pts, y = [], -0.05
        while y < 1.1:
            pts.append((x + random.uniform(-0.03, 0.03), y))
            y += 0.08 + random.random() * 0.08
        bolts.append([pts, 1.0])
    alive = []
    for pts, life in bolts:
        life -= dt * 2.5 * sp
        if life > 0:
            alive.append([pts, life])
    st["bolts"] = alive
    a = fx["c1"]
    out = {}
    for e in P.LAYOUT:
        kx, ky = P.kx(e), P.ky(e)
        v = 0.0
        for pts, life in alive:
            d = min(math.hypot(kx - px, ky - py) for px, py in pts)
            v = max(v, max(0.0, 1.0 - d / 0.06) * min(1.0, life * 2))
        v = P.clamp01(v)
        base = P.scale(a, v)
        out[e[6]] = P.mix(base, (255.0, 255.0, 255.0),
                           P.clamp01((v - 0.6) / 0.4))
    return ("keys", out)


def _frame_vu(_tt, dt, st, fx):
    feed = fx["feed"]
    raw = P.clamp01(feed.band(60, 8000) * fx["gain"] - 0.05)
    sp = fx["speed"]
    sm = st.get("sm", 0.0)
    sm += (raw - sm) * min(1.0, dt * (10 if raw > sm else 3) * sp)
    st["sm"] = sm
    peak = max(sm, st.get("peak", 0.0) - dt * 0.25 * sp)
    st["peak"] = peak
    out = {}
    for e in P.LAYOUT:
        x = P.kx(e)
        if x <= sm + 0.01:
            out[e[6]] = P.hsv(0.33 * (1 - x), 1, 1)
        elif abs(x - peak) < 0.025:
            out[e[6]] = (255.0, 255.0, 255.0)
        else:
            out[e[6]] = (0.0, 0.0, 0.0)
    return ("keys", out)


def _frame_energy(_tt, dt, st, fx):
    feed = fx["feed"]
    raw = P.clamp01(feed.band(40, 600) * fx["gain"] - 0.05)
    sp = fx["speed"]
    sm = st.get("sm", 0.0)
    sm += (raw - sm) * min(1.0, dt * (8 if raw > sm else 2) * sp)
    st["sm"] = sm
    return ("all", P.scale(fx["c1"], 0.03 + 0.97 * sm))


def _frame_freqmap(_tt, _dt, _st, fx):
    feed = fx["feed"]
    cols = 14
    lv = [P.clamp01(feed.band(60 * 150 ** (c / cols),
                               60 * 150 ** ((c + 1) / cols)) *
                     fx["gain"] - 0.08) for c in range(cols)]
    out = {}
    for e in P.LAYOUT:
        col = min(cols - 1, int(P.kx(e) * cols))
        out[e[6]] = P.hsv(0.66 * (1 - col / (cols - 1)), 1, lv[col])
    return ("keys", out)


_GOL_GRID = None


def _gol_grid():
    global _GOL_GRID
    if _GOL_GRID is None:
        rows = []
        for e in sorted(P.LAYOUT, key=lambda e: e[3]):
            if not rows or abs(e[3] - rows[-1][0][3]) > 14:
                rows.append([])
            rows[-1].append(e)
        _GOL_GRID = [sorted(row, key=lambda e: e[2]) for row in rows]
    return _GOL_GRID


def _frame_life(_tt, dt, st, fx):
    import random
    grid = _gol_grid()
    acc = st.get("acc", 0.0) + dt * fx["speed"]
    live = st.get("live")
    if live is None or not live or acc > 0.8:
        if live is None or not live:
            live = {(r, c) for r in range(len(grid))
                    for c in range(len(grid[r]))
                    if random.random() < 0.25}
            st["ages"] = {cell: 0 for cell in live}
        else:
            new = set()
            for r in range(len(grid)):
                for c in range(len(grid[r])):
                    n = sum((rr, cc) in live
                            for rr in (r - 1, r, r + 1)
                            for cc in (c - 1, c, c + 1)
                            if (rr, cc) != (r, c) and 0 <= rr < len(grid)
                            and 0 <= cc < len(grid[rr]))
                    if (r, c) in live:
                        if n in (2, 3):
                            new.add((r, c))
                    elif n == 3:
                        new.add((r, c))
            hist = st.get("hist", [])
            if frozenset(new) in hist or not new:
                # loop detected (blinkers flip A->B->A, stillness never
                # triggers) or died out: reseed fresh soup
                new = {(r, c) for r in range(len(grid))
                       for c in range(len(grid[r]))
                       if random.random() < 0.25}
                hist = []
            else:
                hist = (hist + [frozenset(new)])[-6:]
            st["hist"] = hist
            ages = st.get("ages", {})
            st["ages"] = {cell: ages.get(cell, 0) + 1 if cell in live else 0
                          for cell in new}
            live = new
        st["live"] = live
    if live is None or not live or acc > 0.8:
        st["acc"] = 0.0
    else:
        st["acc"] = acc
    a = fx["c1"]
    b = P.scale(fx["c2"], 0.08)
    ages = st.get("ages", {})
    out = {}
    for r, row in enumerate(grid):
        for c, e in enumerate(row):
            if (r, c) in live:
                out[e[6]] = P.scale(a, max(0.35, 1.0 - ages.get((r, c), 0) * 0.15))
            else:
                out[e[6]] = b
    return ("keys", out)


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
    "matrix": _frame_matrix, "plasma": _frame_plasma, "radar": _frame_radar,
    "lightning": _frame_lightning,
    "vu": _frame_vu, "energy": _frame_energy, "freqmap": _frame_freqmap,
    "life": _frame_life,
    "keyheat": _frame_keyheat, "typewriter": _frame_typewriter,
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
        # NOTE: no grab() here — passive monitoring only. Grabbing would
        # steal the keyboard exclusively and the user couldn't type.
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
        if self.anim_id in TYPING_ANIMS:
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
                    evs = self._typing.drain(st["now"])
                    st.setdefault("rip", []).extend(evs)
                    if self.anim_id in ("keyheat", "typewriter"):
                        st.setdefault("keys", []).extend(evs)
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

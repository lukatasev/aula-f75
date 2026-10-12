"""Shared protocol constants, layout tables and helpers.

Ports src/protocol.js, src/effects.js, src/layout.js, src/keycodes.js
(AULA-F75-configurator, 2.4GHz dongle 3554:fa09) plus the wired
SinoWealth 258A:010C tables from other/old/aula.py.
"""

from __future__ import annotations

import math

# ---------------------------------------------------------------- 2.4GHz USB
W_VID = 0x3554
W_PID = 0xFA09
RID = 0x13
CHUNK = 14
LED_SIZE = 128
USAGE_PAGE = 0xFF02
USAGE = 0x02

CMD_SET_MATRIX = 0x01
CMD_SET_COLORS = 0x02
CMD_SET_LED = 0x04
CMD_SET_RGBTAB = 0x09
CMD_GET_ONLINE = 0x07
CMD_GET_MATRIX = 0x41
CMD_GET_COLORS = 0x42
CMD_GET_LED = 0x44
CMD_GET_RGBTAB = 0x49
CMD_GET_STATUS = 0x4A
CMD_EVENT = 0x0A
CMD_REALTIME = 0x88

OFF_CUSTOM = 0x09
OFF_MODE = 0x0A
OFF_SLEEP = 0x18
OFF_SLOTS = 0x3A
MODE_CUSTOM_W = 21
PACKET_GAP_S = 0.010
RT_MAX = 200
FRAME_INTERVAL_S = 0.066  # ~15 fps, matches web client pacing

# ---------------------------------------------------------------- wired USB
U_VID = 0x258A
U_PID = 0x010C
U_IFACE = 1
U_REPORT_ID = 0x06
U_CMD_LED_PLANAR = 0x06
U_CMD_LED_CUSTOM = 0x0A
U_CMD_CONFIG_READ = 0x84
U_CMD_CONFIG_WRITE = 0x04
U_REPORT_SIZE = 520
U_CONFIG_RESP_SIZE = 136
U_CUSTOM_TERM = 514
U_CFG_CUSTOM_FLAG = 17
U_CFG_EFFECT_ID = 18
U_MODE_STATIC = 1
U_MODE_CUSTOM = 18
U_LED_BUFFER_KEYS = 0x7A
U_PLANE_SIZE = 126
U_PLANE_OFFSET = 8
U_CMD_DELAY_S = 0.005

# ---------------------------------------------------------------- effects
# slot == index in this list (mirrors effects.js .map((e, slot) => ...))
EFFECTS = [
    {"mode": 1, "speed": False, "color": True, "multi": True,
     "name": "static", "desc": "Static"},
    {"mode": 2, "speed": True, "color": True, "multi": True,
     "name": "breathing", "desc": "Breathing"},
    {"mode": 3, "speed": True, "color": False, "multi": False,
     "name": "rainbow", "desc": "Rainbow"},
    {"mode": 4, "speed": True, "color": True, "multi": True,
     "name": "flash-away", "desc": "Flash away"},
    {"mode": 5, "speed": True, "color": True, "multi": True,
     "name": "raindrops", "desc": "Raindrops"},
    {"mode": 6, "speed": True, "color": True, "multi": True,
     "name": "rainbow-wheel", "desc": "Rainbow wheel"},
    {"mode": 7, "speed": True, "color": True, "multi": True,
     "name": "ripples", "desc": "Ripples"},
    {"mode": 8, "speed": True, "color": True, "multi": True,
     "name": "stars", "desc": "Twinkling stars"},
    {"mode": 9, "missing": True, "name": "shadow", "desc": "Shadow"},
    {"mode": 10, "speed": True, "color": True, "multi": True,
     "name": "snake", "desc": "Snake"},
    {"mode": 11, "speed": True, "color": True, "multi": True,
     "name": "neon-stream", "desc": "Neon stream"},
    {"mode": 12, "speed": True, "color": True, "multi": True,
     "name": "reactive", "desc": "Reactive"},
    {"mode": 13, "speed": True, "color": True, "multi": True,
     "name": "sine-wave", "desc": "Sine wave"},
    {"mode": 14, "missing": True, "name": "scanning", "desc": "Scanning"},
    {"mode": 15, "speed": True, "color": False, "multi": False,
     "name": "windmill", "desc": "Windmill"},
    {"mode": 16, "speed": True, "color": False, "multi": False,
     "name": "waterfall", "desc": "Color waterfall"},
    {"mode": 17, "speed": True, "color": False, "multi": False,
     "name": "blossom", "desc": "Blossom"},
    {"mode": 18, "missing": True, "firmware_only": True,
     "name": "storm", "desc": "Storm"},
    {"mode": 21, "speed": False, "color": False, "multi": False,
     "custom": True, "name": "custom", "desc": "Custom (per-key)"},
]
for _slot, _e in enumerate(EFFECTS):
    _e["slot"] = _slot
EFFECT_OFF = {"mode": 0, "slot": -1, "off": True, "name": "off",
              "desc": "Off"}
EFFECT_BY_MODE = {e["mode"]: e for e in EFFECTS}
EFFECT_BY_NAME = {e["name"]: e for e in EFFECTS}

SLEEP_TABLE = [(60, 2), (90, 3), (120, 4), (180, 6), (240, 8),
               (300, 10), (600, 20), (900, 30), (1200, 40)]
SLEEP_SECS_TO_HW = dict(SLEEP_TABLE)
SLEEP_HW_TO_SECS = {hw: s for s, hw in SLEEP_TABLE}


def effect_of(mode: int):
    if mode == 0:
        return EFFECT_OFF
    return EFFECT_BY_MODE.get(mode)


def slot_byte(slot: int, i: int) -> int:
    return OFF_SLOTS + 2 * slot + i


# ---------------------------------------------------------------- F75 layout
# (matrix position k, display name, x, y, w, h, led index)
LAYOUT = [
    (1, "Esc", 30, 30, 25, 27, 0),
    (2, "F1", 107, 30, 25, 27, 12),
    (3, "F2", 144, 30, 25, 27, 18),
    (4, "F3", 183, 30, 25, 27, 24),
    (5, "F4", 222, 30, 25, 27, 30),
    (6, "F5", 269, 30, 25, 27, 36),
    (7, "F6", 305, 30, 25, 27, 42),
    (8, "F7", 343, 30, 25, 27, 48),
    (9, "F8", 388, 30, 25, 27, 54),
    (10, "F9", 439, 30, 25, 27, 60),
    (11, "F10", 477, 30, 25, 27, 66),
    (12, "F11", 516, 30, 25, 27, 72),
    (13, "F12", 555, 30, 25, 27, 78),
    (14, "End", 605, 195, 25, 27, 88),
    (15, "`", 31, 81, 25, 27, 1),
    (16, "1", 70, 81, 25, 27, 7),
    (17, "2", 108, 81, 25, 27, 13),
    (18, "3", 147, 81, 25, 27, 19),
    (19, "4", 184, 81, 25, 27, 25),
    (20, "5", 223, 81, 25, 27, 31),
    (21, "6", 262, 81, 25, 27, 37),
    (22, "7", 300, 80, 25, 27, 43),
    (23, "8", 338, 81, 25, 27, 49),
    (24, "9", 377, 81, 25, 27, 55),
    (25, "0", 416, 81, 25, 27, 61),
    (26, "-", 453, 81, 25, 27, 67),
    (27, "=", 491, 81, 25, 27, 73),
    (28, "Backspace", 531, 81, 60, 27, 79),
    (29, "Delete", 604, 81, 25, 27, 85),
    (30, "Tab", 34, 120, 44, 27, 2),
    (31, "Q", 89, 119, 25, 27, 8),
    (32, "W", 127, 119, 25, 27, 14),
    (33, "E", 165, 119, 25, 27, 20),
    (34, "R", 204, 119, 25, 27, 26),
    (35, "T", 242, 119, 25, 27, 32),
    (36, "Y", 280, 119, 25, 27, 38),
    (37, "U", 318, 119, 25, 27, 44),
    (38, "I", 356, 119, 25, 27, 50),
    (39, "O", 395, 119, 25, 27, 56),
    (40, "P", 433, 119, 25, 27, 62),
    (41, "[", 471, 120, 25, 27, 68),
    (42, "]", 509, 119, 25, 27, 74),
    (43, "\\", 549, 119, 44, 27, 80),
    (44, "PgUp", 605, 120, 25, 27, 86),
    (45, "CapsLock", 33, 158, 52, 27, 3),
    (46, "A", 98, 158, 25, 27, 9),
    (47, "S", 136, 158, 25, 27, 15),
    (48, "D", 174, 158, 25, 27, 21),
    (49, "F", 213, 158, 25, 27, 27),
    (50, "G", 252, 158, 25, 27, 33),
    (51, "H", 290, 158, 25, 27, 39),
    (52, "J", 327, 158, 25, 27, 45),
    (53, "K", 366, 158, 25, 27, 51),
    (54, "L", 405, 158, 25, 27, 57),
    (55, ";", 443, 158, 25, 27, 63),
    (56, "'", 481, 158, 25, 27, 69),
    (57, "Enter", 521, 158, 70, 27, 81),
    (58, "LShift", 33, 195, 72, 27, 4),
    (59, "Z", 116, 195, 25, 27, 10),
    (60, "X", 155, 195, 25, 27, 16),
    (61, "C", 193, 195, 25, 27, 22),
    (62, "V", 232, 195, 25, 27, 28),
    (63, "B", 270, 196, 25, 27, 34),
    (64, "N", 309, 195, 25, 27, 40),
    (65, "M", 347, 195, 25, 27, 46),
    (66, ",", 384, 195, 25, 27, 52),
    (67, ".", 424, 195, 25, 27, 58),
    (68, "/", 463, 195, 25, 27, 64),
    (69, "RShift", 502, 195, 56, 27, 70),
    (70, "Up", 567, 195, 25, 27, 82),
    (71, "LCtrl", 34, 234, 35, 27, 5),
    (72, "LWin", 79, 234, 35, 27, 11),
    (73, "LAlt", 122, 235, 35, 27, 17),
    (74, "Space", 174, 235, 226, 27, 35),
    (75, "RCtrl", 463, 236, 34, 27, 59),
    (76, "FN", 414, 235, 35, 27, 53),
    (77, "Left", 529, 234, 25, 27, 77),
    (78, "Down", 568, 234, 25, 27, 83),
    (79, "Right", 605, 234, 25, 27, 89),
    (80, "PgDn", 604, 159, 25, 27, 87),
]

_BOUNDS_X0 = min(k[2] for k in LAYOUT)
_BOUNDS_Y0 = min(k[3] for k in LAYOUT)
_BOUNDS_W = max(k[2] + k[4] for k in LAYOUT) - _BOUNDS_X0
_BOUNDS_H = max(k[3] + k[5] for k in LAYOUT) - _BOUNDS_Y0
LED_BY_POS = {}   # led index -> layout entry
for _entry in LAYOUT:
    LED_BY_POS[_entry[6]] = _entry


def kx(entry) -> float:
    return (entry[2] + entry[4] / 2 - _BOUNDS_X0) / _BOUNDS_W


def ky(entry) -> float:
    return (entry[3] + entry[5] / 2 - _BOUNDS_Y0) / _BOUNDS_H


# Extra aliases (lowercase, punctuation stripped) -> display name
_KEY_ALIASES = {
    "esc": "Esc", "escape": "Esc",
    "bksp": "Backspace", "backspace": "Backspace",
    "caps": "CapsLock", "capslock": "CapsLock", "caps-lock": "CapsLock",
    "lshft": "LShift", "lshift": "LShift", "shift": "LShift",
    "rshft": "RShift", "rshift": "RShift",
    "lctrl": "LCtrl", "lctl": "LCtrl", "ctrl": "LCtrl", "control": "LCtrl",
    "rctrl": "RCtrl", "rctl": "RCtrl",
    "lwin": "LWin", "win": "LWin", "super": "LWin", "meta": "LWin",
    "lalt": "LAlt", "alt": "LAlt",
    "space": "Space", "spc": "Space",
    "enter": "Enter", "return": "Enter",
    "del": "Delete", "delete": "Delete",
    "pgup": "PgUp", "pageup": "PgUp", "pg-up": "PgUp",
    "pgdn": "PgDn", "pagedown": "PgDn", "pg-dn": "PgDn",
    "up": "Up", "down": "Down", "left": "Left", "right": "Right",
    "fn": "FN",
    "grave": "`", "backquote": "`",
    "minus": "-", "dash": "-", "hyphen": "-",
    "equal": "=", "equals": "=", "plus": "=",
    "lbrkt": "[", "lbracket": "[", "rbracket": "]", "rbrkt": "]",
    "bslsh": "\\", "backslash": "\\",
    "semi": ";", "semicolon": ";",
    "quote": "'", "apostrophe": "'",
    "comma": ",", "dot": ".", "period": ".", "stop": ".",
    "slash": "/",
}
NAME_TO_LED: dict = {}
for (_k, _n, *_rest, _led) in LAYOUT:
    NAME_TO_LED[_n.lower()] = _led
NAME_TO_LED.update({a: NAME_TO_LED[n.lower()] for a, n in
                    _KEY_ALIASES.items() if n.lower() in NAME_TO_LED})


def resolve_key(name: str) -> int:
    """Key display name / alias -> led index. Raises KeyError."""
    key = name.strip().lower()
    if key in NAME_TO_LED:
        return NAME_TO_LED[key]
    raise KeyError(f"unknown key: {name!r}")


def led_name(led: int) -> str:
    e = LED_BY_POS.get(led)
    return e[1] if e else f"led{led}"


# ---------------------------------------------------------------- key codes
HID = {
    0x04: "A", 0x05: "B", 0x06: "C", 0x07: "D", 0x08: "E", 0x09: "F",
    0x0A: "G", 0x0B: "H", 0x0C: "I", 0x0D: "J", 0x0E: "K", 0x0F: "L",
    0x10: "M", 0x11: "N", 0x12: "O", 0x13: "P", 0x14: "Q", 0x15: "R",
    0x16: "S", 0x17: "T", 0x18: "U", 0x19: "V", 0x1A: "W", 0x1B: "X",
    0x1C: "Y", 0x1D: "Z", 0x1E: "1", 0x1F: "2", 0x20: "3", 0x21: "4",
    0x22: "5", 0x23: "6", 0x24: "7", 0x25: "8", 0x26: "9", 0x27: "0",
    0x28: "Enter", 0x29: "Esc", 0x2A: "Backspace", 0x2B: "Tab",
    0x2C: "Space", 0x2D: "-", 0x2E: "=", 0x2F: "[", 0x30: "]",
    0x31: "\\", 0x32: "# (ISO)", 0x33: ";", 0x34: "'", 0x35: "`",
    0x36: ",", 0x37: ".", 0x38: "/", 0x39: "CapsLock", 0x3A: "F1",
    0x3B: "F2", 0x3C: "F3", 0x3D: "F4", 0x3E: "F5", 0x3F: "F6",
    0x40: "F7", 0x41: "F8", 0x42: "F9", 0x43: "F10", 0x44: "F11",
    0x45: "F12", 0x46: "PrintScreen", 0x47: "ScrollLock", 0x48: "Pause",
    0x49: "Insert", 0x4A: "Home", 0x4B: "PgUp", 0x4C: "Delete",
    0x4D: "End", 0x4E: "PgDn", 0x4F: "Right", 0x50: "Left",
    0x51: "Down", 0x52: "Up", 0x53: "NumLock", 0x54: "Num /",
    0x55: "Num *", 0x56: "Num -", 0x57: "Num +", 0x58: "Num Enter",
    0x59: "Num 1", 0x5A: "Num 2", 0x5B: "Num 3", 0x5C: "Num 4",
    0x5D: "Num 5", 0x5E: "Num 6", 0x5F: "Num 7", 0x60: "Num 8",
    0x61: "Num 9", 0x62: "Num 0", 0x63: "Num .", 0x64: "\\ (ISO)",
    0x65: "Menu", 0x68: "F13", 0x69: "F14", 0x6A: "F15", 0x6B: "F16",
    0x6C: "F17", 0x6D: "F18", 0x6E: "F19", 0x6F: "F20", 0x70: "F21",
    0x71: "F22", 0x72: "F23", 0x73: "F24",
}
HID_NAME_TO_CODE = {v.lower(): k for k, v in HID.items()}
HID_NAME_TO_CODE.update({"esc": 0x29, "bksp": 0x2A, "del": 0x4C,
                         "ins": 0x49, "caps": 0x39})

MODS = [  # (bit, short)
    (0x01, "ctrl"), (0x02, "shift"), (0x04, "alt"), (0x08, "win"),
    (0x10, "rctrl"), (0x20, "rshift"), (0x40, "ralt"), (0x80, "rwin"),
]
MOD_BY_NAME = {m[1]: m[0] for m in MODS}

# (cli id, media usage, short label)
MEDIA = [
    ("playpause", 0xCD, "Play/Pause"), ("stop", 0xB7, "Stop"),
    ("prev", 0xB6, "Prev track"), ("next", 0xB5, "Next track"),
    ("volup", 0xE9, "Volume up"), ("voldn", 0xEA, "Volume down"),
    ("mute", 0xE2, "Mute"), ("brightup", 0x6F, "Screen bright+"),
    ("brightdn", 0x70, "Screen bright-"), ("player", 0x183, "Media player"),
    ("email", 0x18A, "Email"), ("calc", 0x192, "Calculator"),
    ("pc", 0x194, "My computer"), ("search", 0x221, "Search"),
    ("webhome", 0x223, "Browser home"), ("webback", 0x224, "Browser back"),
    ("webfwd", 0x225, "Browser fwd"), ("webstop", 0x226, "Browser stop"),
    ("webrefresh", 0x227, "Browser refresh"), ("fav", 0x22A, "Favorites"),
]
MEDIA_BY_ID = {m[0]: m[1] for m in MEDIA}

# (cli id, raw hex, short label)
MOUSE = [
    ("left", "01010100", "Left click"),
    ("right", "01020100", "Right click"),
    ("middle", "01030100", "Middle click"),
    ("forward", "01040100", "Mouse fwd"),
    ("back", "01050100", "Mouse back"),
    ("double", "01010200", "Double click"),
    ("scrollup", "01080000", "Scroll up"),
    ("scrolldn", "01090000", "Scroll down"),
]
MOUSE_BY_ID = {m[0]: m[1] for m in MOUSE}

COMMANDS = [
    ("altf4", "00043d00", "Alt+F4"), ("winl", "00080f00", "Win+L"),
    ("winr", "00081500", "Win+R"), ("wind", "00080700", "Win+D"),
    ("zoomin", "00012e00", "Zoom+"), ("zoomout", "00012d00", "Zoom-"),
    ("taskmgr", "00054c00", "Ctrl+Alt+Del"), ("undo", "00011d00", "Ctrl+Z"),
    ("save", "00011600", "Ctrl+S"),
]
COMMAND_BY_ID = {m[0]: m[1] for m in COMMANDS}

SPECIAL = [
    ("lockwin", "07000001", "Lock Win"), ("lockkbd", "07000002", "Lock kbd"),
    ("factoryreset", "07000004", "Factory reset"),
    ("winmode", "07000018", "Windows mode"),
    ("fxnext", "08000000", "Next light effect"),
    ("ledup", "08030100", "LED bright+"),
    ("leddn", "08030200", "LED bright-"),
    ("speedup", "08040100", "FX speed+"),
    ("speeddn", "08040200", "FX speed-"),
]
SPECIAL_BY_ID = {m[0]: m[1] for m in SPECIAL}

FN_TYPE = 0x0D


def hex_of(data: bytes) -> str:
    return bytes(data).hex()


def from_hex(s: str) -> bytes:
    h = "".join(c for c in s if c in "0123456789abcdefABCDEF")
    if len(h) % 2:
        raise ValueError(f"bad hex string: {s!r}")
    return bytes.fromhex(h)


# ---------------------------------------------------------------- color math
def clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def frac(v: float) -> float:
    return v - math.floor(v)


def hsv(h: float, s: float, v: float) -> tuple:
    h = frac(h) * 6.0
    i = int(math.floor(h))
    f = h - i
    p = v * (1 - s)
    q = v * (1 - s * f)
    w = v * (1 - s * (1 - f))
    table = [(v, w, p), (q, v, p), (p, v, w),
             (p, q, v), (w, p, v), (v, p, q)]
    r, g, b = table[i % 6]
    return (r * 255.0, g * 255.0, b * 255.0)


def mix(a, b, w: float) -> tuple:
    return tuple(x + (y - x) * w for x, y in zip(a, b))


def scale(c, f: float) -> tuple:
    return tuple(v * f for v in c)


def to_int8(c) -> tuple:
    return tuple(max(0, min(255, int(round(v)))) for v in c)


def to_hex(c) -> str:
    return "#" + "".join(f"{max(0, min(255, int(round(v)))):02x}" for v in c)


def is_black(c) -> bool:
    return all(v < 3 for v in c)


def parse_color(s: str) -> tuple:
    h = s.strip().lstrip("#")
    if len(h) != 6:
        raise ValueError(f"expected 6-digit hex color, got {s!r}")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def parse_key_color(spec: str):
    """'W=#ff0000' -> (led, (r,g,b)). Single key (see parse_key_colors)."""
    return parse_key_colors(spec)[0]


def parse_key_colors(spec: str):
    """'W=#ff0000' or 'A,S,D=#00ff00' -> [(led, (r,g,b)), ...]."""
    spec = spec.strip()
    for sep in ("=", ":"):
        if sep in spec:
            names, col = spec.split(sep, 1)
            break
    else:
        parts = spec.split()
        if len(parts) != 2:
            raise ValueError(f"bad --key value {spec!r}, want NAME=COLOR")
        names, col = parts
    rgb = parse_color(col.strip())
    out = []
    for name in names.split(","):
        name = name.strip()
        if not name:
            continue
        out.append((resolve_key(name), rgb))
    if not out:
        raise ValueError(f"bad --key value {spec!r}, want NAME=COLOR")
    return out


# ---------------------------------------------------------------- wired maps
# other/old/aula.py key table, kept verbatim for the wired path
U_KEY_LAYOUT = [
    (0, "ESC"), (1, "F1"), (2, "F2"), (3, "F3"), (4, "F4"), (5, "F5"),
    (6, "F6"), (7, "F7"), (8, "F8"), (9, "F9"), (10, "F10"), (11, "F11"),
    (12, "F12"), (13, "GRAVE"), (14, "1"), (15, "2"), (16, "3"), (17, "4"),
    (18, "5"), (19, "6"), (20, "7"), (21, "8"), (22, "9"), (23, "0"),
    (24, "MINUS"), (25, "EQUAL"), (26, "BKSP"), (27, "PRTSC"), (28, "SCRLK"),
    (29, "PAUSE"), (30, "TAB"), (31, "Q"), (32, "W"), (33, "E"), (34, "R"),
    (35, "T"), (36, "Y"), (37, "U"), (38, "I"), (39, "O"), (40, "P"),
    (41, "LBRKT"), (42, "RBRKT"), (43, "ENTER"), (44, "DEL"), (45, "INS"),
    (46, "HOME"), (47, "PGUP"), (48, "CAPS"), (49, "A"), (50, "S"),
    (51, "D"), (52, "F"), (53, "G"), (54, "H"), (55, "J"), (56, "K"),
    (57, "L"), (58, "SEMI"), (59, "QUOTE"), (60, "BSLSH"), (61, "END"),
    (62, "PGDN"), (63, "LSHFT"), (64, "Z"), (65, "X"), (66, "C"), (67, "V"),
    (68, "B"), (69, "N"), (70, "M"), (71, "COMMA"), (72, "DOT"),
    (73, "SLASH"), (74, "RSHFT"), (75, "UP"), (76, "RCTRL"), (77, "LCTRL"),
    (78, "LWIN"), (79, "LALT"), (80, "SPACE"), (81, "FN"), (82, "MENU"),
    (83, "LEFT"), (84, "DOWN"), (85, "RIGHT"), (86, "ISO"),
]
U_LED_INDEX = [
    0, 12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72, 78,
    1, 7, 13, 19, 25, 31, 37, 43, 49, 55, 61, 67, 73, 79, 84, 90, 96,
    2, 8, 14, 20, 26, 32, 38, 44, 50, 56, 62, 68, 74, 81, 86, 85, 91, 97,
    3, 9, 15, 21, 27, 33, 39, 45, 51, 57, 63, 69, 75, 92, 98,
    4, 10, 16, 22, 28, 34, 40, 46, 52, 58, 64, 82, 94, 83,
    5, 11, 17, 35, 59, 65, 89, 95, 101, 76,
]
U_CUSTOM_LED_MAP = {
    "rshft": 70, "left": 77, "bslsh": 80, "fn": 53, "rctrl": 59,
    "up": 82, "down": 83, "del": 85, "pgup": 86, "pgdn": 87,
    "end": 88, "right": 89,
}
U_KEY_NAME_TO_ID = {n.lower(): i for i, n in U_KEY_LAYOUT}


def u_led_idx(key_id: int) -> int:
    name = U_KEY_LAYOUT[key_id][1]
    if name.lower() in U_CUSTOM_LED_MAP:
        return U_CUSTOM_LED_MAP[name.lower()]
    return U_LED_INDEX[key_id]


# wireless led -> wired plane position, matched by normalized key name
def _norm(n: str) -> str:
    return "".join(c for c in n.lower() if c.isalnum())


_U_BY_NORM = {_norm(n): i for i, n in U_KEY_LAYOUT}
_U_BY_NORM.update({"backspace": _U_BY_NORM["bksp"], "delete": _U_BY_NORM["del"],
                   "capslock": _U_BY_NORM["caps"],
                   "leftshift": _U_BY_NORM["lshft"],
                   "rightshift": _U_BY_NORM["rshft"],
                   "leftctrl": _U_BY_NORM["lctrl"],
                   "rightctrl": _U_BY_NORM["rctrl"],
                   "leftwin": _U_BY_NORM["lwin"],
                   "leftalt": _U_BY_NORM["lalt"],
                   "pageup": _U_BY_NORM["pgup"],
                   "pagedown": _U_BY_NORM["pgdn"],
                   "lshift": _U_BY_NORM["lshft"],
                   "rshift": _U_BY_NORM["rshft"]})

# Punctuation display names vanish under _norm — map them explicitly.
_PUNCT_TO_UID = {
    "`": "grave", "-": "minus", "=": "equal", "[": "lbrkt",
    "]": "rbrkt", "\\": "bslsh", ";": "semi", "'": "quote",
    ",": "comma", ".": "dot", "/": "slash",
}
_PUNCT_TO_UID = {k: U_KEY_NAME_TO_ID[v] for k, v in _PUNCT_TO_UID.items()}

WIRELESS_TO_WIRED_PLANE: dict = {}
for (_k, _n, *_r, _led) in LAYOUT:
    _uid = _U_BY_NORM.get(_norm(_n))
    if _uid is None:
        _uid = _PUNCT_TO_UID.get(_n)
    if _uid is not None:
        WIRELESS_TO_WIRED_PLANE[_led] = u_led_idx(_uid)

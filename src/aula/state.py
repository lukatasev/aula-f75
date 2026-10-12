"""Read / modify / write keyboard state (port of src/state.js).

Wireless blocks: matrix0, matrix1, led, rgb, colors.
Wired: 136-byte config block + planar/custom LED packets.
"""

from __future__ import annotations

import json
import os
import time

from . import protocol as P
from .transport import CommError, u_config_roundtrip

BLOCKS = {
    "matrix0": (P.CMD_GET_MATRIX, P.CMD_SET_MATRIX, 0),
    "matrix1": (P.CMD_GET_MATRIX, P.CMD_SET_MATRIX, 1),
    "led": (P.CMD_GET_LED, P.CMD_SET_LED, 0),
    "rgb": (P.CMD_GET_RGBTAB, P.CMD_SET_RGBTAB, 0),
    "colors": (P.CMD_GET_COLORS, P.CMD_SET_COLORS, 0),
}
ORDER = ["matrix0", "matrix1", "led", "rgb", "colors"]
CONFIG_DIR = os.path.expanduser("~/.config/aula-f75")


def config_dir() -> str:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    return CONFIG_DIR


def led_ok(led: bytes) -> bool:
    return bool(led) and len(led) >= P.LED_SIZE and \
        led[0x7E] == 0x5A and led[0x7F] == 0xA5


def same(a: bytes, b: bytes) -> bool:
    return a is not None and b is not None and bytes(a) == bytes(b)


def backup_path(kind: str) -> str:
    return os.path.join(config_dir(), f"auto-backup-{kind}.json")


def load_backup(kind: str):
    try:
        with open(backup_path(kind)) as f:
            raw = json.load(f)
        return {k: bytes.fromhex(v) for k, v in raw["blocks"].items()}
    except (OSError, ValueError, KeyError):
        return None


def save_backup(kind: str, blocks: dict):
    try:
        with open(backup_path(kind), "w") as f:
            json.dump({"blocks": {k: bytes(v).hex() for k, v in
                                  blocks.items()}}, f)
    except OSError:
        pass


def ensure_backup(kind: str, blocks: dict):
    """First-read auto backup, mirrors the web client's autoBackup."""
    if os.path.exists(backup_path(kind)):
        return
    save_backup(kind, blocks)


# ---------------------------------------------------------------- wireless
def read_wireless(dev) -> tuple:
    """Returns (cur blocks, dev0 pristine copy, N leds, battery or None)."""
    on = dev.read_all(P.CMD_GET_ONLINE)
    if not len(on) or on[0] != 1:
        raise CommError("keyboard is asleep — press a key on it, then retry")
    got = {}
    for k in ORDER:
        get, _set, sub = BLOCKS[k]
        got[k] = bytearray(dev.read_all(get, sub))
    if not led_ok(got["led"]):
        raise CommError("bad LED block from keyboard")
    if not len(got["colors"]) or len(got["colors"]) % 3:
        raise CommError("bad colors block from keyboard")
    ensure_backup("2g", got)
    n = len(got["colors"]) // 3
    battery = None
    try:
        st = dev.read_all(P.CMD_GET_STATUS)
        if len(st) and st[0] <= 100:
            battery = st[0]
    except CommError:
        pass
    dev0 = {k: bytes(v) for k, v in got.items()}
    return got, dev0, n, battery


def set_mode(block: bytearray, mode: int):
    block[P.OFF_MODE] = mode
    block[P.OFF_CUSTOM] = 1 if mode == P.MODE_CUSTOM_W else 0


def dirty_keys(cur: dict, dev0: dict) -> list:
    return [k for k in ORDER if not same(cur[k], dev0[k])]


def save_wireless(dev, cur: dict, dev0: dict, progress=None) -> bool:
    if "colors" in dirty_keys(cur, dev0) and \
            cur["led"][P.OFF_MODE] != P.MODE_CUSTOM_W:
        set_mode(cur["led"], P.MODE_CUSTOM_W)
    keys = dirty_keys(cur, dev0)
    if not keys:
        return True
    total = sum(-(-len(cur[k]) // P.CHUNK) for k in keys)
    done = 0
    all_ok = True
    for k in keys:
        if k == "led" and not led_ok(cur["led"]):
            raise CommError("refusing to write corrupt LED block")
        _get, set_cmd, sub = BLOCKS[k]

        def _cb():
            nonlocal done
            done += 1
            if progress:
                progress(done, total)

        dev.write_cmd(set_cmd, bytes(cur[k]), sub, on_packet=_cb())
        time.sleep(0.06)
        back = dev.read_all(_get, sub)
        if not same(back, cur[k]):
            all_ok = False
        dev0[k] = back
    for k in dev0:
        cur[k] = dev0[k]
    return all_ok


# ---------------------------------------------------------------- per-key rgb
def get_rgb(colors: bytes, n: int, led: int) -> tuple:
    return (colors[led], colors[n + led], colors[2 * n + led])


def set_rgb(colors: bytearray, n: int, led: int, rgb):
    if 0 <= led < n:
        r, g, b = (max(0, min(255, int(round(v)))) for v in rgb)
        colors[led] = r
        colors[n + led] = g
        colors[2 * n + led] = b


def pal_rgb(rgb: bytes, slot: int, j: int) -> tuple:
    o = (slot + 1) * 21 + j * 3
    return (rgb[o], rgb[o + 1], rgb[o + 2])


def set_pal_rgb(rgb: bytearray, slot: int, j: int, color):
    o = (slot + 1) * 21 + j * 3
    r, g, b = (max(0, min(255, int(round(v)))) for v in color)
    rgb[o], rgb[o + 1], rgb[o + 2] = r, g, b

"""Lighting: firmware effects, brightness/speed/color, sleep, battery."""

from __future__ import annotations

from . import protocol as P
from . import state as S


def status_lines(blocks: dict, battery) -> list:
    led = blocks["led"]
    mode = led[P.OFF_MODE]
    eff = P.effect_of(mode)
    name = eff["name"] if eff else f"mode-{mode}"
    lines = [f"effect: {name} (mode {mode})"]
    if eff and eff.get("slot", -1) >= 0 and not eff.get("missing"):
        b = led[P.slot_byte(eff["slot"], 0)]
        sp = led[P.slot_byte(eff["slot"], 1)]
        lines.append(f"brightness: {b} (0-9)")
        if eff.get("speed"):
            lines.append(f"speed: {sp >> 4} (0-4)")
        if eff.get("color") or eff.get("multi"):
            lines.append(f"color index: {sp & 0x0F} (0-6 palette, 7 multi)")
    sleep_hw = led[P.OFF_SLEEP]
    secs = P.SLEEP_HW_TO_SECS.get(sleep_hw)
    lines.append(f"sleep timer: {secs}s (raw {sleep_hw})" if secs
                 else f"sleep timer: raw {sleep_hw}")
    lines.append(f"battery: {battery}%" if battery is not None
                 else "battery: n/a")
    lines.append(f"keys: {len(blocks['colors']) // 3}")
    return lines


def set_effect(blocks: dict, ident: str, brightness=None, speed=None,
               color_index=None, palette=None, multi: bool = False,
               force: bool = False):
    """Mutate led/rgb blocks in place. Returns the effect dict."""
    eff = P.effect_by_ident(ident)
    if eff is None:
        want = ", ".join(sorted(P.EFFECT_BY_NAME))
        raise ValueError(f"unknown effect {ident!r} (want: {want})")
    if eff.get("off"):
        S.set_mode(blocks["led"], 0)
        return eff
    if eff.get("missing") and not eff.get("firmware_only") and not force:
        raise ValueError(f"effect {eff['name']!r} is not implemented in this "
                         "firmware (the web client hides it too)")
    S.set_mode(blocks["led"], eff["mode"])
    slot = eff["slot"]
    if brightness is not None:
        if not 0 <= brightness <= 9:
            raise ValueError("brightness is 0-9")
        blocks["led"][P.slot_byte(slot, 0)] = brightness
    if speed is not None:
        if not eff.get("speed"):
            raise ValueError(f"effect {eff['name']!r} has no speed setting")
        if not 0 <= speed <= 4:
            raise ValueError("speed is 0-4")
        o = P.slot_byte(slot, 1)
        blocks["led"][o] = (speed << 4) | (blocks["led"][o] & 0x0F)
    idx = 7 if multi else color_index
    if idx is not None:
        if not (eff.get("color") or eff.get("multi")):
            raise ValueError(f"effect {eff['name']!r} has no color setting")
        if multi and not eff.get("multi"):
            raise ValueError(f"effect {eff['name']!r} has no multicolor mode")
        if not 0 <= idx <= 7:
            raise ValueError("color index is 0-7 (7 = multicolor)")
        o = P.slot_byte(slot, 1)
        blocks["led"][o] = (blocks["led"][o] & 0xF0) | idx
    if palette is not None:
        if not eff.get("color"):
            raise ValueError(f"effect {eff['name']!r} has no palette")
        o = P.slot_byte(slot, 1)
        j = o and (blocks["led"][o] & 0x0F)
        if j > 6:
            raise ValueError("select a palette index 0-6 first (not multi)")
        S.set_pal_rgb(blocks["rgb"], slot, j, palette)
    return eff


def set_sleep(blocks: dict, seconds: int = None, raw: int = None) -> int:
    if raw is not None:
        if not 0 <= raw <= 255:
            raise ValueError("raw sleep byte is 0-255")
        blocks["led"][P.OFF_SLEEP] = raw
        return raw
    if seconds not in P.SLEEP_SECS_TO_HW:
        want = ", ".join(str(s) for s, _ in P.SLEEP_TABLE)
        raise ValueError(f"sleep seconds want one of: {want} (or --raw N)")
    hw = P.SLEEP_SECS_TO_HW[seconds]
    blocks["led"][P.OFF_SLEEP] = hw
    return hw

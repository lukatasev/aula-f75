"""Key remapping: typed SPEC <-> 4-byte matrix codes (port of src/keys.js)."""

from __future__ import annotations

from . import protocol as P


def parse_spec(spec: str) -> bytes:
    """SPEC forms (case-insensitive type, ':' or '=' separator):
    key:A[+ctrl+shift+alt+win+rctrl...] | media:ID | mouse:ID |
    cmd:ID | special:ID | off | fn
    """
    s = spec.strip()
    if s.lower() == "off":
        return bytes(4)
    if s.lower() == "fn":
        return bytes([P.FN_TYPE, 0, 0, 0])
    for sep in (":", "="):
        if sep in s:
            kind, arg = s.split(sep, 1)
            break
    else:
        raise ValueError(f"bad key spec {spec!r}")
    kind, arg = kind.strip().lower(), arg.strip()
    if kind == "off":
        return bytes(4)
    if kind == "fn":
        return bytes([P.FN_TYPE, 0, 0, 0])
    if kind == "key":
        parts = [p.strip().lower() for p in arg.split("+")]
        mods = 0
        code = 0
        for p in parts:
            if p in P.MOD_BY_NAME:
                mods |= P.MOD_BY_NAME[p]
            elif p in P.HID_NAME_TO_CODE:
                code = P.HID_NAME_TO_CODE[p]
            else:
                raise ValueError(f"unknown key/modifier {p!r}")
        if not code and not mods:
            raise ValueError(f"empty key spec {spec!r}")
        return bytes([0, mods, 0, code])
    if kind == "media":
        u = P.MEDIA_BY_ID.get(arg.lower())
        if u is None:
            want = ", ".join(m[0] for m in P.MEDIA)
            raise ValueError(f"unknown media {arg!r} (want: {want})")
        return bytes([2, 0, (u >> 8) & 0xFF, u & 0xFF])
    if kind == "mouse":
        h = P.MOUSE_BY_ID.get(arg.lower())
        if h is None:
            want = ", ".join(m[0] for m in P.MOUSE)
            raise ValueError(f"unknown mouse {arg!r} (want: {want})")
        return P.from_hex(h)
    if kind == "cmd":
        h = P.COMMAND_BY_ID.get(arg.lower())
        if h is None:
            want = ", ".join(m[0] for m in P.COMMANDS)
            raise ValueError(f"unknown command {arg!r} (want: {want})")
        return P.from_hex(h)
    if kind == "special":
        h = P.SPECIAL_BY_ID.get(arg.lower())
        if h is None:
            want = ", ".join(m[0] for m in P.SPECIAL)
            raise ValueError(f"unknown special {arg!r} (want: {want})")
        return P.from_hex(h)
    if kind == "raw":
        b = P.from_hex(arg)
        if len(b) != 4:
            raise ValueError("raw spec must be 4 bytes (8 hex chars)")
        return b
    raise ValueError(f"bad spec type {kind!r} "
                     "(want key/media/mouse/cmd/special/off/fn/raw)")


def describe(code: bytes) -> str:
    h = P.hex_of(code)
    if h == "00000000":
        return "disabled"
    for table in (P.COMMANDS, P.MOUSE, P.SPECIAL):
        for _id, _hx, short in table:
            if _hx == h:
                return short
    ty, b1, b2, b3 = code[0], code[1], code[2], code[3]
    if ty == 0x00:
        parts = [m[1] for m in P.MODS if b1 & m[0]]
        for b in (b3, b2):
            if b:
                parts.append(P.HID.get(b, f"#{b:02x}"))
        return "+".join(parts) if parts else "none"
    if ty == 0x02:
        u = (b2 << 8) | b3
        for _id, _u, short in P.MEDIA:
            if _u == u:
                return short
        return "media"
    if ty == P.FN_TYPE:
        return "Fn"
    if ty == 0x03:
        return "macro"
    return "kb-func"


def layer_block(blocks: dict, layer: str) -> str:
    if layer in ("normal", "0", "0"):
        return "matrix0"
    if layer in ("fn", "1"):
        return "matrix1"
    raise ValueError("layer is normal|fn")


def code_at(block: bytes, led: int) -> bytes:
    return bytes(block[4 * led:4 * led + 4])


def show_layer(blocks: dict, layer: str) -> list:
    blk = blocks[layer_block(blocks, layer)]
    rows = []
    for (_k, name, *_r, led) in P.LAYOUT:
        rows.append((name, led, describe(code_at(blk, led))))
    return rows

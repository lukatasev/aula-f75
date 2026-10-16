"""USB transports for both connection modes.

2.4GHz dongle (3554:fa09): hidapi port of src/transport.js - 20-byte
packets, report ID 0x13, 14-byte chunks, per-packet checksum and acks.
Wired (258A:010C): hidapi HID feature reports (report 0x06, 520 bytes)
on interface 1 - same packets as other/old/aula.py, but via hidraw with no
kernel-driver detaching, so typing keeps working.
"""

from __future__ import annotations

import threading
import time

from . import protocol as P


class CommError(Exception):
    """Raised when the keyboard does not answer correctly."""


WRITE_GAP_S = 0.015

# Set by the CLI on SIGINT/SIGTERM so in-flight retry loops abort fast
# instead of grinding through every timeout.
ABORT = threading.Event()


def build_packet(cmd: int, total: int, idx: int, sub_len: int,
                 data: bytes | None) -> bytes:
    p = bytearray(20)
    p[0] = P.RID
    p[1] = cmd
    p[2] = total
    p[3] = idx
    p[4] = sub_len
    if data:
        p[5:5 + len(data[:P.CHUNK])] = data[:P.CHUNK]
    p[19] = sum(p[:19]) & 0xFF
    return bytes(p)


def packet_ok(pkt: bytes) -> bool:
    return len(pkt) == 20 and pkt[0] == P.RID and \
        (sum(pkt[:19]) & 0xFF) == pkt[19]


class WirelessHID:
    """hidapi handle to the 2.4GHz dongle command interface."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.dev = None
        self.queue: list = []
        self._open()

    def _open(self):
        import hid
        cands = hid.enumerate(P.W_VID, P.W_PID)
        if not cands:
            raise CommError(f"device {P.W_VID:04x}:{P.W_PID:04x} not found")
        # Linux hidapi reports no usage page; the command collection
        # (page 0xff02, report 0x13) lives on USB interface 1. Probe each
        # candidate with read-only GET_ONLINE until one answers.
        cands = sorted(cands,
                       key=lambda c: 0 if c.get("interface_number") == 1
                       else 1)
        errors = []
        asleep_seen = False
        for c in cands:
            dev = hid.device()
            try:
                dev.open_path(c["path"])
            except Exception as e:
                errors.append(str(e))
                continue
            self.dev = dev
            self.path = c["path"]
            try:
                self.queue = []
                on = self.read_all(P.CMD_GET_ONLINE, tries=2)
                if len(on) and on[0] == 1:
                    return  # responsive command interface
                if len(on):
                    asleep_seen = True
            except CommError as e:
                errors.append(str(e))
            try:
                dev.close()
            except Exception:
                pass
            self.dev = None
        if asleep_seen:
            raise CommError("keyboard is asleep - press any key on it, "
                            "then retry")
        raise CommError("2.4GHz dongle found but no interface answers "
                        f"({'; '.join(errors)})")

    def _log(self, *a):
        if self.verbose:
            print("[hid]", *a)

    def send(self, pkt: bytes):
        n = self.dev.write(bytes(pkt))
        if n != len(pkt):
            raise CommError(f"short write ({n}/{len(pkt)})")

    def _read_frame(self, timeout_ms: int):
        data = self.dev.read(20, timeout_ms)
        if not data:
            return None
        b = bytes(data)
        if len(b) == 20 and b[0] == P.RID:
            r = b
        elif len(b) == 19:
            r = bytes([P.RID]) + b
        else:
            return None
        if r[1] == P.CMD_EVENT:
            return None  # async online event, not a command reply
        if (r[1] & 0x7F) == (P.CMD_REALTIME & 0x7F):
            return None  # realtime echo, ignore like the web client
        return r

    def _recv(self, cmd: int, timeout_ms: int = 1000):
        end = time.monotonic() + timeout_ms / 1000.0
        while True:
            if ABORT.is_set():
                return None
            for i, r in enumerate(self.queue):
                if (r[1] & 0x7F) == (cmd & 0x7F):
                    return self.queue.pop(i)
            left = end - time.monotonic()
            if left <= 0:
                return None
            r = self._read_frame(int(min(left * 1000, 100)))
            if r is not None:
                self.queue.append(r)

    def read_all(self, cmd: int, sub: int = 0, tries: int = 3) -> bytes:
        for _ in range(tries):
            if ABORT.is_set():
                raise CommError("interrupted")
            self.queue = []
            self.send(build_packet(cmd, 1, 0, sub << 4, None))
            parts: dict = {}
            while True:
                r = self._recv(cmd)
                if r is None or (r[1] & 0x80) or (r[2] & 0x80):
                    break
                total = r[2] & 0x7F
                idx = r[3]
                ln = min(r[4] & 0x0F, P.CHUNK)
                parts[idx] = r[5:5 + ln]
                if idx + 1 >= total:
                    if len(parts) == total:
                        out = bytearray()
                        for k in range(total):
                            out += parts[k]
                        return bytes(out)
                    break
            time.sleep(0.1)
        raise CommError(f"no reply to cmd 0x{cmd:02x}")

    def write_cmd(self, cmd: int, data: bytes, sub: int = 0,
                  tries: int = 5, on_packet=None):
        total = max(1, -(-len(data) // P.CHUNK))
        self.queue = []
        for idx in range(total):
            chunk = data[idx * P.CHUNK:(idx + 1) * P.CHUNK]
            pkt = build_packet(cmd, total, idx, (sub << 4) | len(chunk),
                               chunk)
            ok = False
            for _ in range(tries):
                if ABORT.is_set():
                    raise CommError("interrupted")
                self.send(pkt)
                r = self._recv(cmd)
                ok = bool(r) and not (r[2] & 0x80) and r[3] == idx
                if ok:
                    break
                time.sleep(0.1)
            if not ok:
                raise CommError(f"write cmd 0x{cmd:02x} pkt {idx} failed")
            # airtime for key events: back-to-back packets stall the
            # dongle link and delay key releases (stuck keys)
            time.sleep(WRITE_GAP_S)
            if on_packet:
                on_packet()

    def send_realtime(self, sub: int, data: bytes):
        total = max(1, -(-len(data) // P.CHUNK))
        for idx in range(total):
            time.sleep(P.PACKET_GAP_S)
            chunk = data[idx * P.CHUNK:(idx + 1) * P.CHUNK]
            self.send(build_packet(P.CMD_REALTIME, total, idx,
                                   (sub << 4) | len(chunk), chunk))

    def close(self):
        try:
            if self.dev is not None:
                self.dev.close()
        finally:
            self.dev = None


class WiredUSB:
    """hidapi handle to the wired SinoWealth board (258A:010C).

    Uses HID feature reports on interface 1 (report 0x06, 520 bytes) via
    hidraw - the same packets other/old/aula.py sent with pyusb, but with zero
    kernel-driver detaching, so typing keeps working mid-command and
    animations can stream without bricking input.
    """

    def __init__(self):
        import hid
        cands = hid.enumerate(P.U_VID, P.U_PID)
        if not cands:
            raise CommError(f"device {P.U_VID:04x}:{P.U_PID:04x} not found")
        cands = sorted(cands,
                       key=lambda c: 0 if c.get("interface_number") == 1
                       else 1)
        errors = []
        for c in cands:
            dev = hid.device()
            try:
                dev.open_path(c["path"])
            except Exception as e:
                errors.append(str(e))
                continue
            self.dev = dev
            self.path = c["path"]
            try:
                # harmless read-trigger probe; a live board answers the
                # config read with report 06/0x84
                dev.send_feature_report(u_build_config_read())
                time.sleep(P.U_CMD_DELAY_S)
                r = bytes(dev.get_feature_report(P.U_REPORT_ID, 520))
                if len(r) >= P.U_CONFIG_RESP_SIZE and r[0] == P.U_REPORT_ID \
                        and r[1] == P.U_CMD_CONFIG_READ:
                    return
                errors.append(f"{c['path']!r}: unexpected reply")
            except Exception as e:
                errors.append(str(e))
            try:
                dev.close()
            except Exception:
                pass
            self.dev = None
        raise CommError("wired board found but LED interface does not "
                        f"answer ({'; '.join(errors)})")

    def send(self, pkt: bytes):
        n = self.dev.send_feature_report(bytes(pkt))
        if n != len(pkt):
            raise CommError(f"short feature write ({n}/{len(pkt)})")

    def recv(self, length: int = P.U_REPORT_SIZE) -> bytes:
        return bytes(self.dev.get_feature_report(P.U_REPORT_ID, length))

    def close(self):
        try:
            if self.dev is not None:
                self.dev.close()
        finally:
            self.dev = None


# ---------------------------------------------------------------- wired pkts
def u_build_led_custom(r: int, g: int, b: int) -> bytes:
    pkt = bytearray(P.U_REPORT_SIZE)
    pkt[0] = P.U_REPORT_ID
    pkt[1] = P.U_CMD_LED_CUSTOM
    pkt[4] = 0x01
    pkt[7] = 0x02
    i = 29
    while i + 2 < P.U_CUSTOM_TERM:
        pkt[i] = r
        pkt[i + 1] = g
        pkt[i + 2] = b
        i += 3
    pkt[P.U_CUSTOM_TERM] = 0x5A
    pkt[P.U_CUSTOM_TERM + 1] = 0xA5
    return bytes(pkt)


def u_build_led_planar(colors: dict) -> bytes:
    """colors: plane position -> (r,g,b)."""
    pkt = bytearray(P.U_REPORT_SIZE)
    pkt[0] = P.U_REPORT_ID
    pkt[1] = P.U_CMD_LED_PLANAR
    pkt[4] = 0x01
    pkt[6] = P.U_LED_BUFFER_KEYS
    pkt[7] = 0x01
    pr, pg, pb = P.U_PLANE_OFFSET, P.U_PLANE_OFFSET + P.U_PLANE_SIZE, \
        P.U_PLANE_OFFSET + 2 * P.U_PLANE_SIZE
    for pos, (r, g, b) in colors.items():
        if 0 <= pos < P.U_PLANE_SIZE:
            pkt[pr + pos] = r
            pkt[pg + pos] = g
            pkt[pb + pos] = b
    return bytes(pkt)


def u_build_planar_from_keyids(mapping: dict) -> bytes:
    """mapping: old key id -> (r,g,b)."""
    return u_build_led_planar({P.u_led_idx(k): c for k, c in mapping.items()})


def u_build_direct_frame(colors: dict) -> bytes:
    """Direct-mode frame (cmd 0x08, interleaved RGB at 8+idx*3).

    Temporary live overlay: the keyboard shows it while frames arrive
    (keepalive ~1s) and falls back to its stored effect afterwards.
    No config writes, no mode switching, nothing stored to restore.
    colors: plane position -> (r,g,b).
    """
    pkt = bytearray(P.U_REPORT_SIZE)
    pkt[0] = P.U_REPORT_ID
    pkt[1] = 0x08
    pkt[4] = 0x01
    pkt[6] = P.U_LED_BUFFER_KEYS
    pkt[7] = 0x01
    for pos, (r, g, b) in colors.items():
        off = 8 + pos * 3
        if 0 <= off <= P.U_REPORT_SIZE - 3 and 0 <= pos < P.U_PLANE_SIZE:
            pkt[off] = r
            pkt[off + 1] = g
            pkt[off + 2] = b
    return bytes(pkt)


def u_build_config_read() -> bytes:
    pkt = bytearray(P.U_REPORT_SIZE)
    pkt[0] = P.U_REPORT_ID
    pkt[1] = P.U_CMD_CONFIG_READ
    pkt[4] = 0x01
    pkt[6] = 0x80
    return bytes(pkt)


def u_build_config_write(config: bytes, effect: int,
                         brightness: int | None = None,
                         custom: bool = False) -> bytes:
    pkt = bytearray(P.U_REPORT_SIZE)
    pkt[0] = P.U_REPORT_ID
    pkt[1] = P.U_CMD_CONFIG_WRITE
    pkt[4] = 0x01
    pkt[6] = 0x80
    n = min(P.U_CONFIG_RESP_SIZE - 8, P.U_REPORT_SIZE - 8)
    pkt[8:8 + n] = config[8:8 + n]
    pkt[P.U_CFG_CUSTOM_FLAG] = 0x01 if custom else 0x00
    pkt[P.U_CFG_EFFECT_ID] = effect
    off = 64 + 2 * effect
    if 0 <= off < P.U_REPORT_SIZE - 1:
        if brightness is not None:
            pkt[off] = brightness
        elif not (1 <= pkt[off] <= 4):
            pkt[off] = 4
        if custom:
            pkt[off + 1] = (pkt[off + 1] & 0xF0) | 0x07
        else:
            pkt[off + 1] &= 0xF0
    return bytes(pkt)


def u_config_roundtrip(dev: WiredUSB) -> bytes:
    dev.send(u_build_config_read())
    time.sleep(P.U_CMD_DELAY_S)
    return dev.recv()[:P.U_CONFIG_RESP_SIZE]


def open_device(pref: str = "auto", verbose: bool = False):
    """Returns (kind, handle) with kind '2g' or 'wired'."""
    if pref in ("auto", "2.4g", "2g"):
        try:
            return "2g", WirelessHID(verbose=verbose)
        except Exception as e:
            if pref != "auto":
                raise CommError(f"2.4GHz dongle: {e}")
    if pref in ("auto", "wired"):
        try:
            return "wired", WiredUSB()
        except Exception as e:
            if pref != "auto":
                raise CommError(f"wired: {e}")
    raise CommError("no keyboard found (checked 2.4GHz 3554:fa09 and "
                    "wired 258a:010c) - if the keyboard is asleep, press "
                    "any key on it and retry")

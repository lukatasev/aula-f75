"""Command line interface: subcommands for every configurator feature."""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import time

from . import protocol as P
from . import state as S
from . import lighting as L
from . import keys as K
from . import anims as A
from . import daemon as D
from .transport import (CommError, open_device, u_build_led_custom,
                        u_build_led_planar, u_build_direct_frame,
                        u_build_config_read,
                        u_build_config_write, u_config_roundtrip)


# ---------------------------------------------------------------- helpers
def _open(args):
    kind, dev = open_device(args.transport)
    print(f"connected via {'2.4GHz dongle' if kind == '2g' else 'wired'}",
          file=sys.stderr)
    return kind, dev


def _close(dev):
    try:
        dev.close()
    except Exception:
        pass


def _progress(done, total):
    print(f"\rwriting… {round(done * 100 / total)}%", end="", flush=True)
    if done >= total:
        print()


def _save_wireless(dev, cur, dev0):
    ok = S.save_wireless(dev, cur, dev0, progress=_progress)
    print("saved" if ok else "saved (verify mismatch on some blocks — "
          "retry if lighting looks wrong)")


# ---------------------------------------------------------------- color
def cmd_color(args):
    keys = {}
    for spec in args.key:
        try:
            pairs = P.parse_key_colors(spec)
        except (KeyError, ValueError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        for led, col in pairs:
            keys[led] = col
    base = None
    if args.base is not None:
        try:
            base = P.parse_color(args.base)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
    if base is None and not keys:
        print("error: give a BASE color and/or --key NAME=COLOR",
              file=sys.stderr)
        return 1
    kind, dev = _open(args)
    try:
        if kind == "2g":
            return _color_wireless(dev, base, keys, args.brightness)
        return _color_wired(dev, base, keys, args.brightness)
    finally:
        _close(dev)


def _color_wireless(dev, base, keys, brightness):
    cur, dev0, n, _batt = S.read_wireless(dev)
    colors = bytearray(cur["colors"])
    if base is not None:
        for (_k, _n, *_r, led) in P.LAYOUT:
            if led not in keys and led < n:
                S.set_rgb(colors, n, led, base)
    for led, col in keys.items():
        if led >= n:
            print(f"warning: key led {led} out of range, skipped",
                  file=sys.stderr)
            continue
        S.set_rgb(colors, n, led, col)
    cur["colors"] = bytes(colors)
    S.set_mode(cur["led"], P.MODE_CUSTOM_W)
    if brightness is not None:
        if not 0 <= brightness <= 9:
            print("error: wireless brightness is 0-9", file=sys.stderr)
            return 1
        eff = P.EFFECT_BY_MODE[P.MODE_CUSTOM_W]
        cur["led"][P.slot_byte(eff["slot"], 0)] = brightness
    _save_wireless(dev, cur, dev0)
    print("set " + ("per-key colors" if keys else f"static {P.to_hex(base)}"))
    return 0


def _color_wired(dev, base, keys, brightness):
    import time as _t
    if brightness is not None and not 1 <= brightness <= 4:
        print("error: wired brightness is 1-4", file=sys.stderr)
        return 1
    if keys:
        kid_map = {}
        for led, col in keys.items():
            name = P.led_name(led)
            kid = _wireless_led_to_uid(led, name)
            if kid is None:
                print(f"warning: no wired mapping for {name}, skipped",
                      file=sys.stderr)
                continue
            kid_map[kid] = col
        if base is not None:
            for kid, _n in P.U_KEY_LAYOUT:
                if kid not in kid_map:
                    kid_map[kid] = base
        from . import transport as T
        dev.send(T.u_build_planar_from_keyids(kid_map))
        _t.sleep(P.U_CMD_DELAY_S)
        cfg = u_config_roundtrip(dev)
        _t.sleep(P.U_CMD_DELAY_S)
        dev.send(u_build_config_write(cfg, P.U_MODE_CUSTOM, brightness,
                                      custom=True))
        print("set per-key colors")
    else:
        dev.send(u_build_led_custom(*base))
        _t.sleep(P.U_CMD_DELAY_S)
        cfg = u_config_roundtrip(dev)
        _t.sleep(P.U_CMD_DELAY_S)
        dev.send(u_build_config_write(cfg, P.U_MODE_STATIC, brightness))
        print(f"set static color to {P.to_hex(base)}")
    return 0


def _wireless_led_to_uid(led: int, name: str):
    for uid, pos in ((uid, P.u_led_idx(uid))
                     for uid, _n in P.U_KEY_LAYOUT):
        pass
    # reverse lookup via plane map
    plane = P.WIRELESS_TO_WIRED_PLANE.get(led)
    if plane is None:
        # try old-style name directly (BKSP, LSHFT, …)
        uid = P.U_KEY_NAME_TO_ID.get(name.lower())
        return uid
    for uid, _n in P.U_KEY_LAYOUT:
        if P.u_led_idx(uid) == plane:
            return uid
    return None


# ---------------------------------------------------------------- effect
def cmd_effect(args):
    if args.action == "list":
        for e in P.EFFECTS:
            flag = " (not in firmware)" if e.get("missing") else ""
            print(f"{e['name']:13} mode {e['mode']:3}  {e['desc']}{flag}")
        print(f"{'off':13} mode   0  Off")
        return 0
    kind, dev = _open(args)
    try:
        if kind == "2g":
            cur, dev0, _n, _b = S.read_wireless(dev)
            pal = P.parse_color(args.color) if args.color else None
            try:
                eff = L.set_effect(cur, args.effect,
                                   brightness=args.brightness,
                                   speed=args.speed,
                                   color_index=args.color_index,
                                   palette=pal, multi=args.multi,
                                   force=args.force)
            except ValueError as e:
                print(f"error: {e}", file=sys.stderr)
                return 1
            _save_wireless(dev, cur, dev0)
            print(f"effect: {eff['name']}")
            return 0
        # wired: best-effort via config block
        eff = P.effect_by_ident(args.effect)
        mode = eff["mode"] if eff else None
        if eff is None or mode is None:
            print(f"error: unknown effect {args.effect!r}", file=sys.stderr)
            return 1
        if args.brightness is not None and not 1 <= args.brightness <= 4:
            print("error: wired brightness is 1-4", file=sys.stderr)
            return 1
        if args.speed is not None:
            print("warning: speed is best-effort on wired and may be "
                  "ignored", file=sys.stderr)
        cfg = u_config_roundtrip(dev)
        time.sleep(P.U_CMD_DELAY_S)
        dev.send(u_build_config_write(
            cfg, mode, args.brightness,
            custom=(mode == P.U_MODE_CUSTOM)))
        print(f"effect: {eff['name']} (wired best-effort — palette/speed "
              "may not apply)")
        return 0
    finally:
        _close(dev)


# ---------------------------------------------------------------- colors
def cmd_colors(args):
    per_key = {}
    for spec in args.key:
        try:
            pairs = P.parse_key_colors(spec)
        except (KeyError, ValueError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        for led, col in pairs:
            per_key[led] = col
    if args.preset and args.preset not in ("rainbow", "gradient"):
        print("error: preset is rainbow|gradient", file=sys.stderr)
        return 1
    if args.clear and (args.all or per_key or args.preset):
        print("error: --clear is exclusive", file=sys.stderr)
        return 1
    if not (args.all or per_key or args.preset or args.clear):
        print("error: give --all HEX, --key NAME=COLOR, --preset, or --clear",
              file=sys.stderr)
        return 1
    c1 = P.parse_color(args.color1) if args.color1 else (255, 48, 0)
    c2 = P.parse_color(args.color2) if args.color2 else (0, 80, 255)

    kind, dev = _open(args)
    try:
        if kind == "2g":
            cur, dev0, n, _b = S.read_wireless(dev)
            colors = bytearray(cur["colors"])
            paint = {}
            if args.clear:
                paint = {e[6]: (0, 0, 0) for e in P.LAYOUT}
            elif args.preset == "rainbow":
                paint = {e[6]: P.hsv(P.kx(e) * 0.85, 1, 1) for e in P.LAYOUT}
            elif args.preset == "gradient":
                paint = {e[6]: P.mix(c1, c2, P.kx(e)) for e in P.LAYOUT}
            if args.all:
                paint.update({e[6]: P.parse_color(args.all)
                              for e in P.LAYOUT})
            paint.update(per_key)
            for led, col in paint.items():
                if led < n:
                    S.set_rgb(colors, n, led, col)
            cur["colors"] = bytes(colors)
            S.set_mode(cur["led"], P.MODE_CUSTOM_W)
            _save_wireless(dev, cur, dev0)
            print(f"painted {len(paint)} keys")
            return 0
        # wired
        from . import transport as T
        plane = {}
        if args.clear:
            plane = {pos: (0, 0, 0)
                     for pos in P.WIRELESS_TO_WIRED_PLANE.values()}
        else:
            if args.preset == "rainbow":
                for e in P.LAYOUT:
                    pos = P.WIRELESS_TO_WIRED_PLANE.get(e[6])
                    if pos is not None:
                        plane[pos] = P.to_int8(P.hsv(P.kx(e) * 0.85, 1, 1))
            elif args.preset == "gradient":
                for e in P.LAYOUT:
                    pos = P.WIRELESS_TO_WIRED_PLANE.get(e[6])
                    if pos is not None:
                        plane[pos] = P.to_int8(P.mix(c1, c2, P.kx(e)))
            if args.all:
                rgb = P.parse_color(args.all)
                plane = {pos: rgb
                         for pos in P.WIRELESS_TO_WIRED_PLANE.values()}
            for led, col in per_key.items():
                pos = P.WIRELESS_TO_WIRED_PLANE.get(led)
                if pos is None:
                    print(f"warning: no wired mapping for "
                          f"{P.led_name(led)}, skipped", file=sys.stderr)
                    continue
                plane[pos] = col
        dev.send(T.u_build_led_planar(plane))
        time.sleep(P.U_CMD_DELAY_S)
        cfg = u_config_roundtrip(dev)
        time.sleep(P.U_CMD_DELAY_S)
        dev.send(u_build_config_write(cfg, P.U_MODE_CUSTOM, None,
                                      custom=True))
        print(f"painted {len(plane)} leds")
        return 0
    finally:
        _close(dev)


# ---------------------------------------------------------------- anim
def cmd_anim(args):
    if args.action == "list":
        for aid, (name, desc, audio) in A.ANIM_INFO.items():
            print(f"{aid:9} {name} — {desc}"
                  + (" [needs audio]" if audio else "")
                  + (" [key input]" if aid == "type" else ""))
        return 0
    if args.action == "stop":
        if D.stop_daemon():
            print("animation stopped")
            return 0
        print("no background animation running")
        return 1
    return _anim_start(args)


def _anim_start(args):
    if args.daemon and getattr(args, "daemon_child", False):
        pass
    elif args.daemon:
        D.stop_daemon()
        D.remove_pid()
        argv = _daemon_argv(args)
        pid = D.spawn_daemon(argv)
        time.sleep(0.5)
        info = D.read_pid()
        if info and info.get("pid"):
            print(f"animation {args.anim} started in background "
                  f"(pid {info['pid']})")
            return 0
        print(f"daemon starting (fork pid {pid}), see "
              f"{D.LOG_FILE} for errors")
        return 0
    if getattr(args, "daemon_child", False):
        D.write_pid({"pid": os.getpid(), "anim": args.anim,
                     "started": time.time()})
    kind, dev = open_device(args.transport)
    runner = A.AnimRunner(
        kind, dev, args.anim, speed=args.speed,
        brightness=args.brightness, c1=P.parse_color(args.color1),
        c2=P.parse_color(args.color2), gain=args.gain, source=args.source,
        duration=args.time, verbose=args.verbose, device=args.device,
        eq_style=args.eq_style, peak_fall=args.peak_fall)
    stop_ev = runner.stop_flag
    stopping = {"n": 0}

    def _sig(_n, _f):
        from .transport import ABORT
        ABORT.set()
        stopping["n"] += 1
        if stopping["n"] == 1:
            print("\nstopping… restoring lighting",
                  file=sys.stderr, flush=True)
        stop_ev.set()
    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    restore = _anim_restore(kind, dev, args.verbose)
    try:
        if kind == "wired" and args.verbose:
            print("[anim] wired direct mode: temporary overlay, "
                  "auto-reverts ~1s after stop")
        print(f"playing {args.anim} — Ctrl+C to stop"
              + (" (restores lighting on exit)" if not
                 getattr(args, "daemon_child", False) else ""),
              flush=True)
        runner.run(restore)
    except CommError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        _close(dev)
        if getattr(args, "daemon_child", False):
            D.remove_pid()
    print("stopped" + (", lighting restored" if kind == "2g"
                        else " (lighting auto-reverts in ~1s)"))
    return 0


def _daemon_argv(args):
    """Re-exec argv for the detached child (drops --daemon)."""
    rest = [a for a in sys.argv[1:] if a != "--daemon"] + ["--daemon-child"]
    if sys.argv[0].endswith("__main__.py"):
        return [sys.executable, "-m", "aula"] + rest
    return [sys.executable, sys.argv[0]] + rest


def _anim_restore(kind, dev, verbose=False):
    if kind == "2g":
        try:
            cur, _d0, _n, _b = S.read_wireless(dev)
            saved = bytes(cur["led"])
        except CommError:
            saved = None

        def _do():
            if saved is None:
                return
            t0 = time.monotonic()
            try:
                on = dev.read_all(P.CMD_GET_ONLINE, tries=1)
                awake = bool(len(on)) and on[0] == 1
            except CommError:
                awake = False
            if verbose:
                print(f"[anim] online check: awake={awake} "
                      f"+{time.monotonic() - t0:.2f}s")
            if not awake:
                print("keyboard asleep — stored lighting unchanged, it "
                      "wakes with previous lighting")
                return
            dev.write_cmd(P.CMD_SET_LED, saved, tries=3)
            if verbose:
                print(f"[anim] led restore write "
                      f"+{time.monotonic() - t0:.2f}s")
        return _do
    # wired direct mode needs no restore: the overlay auto-reverts ~1s
    # after the last frame, stored config untouched
    return lambda: None


# ---------------------------------------------------------------- keys
def cmd_keys(args):
    if args.action == "types":
        print("key:NAME[+mod...]  mods: ctrl shift alt win rctrl rshift "
              "ralt rwin")
        print("media: " + ", ".join(m[0] for m in P.MEDIA))
        print("mouse: " + ", ".join(m[0] for m in P.MOUSE))
        print("cmd: " + ", ".join(m[0] for m in P.COMMANDS))
        print("special: " + ", ".join(m[0] for m in P.SPECIAL))
        print("off | fn | raw:00112233")
        return 0
    kind, dev = _open(args)
    try:
        if kind != "2g":
            print("error: key remapping is only supported over the 2.4GHz "
                  "dongle (no remap protocol is known for wired)",
                  file=sys.stderr)
            return 1
        if args.action == "show":
            cur, _d0, _n, _b = S.read_wireless(dev)
            for name, led, desc in K.show_layer(cur, args.layer):
                print(f"{name:10} {desc}")
            return 0
        if args.action == "set":
            try:
                led = P.resolve_key(args.key)
            except KeyError as e:
                print(f"error: {e}", file=sys.stderr)
                return 1
            try:
                code = K.parse_spec(args.spec)
            except ValueError as e:
                print(f"error: {e}", file=sys.stderr)
                return 1
            cur, dev0, _n, _b = S.read_wireless(dev)
            blk = K.layer_block(cur, args.layer)
            if bytes(cur[blk][4 * led:4 * led + 4])[0] == P.FN_TYPE \
                    and not args.force:
                print("error: that key is the Fn key (locked) — use --force "
                      "to override at your own risk", file=sys.stderr)
                return 1
            cur[blk][4 * led:4 * led + 4] = code
            _save_wireless(dev, cur, dev0)
            print(f"{args.key} [{args.layer}] -> {K.describe(code)}")
            return 0
        if args.action in ("reset-key", "reset-layer"):
            back = S.load_backup("2g")
            if back is None:
                print("error: no auto-backup found yet — connect once with "
                      "any read command first", file=sys.stderr)
                return 1
            cur, dev0, _n, _b = S.read_wireless(dev)
            blk = K.layer_block(cur, args.layer)
            if blk not in back or len(back[blk]) != len(cur[blk]):
                print("error: backup incompatible with current keyboard",
                      file=sys.stderr)
                return 1
            if args.action == "reset-key":
                try:
                    led = P.resolve_key(args.key)
                except KeyError as e:
                    print(f"error: {e}", file=sys.stderr)
                    return 1
                cur[blk][4 * led:4 * led + 4] = back[blk][4 * led:4 * led + 4]
            else:
                cur[blk] = bytearray(back[blk])
            _save_wireless(dev, cur, dev0)
            print("restored from auto-backup")
            return 0
    finally:
        _close(dev)
    return 1


# ---------------------------------------------------------------- sleep/batt
def cmd_sleep(args):
    kind, dev = _open(args)
    try:
        if kind != "2g":
            print("error: sleep timer is only supported over 2.4GHz",
                  file=sys.stderr)
            return 1
        cur, dev0, _n, _b = S.read_wireless(dev)
        if args.action == "get" and args.seconds is None and \
                args.raw is None:
            hw = cur["led"][P.OFF_SLEEP]
            secs = P.SLEEP_HW_TO_SECS.get(hw)
            print(f"sleep: {secs}s (raw {hw})" if secs else
                  f"sleep: raw {hw}")
            return 0
        secs = args.seconds if args.action == "set" else args.seconds
        try:
            hw = L.set_sleep(cur, seconds=secs, raw=args.raw)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        _save_wireless(dev, cur, dev0)
        s = P.SLEEP_HW_TO_SECS.get(hw, f"raw {hw}")
        print(f"sleep timer: {s}")
        return 0
    finally:
        _close(dev)


def cmd_battery(args):
    kind, dev = _open(args)
    try:
        if kind != "2g":
            print("error: battery readout is only supported over 2.4GHz",
                  file=sys.stderr)
            return 1
        on = dev.read_all(P.CMD_GET_ONLINE)
        if not len(on) or on[0] != 1:
            print("error: keyboard is asleep — press a key, then retry",
                  file=sys.stderr)
            return 1
        st = dev.read_all(P.CMD_GET_STATUS)
        if len(st) and st[0] <= 100:
            print(f"battery: {st[0]}%")
        else:
            print("battery: n/a")
        return 0
    except CommError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        _close(dev)


def cmd_status(args):
    kind, dev = _open(args)
    try:
        if kind != "2g":
            cfg = u_config_roundtrip(dev)
            print(f"transport: wired\nstatic effect id: {cfg[18]}")
            return 0
        cur, _d0, _n, batt = S.read_wireless(dev)
        print("transport: 2.4GHz dongle")
        for line in L.status_lines(cur, batt):
            print(line)
        return 0
    except CommError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        _close(dev)


# ---------------------------------------------------------------- audio debug
def cmd_audio(args):
    from .audio import AudioFeed, list_sources
    if args.action == "list":
        try:
            dm, ds, rows = list_sources()
        except Exception as e:
            print(f"error: {e} (is PipeWire/Pulse running?)",
                  file=sys.stderr)
            return 1
        print(f"default mic: {dm}\ndefault speaker: {ds}")
        for name, kind in rows:
            mark = ""
            if name == dm or name == ds:
                mark = "  [default]"
            print(f"[{kind:7}] {name}{mark}")
        print("\nuse: anim start eq --device '<part of name>'")
        return 0
    # level meter
    import time as _t
    feed = AudioFeed(args.source, args.gain, args.device)
    try:
        feed.start()
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"capturing: {feed.device_name} — play music, Ctrl+C to stop")
    try:
        end = _t.monotonic() + args.secs if args.secs else None
        while end is None or _t.monotonic() < end:
            feed.poll()
            bass = max(0.0, min(1.0, feed.band(40, 160) * args.gain))
            # peak across sub-bands: percussive highs are narrowband and a
            # wide mean would dilute them below visibility (the keyboard's
            # EQ columns are narrow for the same reason).
            mid = max(0.0, min(1.0, max(feed.band(250, 800),
                                        feed.band(800, 2000)) * args.gain))
            high = max(0.0, min(1.0, max(feed.band(2000, 4500),
                                         feed.band(4500, 9000)) * args.gain))
            bb, mb, hb = int(bass * 26), int(mid * 26), int(high * 26)
            print(f"\rbass [{'#' * bb:<26}] mid [{'#' * mb:<26}] "
                  f"high [{'#' * hb:<26}]", end="", flush=True)
            _t.sleep(0.05)
        print()
    except KeyboardInterrupt:
        print()
    finally:
        feed.stop()
    return 0


# ---------------------------------------------------------------- selftest
def cmd_selftest(_args):
    fails = []

    def check(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    from .transport import build_packet, packet_ok
    pkt = build_packet(0x44, 3, 1, 0x0E, bytes(range(14)))
    check("packet len/checksum", packet_ok(pkt) and len(pkt) == 20)
    bad = bytearray(pkt)
    bad[5] ^= 1
    check("checksum detects corruption", not packet_ok(bytes(bad)))
    check("hsv red", P.to_int8(P.hsv(0.0, 1, 1)) == (255, 0, 0))
    check("hsv cyan-ish", P.to_int8(P.hsv(0.5, 1, 1)) == (0, 255, 255))
    try:
        P.resolve_key("w"), P.resolve_key("Space"), P.resolve_key("lshift"), \
            P.resolve_key("pgdn"), P.resolve_key("Esc")
        check("key aliases", True)
    except KeyError:
        check("key aliases", False)
    try:
        bad_key = False
        try:
            P.resolve_key("notakey")
            bad_key = True
        except KeyError:
            pass
        check("unknown key rejected", not bad_key)
    except Exception:
        check("unknown key rejected", False)
    check("parse #rrggbb", P.parse_color("#89b4fa") == (0x89, 0xB4, 0xFA))
    led, col = P.parse_key_color("W=#ff0000")
    check("parse NAME=COLOR",
          led == P.resolve_key("w") and col == (255, 0, 0))
    check("media spec", K.parse_spec("media:playpause") == bytes([2, 0, 0, 0xCD]))
    check("key+mods spec",
          K.parse_spec("key:a+ctrl+shift") == bytes([0, 0x03, 0, 0x04]))
    check("off spec", K.parse_spec("off") == bytes(4))
    check("describe", K.describe(bytes([0, 1, 0, 4])) == "ctrl+A")
    demo = {e[6]: (255, 0, 0) if i % 2 else (0, 0, 255)
            for i, e in enumerate(P.LAYOUT)}
    enc = A.encode_groups(demo)
    check("encode_groups fits", enc is not None and len(enc) <= P.RT_MAX)
    if enc:
        back = {}
        i = 0
        while i < len(enc):
            r, g, b, cnt = enc[i], enc[i + 1], enc[i + 2], enc[i + 3]
            for l in enc[i + 4:i + 4 + cnt]:
                back[l] = (r, g, b)
            i += 4 + cnt
        check("encode_groups roundtrip",
              all(back.get(l) == demo[l] for l in demo))
    custom = u_build_led_custom(1, 2, 3)
    check("wired custom pkt",
          len(custom) == 520 and custom[514] == 0x5A and custom[515] == 0xA5)
    planar = u_build_led_planar({0: (255, 0, 0), 125: (0, 0, 255)})
    check("wired planar pkt",
          len(planar) == 520 and planar[8] == 255 and
          planar[8 + 2 * 126 + 125] == 255)
    direct = u_build_direct_frame({0: (1, 2, 3), 10: (4, 5, 6)})
    check("wired direct pkt",
          len(direct) == 520 and direct[0] == 0x06 and direct[1] == 0x08
          and direct[8:11] == bytes((1, 2, 3))
          and direct[8 + 30:8 + 33] == bytes((4, 5, 6)))
    cfg = bytes(136)
    wr = u_build_config_write(cfg, 1, 4)
    check("wired config static", wr[17] == 0 and wr[18] == 1 and wr[66] == 4)
    wr2 = u_build_config_write(cfg, 18, 4, custom=True)
    check("wired config custom",
          wr2[17] == 1 and wr2[18] == 18 and wr2[100] == 4)
    check("wireless->wired plane map", len(P.WIRELESS_TO_WIRED_PLANE) > 60)
    check("effect table",
          P.EFFECT_BY_NAME["static"]["mode"] == 1 and
          P.EFFECT_BY_MODE[21].get("custom"))
    check("sleep table", P.SLEEP_SECS_TO_HW[60] == 2)
    try:
        import numpy as _np
        from .audio import AudioFeed as _AF
        _f = _AF("monitor", 1.0)
        _f._bins = _np.zeros(1024)
        check("audio silence gated", _f.band(40, 160) == 0.0)
        _f._bins = _np.full(1024, 89.0)  # ~analog idle noise floor
        check("audio idle noise gated", _f.band(40, 160) < 0.05)
        _f._bins = _np.full(1024, 255.0)
        check("audio peaks pass", _f.band(40, 160) > 0.95)
    except ImportError:
        print("SKIP audio gate checks (no numpy)")
    if fails:
        print(f"{len(fails)} FAILURES", file=sys.stderr)
        return 1
    print("all selftests passed")
    return 0


# ---------------------------------------------------------------- parser
def build_parser():
    ap = argparse.ArgumentParser(
        prog="aula", description="AULA F75 Pro CLI — lighting, effects, "
        "per-key colors, remap, settings, live animations (2.4GHz + wired)")
    ap.add_argument("--transport", default="auto",
                    choices=["auto", "2.4g", "wired"],
                    help="connection to use (default: auto-detect)")
    ap.add_argument("--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("color", help="one-shot static / per-key color")
    c.add_argument("base", nargs="?",
                   help="base hex color for all keys, e.g. '#89b4fa'")
    c.add_argument("--key", action="append", default=[],
                   help="per-key override NAME=COLOR (repeatable)")
    c.add_argument("--brightness", type=int, default=None,
                   help="0-9 on 2.4GHz, 1-4 on wired")
    c.set_defaults(func=cmd_color)

    e = sub.add_parser("effect", help="firmware lighting effects")
    esub = e.add_subparsers(dest="action", required=True)
    esub.add_parser("list", help="list firmware effects")
    eset = esub.add_parser("set", help="apply a firmware effect")
    eset.add_argument("effect", help="name or mode number (see list)")
    eset.add_argument("--brightness", type=int, default=None,
                      help="0-9 (2.4GHz) / 1-4 (wired)")
    eset.add_argument("--speed", type=int, default=None, help="0-4")
    eset.add_argument("--color-index", type=int, default=None,
                      help="palette 0-6, 7 = multicolor")
    eset.add_argument("--color", default=None,
                      help="rewrite selected palette entry, hex")
    eset.add_argument("--multi", action="store_true",
                      help="switch to multicolor")
    eset.add_argument("--force", action="store_true",
                      help=argparse.SUPPRESS)  # probe firmware-missing modes
    e.set_defaults(func=cmd_effect)

    k = sub.add_parser("colors", help="paint per-key colors")
    k.add_argument("--all", default=None, metavar="HEX",
                   help="paint every key")
    k.add_argument("--key", action="append", default=[],
                   help="NAME=COLOR (repeatable)")
    k.add_argument("--preset", default=None, choices=["rainbow", "gradient"])
    k.add_argument("--color1", default=None)
    k.add_argument("--color2", default=None)
    k.add_argument("--clear", action="store_true", help="all keys black")
    k.set_defaults(func=cmd_colors)

    a = sub.add_parser("anim", help="live animations (keeps running)")
    asub = a.add_subparsers(dest="action", required=True)
    asub.add_parser("list", help="list live animations")
    astart = asub.add_parser("start", help="play a live animation")
    astart.add_argument("anim", help="animation id (see list)")
    astart.add_argument("--speed", type=float, default=1.0)
    astart.add_argument("--brightness", type=float, default=1.0)
    astart.add_argument("--color1", default="#ff2a00")
    astart.add_argument("--color2", default="#0050ff")
    astart.add_argument("--source", default="monitor",
                        choices=["monitor", "mic"],
                        help="audio input for eq/pulse")
    astart.add_argument("--device", default=None,
                        help="capture device name substring (see audio list)")
    astart.add_argument("--gain", type=float, default=1.0)
    astart.add_argument("--eq-style", default="rainbow",
                        choices=["rainbow", "gradient", "solid"],
                        help="eq bar coloring (gradient/solid use "
                        "--color1/--color2/--color1)")
    astart.add_argument("--peak-fall", action=argparse.BooleanOptionalAction,
                        default=True,
                        help="slow-falling eq bars + white peak caps "
                        "(--no-peak-fall for instant bars)")
    astart.add_argument("--time", type=float, default=0,
                        help="stop after N seconds (0 = run until stopped)")
    astart.add_argument("--daemon", action="store_true",
                        help="run detached in background")
    astart.add_argument("--daemon-child", action="store_true",
                        help=argparse.SUPPRESS)
    asub.add_parser("stop", help="stop the background animation")
    a.set_defaults(func=cmd_anim)

    m = sub.add_parser("keys", help="key remapping (2.4GHz only)")
    msub = m.add_subparsers(dest="action", required=True)
    mshow = msub.add_parser("show", help="show current layer mapping")
    mshow.add_argument("--layer", default="normal", choices=["normal", "fn"])
    mset = msub.add_parser("set", help="remap one key")
    mset.add_argument("key", help="physical key name, e.g. CapsLock")
    mset.add_argument("spec", help="key:A+ctrl | media:playpause | "
                      "mouse:left | cmd:altf4 | special:fxnext | off | fn")
    mset.add_argument("--layer", default="normal", choices=["normal", "fn"])
    mset.add_argument("--force", action="store_true",
                      help="allow overwriting the Fn key")
    mrk = msub.add_parser("reset-key",
                          help="restore one key from auto-backup")
    mrk.add_argument("key")
    mrk.add_argument("--layer", default="normal", choices=["normal", "fn"])
    mrl = msub.add_parser("reset-layer",
                          help="restore a layer from auto-backup")
    mrl.add_argument("--layer", default="normal", choices=["normal", "fn"])
    msub.add_parser("types", help="list remap spec types and ids")
    m.set_defaults(func=cmd_keys)

    s = sub.add_parser("sleep", help="sleep timer (2.4GHz only)")
    ssub = s.add_subparsers(dest="action", required=False)
    ssub.add_parser("get").set_defaults(seconds=None, raw=None)
    sset = ssub.add_parser("set")
    sset.add_argument("seconds", nargs="?", type=int, default=None)
    sset.add_argument("--raw", type=int, default=None)
    s.set_defaults(func=cmd_sleep, action="get", seconds=None, raw=None)

    sub.add_parser("battery", help="battery readout (2.4GHz only)"). \
        set_defaults(func=cmd_battery)
    sub.add_parser("status", help="show effect/brightness/sleep/battery"). \
        set_defaults(func=cmd_status)

    u = sub.add_parser("audio", help="audio capture diagnostics")
    usub = u.add_subparsers(dest="action", required=True)
    usub.add_parser("list", help="list capture devices/monitors")
    ulevel = usub.add_parser("level", help="live input meter (play music)")
    ulevel.add_argument("--source", default="monitor",
                        choices=["monitor", "mic"])
    ulevel.add_argument("--device", default=None,
                        help="device name substring")
    ulevel.add_argument("--gain", type=float, default=1.0)
    ulevel.add_argument("--secs", type=float, default=0,
                        help="stop after N seconds (0 = until Ctrl+C)")
    u.set_defaults(func=cmd_audio)
    sub.add_parser("selftest", help="protocol self-test, no hardware"). \
        set_defaults(func=cmd_selftest)
    return ap


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    from .transport import ABORT
    ABORT.clear()
    try:
        rc = args.func(args)
    except CommError as e:
        if str(e) == "interrupted":
            print("interrupted", file=sys.stderr)
            return 130
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except BrokenPipeError:
        return 1
    return rc or 0

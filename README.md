# AULA F75 Pro CLI

Python CLI rebuilt from reverse-engineered AULA configurators
(see `other/`), in the style of `other/old/aula.py`. One-shot commands send
their change and disconnect; live animations keep running (foreground or
`--daemon`) and restore your lighting on exit (2.4GHz) or auto-revert
(wired direct mode).

## Setup

```bash
cd ~/Projects/aula_reverse
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

(`hidapi` = 2.4GHz dongle + wired feature reports, `numpy` = animations /
audio FFT, `soundcard` = monitor/mic capture, `evdev` = optional
real-keypress ripples.)

udev rules are already installed (`/etc/udev/rules.d/` — see
`70-aula-f75.rules` here for reference). Unplug/replug the dongle after
installing them.

Run it (no venv activation needed):

```bash
./.venv/bin/aula status
./.venv/bin/aula --transport 2.4g anim start fire --daemon
```

With the venv activated (`source .venv/bin/activate`), just `aula …`.
The package is `aula/`; reference clones live in `other/` (git-ignored).

## Usage

```bash
aula color '#89b4fa'                          # static, all keys
aula color --key W=#ff0000 --key E=#00ff00    # per-key (+ optional base)
aula color '#000000' --brightness 4           # brightness 0-9 (2.4G), 1-4 (wired)

aula effect list
aula effect set breathing --brightness 6 --speed 2 --color-index 3
aula effect set static --color-index 2 --color '#00ff00'   # edit palette entry
aula effect set rainbow --multi 2>/dev/null || true        # rainbow has no color opts

aula colors --all '#ff3000'
aula colors --preset rainbow | --preset gradient --color1 R --color2 B
aula colors --key A=#00ff00 --key S=#0000ff
aula colors --clear

aula anim list
aula anim start wave [--speed 1.5 --brightness 0.8 --color1 R --color2 B]
aula anim start eq --source monitor --gain 2      # or --source mic
aula anim start eq --device 'HDMI'                # capture a specific sink
aula audio list                                   # show capture devices
aula audio level --source monitor                 # live meter: play music,
                                                  # pick the device that moves
aula anim start type                               # ripples (evdev or auto)
aula anim start fire --daemon --time 0             # background; --time SECS to auto-stop
aula anim stop

aula keys show [--layer normal|fn]
aula keys set CapsLock key:esc                    # key:A[+ctrl+shift+alt+win...]
aula keys set F12 media:playpause | mouse:left | cmd:altf4 | special:fxnext | off
aula keys reset-key F12 [--layer normal]          # restore one key from auto-backup
aula keys reset-layer [--layer fn]
aula keys types                                   # all spec ids

aula sleep get
aula sleep set 120                                # 60,90,120,180,240,300,600,900,1200 (or --raw N)
aula battery
aula status
aula selftest                                     # no-hardware protocol checks
```

Global flags: `--transport auto|2.4g|wired` (default auto),
`--verbose`.

## Behavior notes

- **Keyboard must be awake.** If it slept (default timer 60 s), press any
  physical key once, then run the command. Long writes can race the sleep
  timer — on `comm` errors, wake it and retry.
- **First read auto-backs up** to `~/.config/aula-f75/auto-backup-<mode>.json`
  (mirrors the web client's auto-backup). `keys reset-*` and all animation
  restores use it; nothing is ever uploaded anywhere.
- **Animations restore lighting on exit** (foreground Ctrl+C, `anim stop`,
  SIGTERM). Daemon state: `~/.config/aula-f75/anim.pid`, log `anim.log`.
- **Typing ripples** use real keypresses via evdev when permitted, otherwise
  automatic ripples. For real input: `sudo usermod -aG input $USER`, relog, and
  the daemon/context must read `/dev/input/*`.
- **Audio anims** (`eq`, `pulse`): `--source monitor` captures system output
  via PipeWire/Pulse loopback, `mic` the microphone. `--gain 0.5-5`
  (default 1.0). Monitor idle noise is gated to silence, so quiet parts
  fade instead of parking the keyboard on full colors.
- **Wired (258A:010C)** supports `color`, `colors`, `effect set`
  (best-effort: mode/brightness via config block, palette+speed may not
  apply). Single-shot commands use detach-free hidraw feature reports, so
  typing is never interrupted. `keys`/`sleep`/`battery` are 2.4GHz-only —
  no remap/power protocol is known for wired. **Live `anim`s use direct
  mode** (`0x08` frames, temporary overlay with ~1s auto-revert — no
  config writes, nothing stored to lose), same mechanism as f87d on this
  chip family; all 80 keys are mapped. Hardware-verified (wave flows,
  typing alive throughout).
- **No named profiles** (per design decision): only the automatic backup.
- Macros are unsupported, same as the web configurator.

## Layout

```
aula/
  protocol.py    constants, EFFECTS/LAYOUT/keycode tables, color math
  transport.py   hidapi: 2.4G 20-byte protocol + wired feature reports
  state.py       block read/write/verify, auto-backup
  lighting.py    effects, brightness/speed/palette, sleep
  keys.py        remap SPEC <-> 4-byte codes
  audio.py       soundcard capture + FFT bands
  anims.py       10 animations, group encoder, runner, typing input
  daemon.py      double-fork, PID file, stop
  cli.py         argparse + commands
```

## Verified on hardware (2.4GHz dongle, 2026-10-11)

Read: `status` (storm/18, sleep 60 s, battery 100 %, 126 keys), `battery`,
`keys show` both layers, `sleep get`. Write (all restored byte-exact after):
effect change, per-key colors incl. readback, palette entry, remap
F12→F24→restore. Live: `cycle`/`wave`/`fire`/`type`/`eq` realtime frames,
foreground + `--daemon`/`stop` with restore. `selftest`: 22/22 pass.

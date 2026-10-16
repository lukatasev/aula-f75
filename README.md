# AULA F75 Pro CLI

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)

Command-line control for the AULA F75 Pro keyboard on Linux: static colors,
firmware effects, per-key painting, key remapping, sleep timer, battery —
plus live animations, including music-reactive ones. Works over the
**2.4GHz dongle** and **wired USB**, with no vendor software, no daemon
required for one-shot commands, and nothing ever leaving your machine.

## Features

- **Static & per-key colors** — whole board or individual keys, presets included
- **All 18 firmware effects** (static, breathing, rainbow, snake, reactive…) with brightness, speed, palette control
- **21 live animations** — wave, fire, meteor shower, matrix rain, plasma, radar, lightning, typing ripples, Game of Life, 5 music visualizers and more; foreground or background (`--daemon`)
- **Key remapping** on normal and Fn layers (keys, media, mouse, shortcuts, special functions)
- **Settings** — sleep timer, battery readout, auto-backup with one-key restore

## Requirements

System packages (Arch shown; any distro works):

```bash
sudo pacman -S python libusb hidapi libpulse
```

| Python package | Used for |
|---|---|
| `hidapi` | 2.4GHz dongle + wired USB transport |
| `numpy` | animation math + audio FFT |
| `soundcard` | system-output/mic capture for music anims |
| `evdev` *(optional)* | real keypresses for typing-reactive anims |

## Installation

```bash
git clone https://github.com/lukatasev/aula-f75
cd aula-f75
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

Allow user-space USB access (once), then replug the keyboard/dongle:

```bash
sudo cp 70-aula-f75.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Run it:

```bash
./aulaf75 status
```

With the venv activated (`source .venv/bin/activate`), drop the prefix: `aulaf75 status`.
To run it from anywhere without activation (no `./`, no venv):

```bash
mkdir -p ~/.local/bin
ln -s "$PWD/.venv/bin/aulaf75" ~/.local/bin/aulaf75
```

(ensure `~/.local/bin` is on your `PATH`.) All examples below use `./aulaf75`.

## Usage

```bash
./aulaf75 color '#89b4fa'                          # static, all keys
./aulaf75 color --key W=#ff0000 --key E=#00ff00    # per-key (+ optional base)
./aulaf75 color '#000000' --brightness 4           # brightness 0-9 (2.4G), 1-4 (wired)

./aulaf75 effect list
./aulaf75 effect set breathing --brightness 6 --speed 2 --color-index 3
./aulaf75 effect set static --color-index 2 --color '#00ff00'   # edit palette entry

./aulaf75 colors --all '#ff3000'
./aulaf75 colors --preset rainbow | --preset gradient --color1 R --color2 B
./aulaf75 colors --key A=#00ff00 --key S=#0000ff
./aulaf75 colors --clear

./aulaf75 anim list
./aulaf75 anim start wave [--speed 1.5 --brightness 0.8 --color1 R --color2 B]
./aulaf75 anim start eq --source monitor --gain 2      # or --source mic
./aulaf75 anim start eq --device 'HDMI'                # capture a specific sink
./aulaf75 audio list                                   # show capture devices
./aulaf75 audio level --source monitor                 # live meter: play music,
                                                    # pick the device that moves
./aulaf75 anim start fire --daemon --time 0             # background; --time SECS to auto-stop
./aulaf75 anim stop

./aulaf75 keys show [--layer normal|fn]
./aulaf75 keys set CapsLock key:esc                    # key:A[+ctrl+shift+alt+win...]
./aulaf75 keys set F12 media:playpause | mouse:left | cmd:altf4 | special:fxnext | off
./aulaf75 keys reset-key F12 [--layer normal]          # restore one key from auto-backup
./aulaf75 keys reset-layer [--layer fn]
./aulaf75 keys types                                   # all spec ids

./aulaf75 sleep get
./aulaf75 sleep set 120                                # 60,90,120,180,240,300,600,900,1200 (or --raw N)
./aulaf75 battery
./aulaf75 status
./aulaf75 selftest                                     # no-hardware protocol checks
```

Global flags: `--transport auto|2.4g|wired` (default auto),
`--verbose`.

Key names accept plain words, so shell quoting is never a fight:
`--key '8,9,minus,equal,u,i,o,p,lbracket,rbracket,j,k,l,quote,semicolon=#ff0000'`.

## Behavior notes

- **Keyboard must be awake.** If it slept (default timer 60 s), press any
  physical key once, then run the command. Long writes can race the sleep
  timer — on `comm` errors, wake it and retry.
- **First read auto-backs up** to `~/.config/aula-f75/auto-backup-<mode>.json`.
  `keys reset-*` and animation restores use it; nothing is ever uploaded anywhere.
- **Animations restore lighting on exit** (foreground Ctrl+C, `anim stop`,
  SIGTERM). Wired animations are a temporary overlay that auto-reverts in ~1 s.
  Daemon state: `~/.config/aula-f75/anim.pid`, log `anim.log`.
- **Known limitation: media keys + volume knob go quiet while a live
  animation streams** (both transports; letter keys unaffected). The
  firmware deprioritizes consumer input while sinking continuous LED
  traffic, at any frame rate — no client-side fix. Use firmware effects
  (`effect set …`) when media controls must stay alive.
- **Typing ripples** use real keypresses via evdev when permitted, otherwise
  automatic ripples. For real input: `sudo usermod -aG input $USER`, then relog.
- **Audio anims** (`eq`, `pulse`, `vu`, `energy`, `freqmap`): `--source monitor`
  captures system output via PipeWire/Pulse loopback, `mic` the microphone.
  `--gain 0.5-5` (default 1.0). Monitor idle noise is gated to silence, so
  quiet parts fade instead of parking the keyboard on full colors.
- **Wired (258A:010C)** supports `color`, `colors`, `effect set`
  (best-effort: mode/brightness via config block) and live `anim`s via direct
  mode. `keys`/`sleep`/`battery` are 2.4GHz-only — no remap/power protocol is
  known for wired.
- Macros are unsupported, same as the web configurator.

## Verified on hardware

2.4GHz reads/writes (restored byte-exact), per-key readback, remap round-trip,
realtime animations foreground + daemon with restore; wired status, direct-mode
animations with typing alive throughout. `selftest` covers the protocol without
hardware and runs in CI.

## Credits

Protocol groundwork by others: [trueig's AULA-F75-configurator](https://github.com/trueig/AULA-F75-configurator)
(2.4GHz WebHID protocol) and [veysiemrah/aula-rgb-controller](https://github.com/veysiemrah/aula-rgb-controller).
This CLI re-implements it all in Python.

## License

MIT — see [LICENSE](LICENSE).

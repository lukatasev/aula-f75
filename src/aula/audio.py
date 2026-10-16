"""Audio capture for music-reactive animations.

PipeWire/Pulse via the `soundcard` package + numpy FFT, mirroring the
web client's AnalyserNode (fftSize 2048, smoothing 0.5).
"""

from __future__ import annotations

import threading

SR = 48000
FFT = 2048
SMOOTH = 0.5


class AudioFeed:
    def __init__(self, source: str = "monitor", gain: float = 1.0,
                 device: str | None = None):
        if source not in ("monitor", "mic"):
            raise ValueError("source is monitor|mic")
        self.source = source
        self.gain = gain
        self.want_device = device
        self.device_name = None
        self._rec = None
        self._bins = None
        self._prev = None
        self._window = None
        self._thread = None
        self._stop_ev = threading.Event()
        self._lock = threading.Lock()
        self._sr = SR

    # Noise gate (byte scale): analog monitor idle noise sits ~0.30-0.40
    # here, so anything at/below GATE reads as silence instead of pinning
    # the meter forever.
    GATE = 0.35

    def start(self):
        import soundcard as sc
        if self.want_device:
            mic = _find_device(sc, self.want_device)
            if mic is None:
                avail = ", ".join(m.name for m in
                                  _all_inputs(sc)) or "none"
                raise RuntimeError(
                    f"audio device matching {self.want_device!r} not found "
                    f"(have: {avail})")
        elif self.source == "mic":
            mic = sc.default_microphone()
            if mic is None:
                raise RuntimeError("no microphone found")
        else:
            mic = _loopback_for_default_speaker(sc)
            if mic is None:
                raise RuntimeError(
                    "no monitor (loopback) source found - is PipeWire/Pulse "
                    "running? fall back to --source mic")
        self.device_name = getattr(mic, "name", "?")
        self._rec = mic.recorder(samplerate=self._sr, channels=1,
                                 blocksize=FFT)
        self._rec.__enter__()
        import numpy as np
        self._bins = np.zeros(FFT // 2, dtype=float)
        self._window = np.blackman(FFT)
        # Realtime capture thread: the animation loop spends ~150 ms per
        # frame (USB pacing) but 2048 frames are only 43 ms of audio, so
        # polling from the loop would fall behind more every frame and the
        # delay would grow without bound. The thread consumes in real time;
        # pollers only read the latest spectrum via band().
        self._stop_ev = threading.Event()
        self._thread = threading.Thread(target=self._capture, daemon=True)
        self._thread.start()

    def stop(self):
        ev = getattr(self, "_stop_ev", None)
        if ev is not None:
            ev.set()
        th = getattr(self, "_thread", None)
        if th is not None:
            th.join(timeout=2.0)
            self._thread = None
        rec, self._rec = self._rec, None
        if rec is not None:
            try:
                rec.__exit__(None, None, None)
            except Exception:
                pass

    def _capture(self):
        import numpy as np
        window = np.blackman(FFT)
        while not self._stop_ev.is_set():
            try:
                data = self._rec.record(numframes=FFT)
            except Exception:
                break
            if data is None or not len(data):
                continue
            self._process(np.asarray(data[:, 0], dtype=float), window,
                          np)

    def poll(self):
        """Manual single step (diagnostics/tests).

        No-op while the background capture thread runs; band() always
        serves the latest spectrum.
        """
        th = getattr(self, "_thread", None)
        if th is not None and th.is_alive():
            return
        import numpy as np
        if self._rec is None:
            return
        if getattr(self, "_window", None) is None:
            self._window = np.blackman(FFT)
        data = self._rec.record(numframes=FFT)
        if data is None or not len(data):
            return
        self._process(np.asarray(data[:, 0], dtype=float), self._window,
                      np)

    def _process(self, mono, window, np):
        # Stall guard: when the monitored stream idles, some backends keep
        # handing back the last buffered block instead of fresh silence.
        # Bit-identical consecutive blocks never happen on a live stream,
        # so treat them as silence and let the levels decay.
        if self._prev is not None and mono.shape == self._prev.shape and \
                np.array_equal(mono, self._prev):
            mono = np.zeros_like(mono)
        else:
            self._prev = mono.copy()
        # Blackman window like AnalyserNode: without it, loud bass leaks
        # across the whole spectrum and every band reads hot.
        windowed = mono * window
        mag = np.abs(np.fft.rfft(windowed, n=FFT)) / (FFT / 2)
        # +3 dB/octave whitening: mean power-per-Hz over log bands tilts
        # down ~3 dB/oct on pink-ish music, burying highs. Tilt first so
        # highs dance as hard as bass on real mixes.
        freqs = np.fft.rfftfreq(FFT, 1.0 / self._sr)
        tilt = np.sqrt(np.maximum(freqs, 1.0) / 1000.0)
        mag = mag * tilt
        mag = mag[1:FFT // 2 + 1]  # drop DC, keep 1024 bins like the browser
        # dB bytes, browser-style mapping but with the ceiling at full
        # scale (0 dBFS): the browser's -30 dB ceiling saturates on any
        # modern mastered mix, pinning every band.
        with np.errstate(divide="ignore"):
            db = 20.0 * np.log10(np.maximum(mag, 1e-5))
        scaled = np.clip((db + 100.0) * 255.0 / 100.0, 0, 255)
        with self._lock:
            self._bins = SMOOTH * self._bins + (1 - SMOOTH) * scaled

    def band(self, f0: float, f1: float) -> float:
        """Gated mean bin level (0-1).

        0 = silence/monitor idle noise, ~1 = full-scale peaks. Multiply
        by --gain downstream (default 1.0).
        """
        import numpy as np
        with self._lock:
            bins = None if self._bins is None else self._bins.copy()
        if bins is None:
            return 0.0
        nyq = self._sr / 2
        n = len(bins)
        i0 = max(1, int(f0 / nyq * n))
        i1 = max(i0 + 1, int(f1 / nyq * n) + 1)
        i1 = min(i1, n)
        if i0 >= n:
            return 0.0
        raw = float(np.mean(bins[i0:i1])) / 255.0
        return min(1.0, max(0.0, (raw - self.GATE) / (1.0 - self.GATE)))


def _all_inputs(sc):
    try:
        return list(sc.all_microphones(include_loopback=True))
    except Exception:
        return []


def _find_device(sc, substr: str):
    substr = substr.lower()
    for m in _all_inputs(sc):
        if substr in (getattr(m, "name", "") or "").lower():
            return m
    return None


def list_sources():
    """(default_mic, default_speaker, [(name, kind)]) for diagnostics."""
    import soundcard as sc
    try:
        dm = sc.default_microphone()
        dm = getattr(dm, "name", None)
    except Exception:
        dm = None
    try:
        ds = sc.default_speaker()
        ds = getattr(ds, "name", None)
    except Exception:
        ds = None
    rows = []
    for m in _all_inputs(sc):
        name = getattr(m, "name", "?") or "?"
        nl = name.lower()
        kind = "monitor" if ("monitor" in nl or "loopback" in nl
                             or (ds and name == ds)) else "input"
        rows.append((name, kind))
    return dm, ds, rows


def _loopback_for_default_speaker(sc):
    try:
        spk = sc.default_speaker()
    except Exception:
        spk = None
    cands = []
    try:
        cands = sc.all_microphones(include_loopback=True)
    except Exception:
        return None
    if spk is not None:
        for m in cands:
            if getattr(m, "name", "") == getattr(spk, "name", None):
                return m
        for m in cands:
            name = (getattr(m, "name", "") or "").lower()
            if "monitor" in name or "loopback" in name or "output" in name:
                return m
    for m in cands:
        name = (getattr(m, "name", "") or "").lower()
        if "monitor" in name:
            return m
    return cands[0] if cands else None

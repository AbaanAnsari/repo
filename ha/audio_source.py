"""Audio sources returning float32 arrays [M, n] in [-1,1]."""
import subprocess, time, wave, re
import numpy as np
from .geometry import Array

class ALSASource:
    def __init__(self, cfg):
        a = cfg["alsa"]; self.fs = cfg["sample_rate"]; self.nch = a["channels"]
        self.M = len(cfg["array"]["mic_angles_deg"]); self.bits = a["bits"]
        self.dev = a["device"] if a["device"] != "auto" else self._find_device()
        self.fmt = a["format"]
        self.map = a["channel_map"]
        self.buf = b""
        self.proc = subprocess.Popen(
            ["arecord", "-q", "-D", self.dev, "-c", str(self.nch), "-r", str(self.fs),
             "-f", self.fmt, "-t", "raw", "--buffer-size", "16384"],
            stdout=subprocess.PIPE, bufsize=0)
        if self.map == "auto":
            self.map = self._probe()
        self.map = list(self.map)
        self.name = f"ALSA {self.dev} ch{self.map}"

    @staticmethod
    def _find_device():
        out = subprocess.run(["arecord", "-l"], capture_output=True, text=True).stdout
        if "mic4" in out:
            return "hw:CARD=mic4,DEV=0"
        for line in out.splitlines():
            m = re.match(r"card (\d+): (\S+) .*device (\d+)", line)
            if m and not any(k in line.lower() for k in ("hdmi", "usb", "headphones")):
                return f"hw:{m.group(1)},{m.group(3)}"
        raise RuntimeError("No I2S capture card found (arecord -l). Run tools/hw_check.py")

    def _raw(self, n):
        need = n * self.nch * 4
        while len(self.buf) < need:
            d = self.proc.stdout.read(need - len(self.buf))
            if not d:
                raise RuntimeError("arecord stopped (device busy/unsupported format?)")
            self.buf += d
        d, self.buf = self.buf[:need], self.buf[need:]
        x = np.frombuffer(d, dtype="<i4").reshape(-1, self.nch).T.astype(np.float32)
        return x / 2147483648.0

    def _probe(self):
        x = self._raw(self.fs)[:, 2000:]
        s = x.std(axis=1)
        live = [int(c) for c in np.argsort(-s)[: self.M] if s[c] > 1e-7]
        if len(live) < self.M:
            raise RuntimeError(f"Only {len(live)} live channels found (std={s}). Check wiring/overlay; run tools/hw_check.py")
        return sorted(live)

    def read(self, n):
        return self._raw(n)[self.map]

    def close(self):
        self.proc.kill()


class _Paced:
    def pace(self, n):
        self._t = getattr(self, "_t", time.time()) + n / self.fs
        d = self._t - time.time()
        if d > 0: time.sleep(d)
        elif d < -1: self._t = time.time()


class WavSource(_Paced):
    def __init__(self, cfg, path):
        w = wave.open(path); self.fs = w.getframerate(); ch = w.getnchannels()
        raw = np.frombuffer(w.readframes(w.getnframes()), "<i2" if w.getsampwidth() == 2 else "<i4")
        self.x = (raw.reshape(-1, ch).T.astype(np.float32) / (2 ** (8 * w.getsampwidth() - 1)))[: len(cfg["array"]["mic_angles_deg"])]
        self.i = 0; self.name = f"WAV {path}"

    def read(self, n):
        idx = (np.arange(self.i, self.i + n)) % self.x.shape[1]; self.i += n
        self.pace(n); return self.x[:, idx]
    def close(self): pass


class SimSource(_Paced):
    """Synthetic speech-like target + interferer + diffuse noise, exact fractional delays."""
    def __init__(self, cfg, realtime=True, seed=0):
        self.fs = cfg["sample_rate"]; self.arr = Array(cfg); self.cfg = cfg["sim"]
        self.rng = np.random.default_rng(seed); self.t = 0; self.realtime = realtime
        self.name = "SIMULATION"; self.truth = self.cfg["target_deg"]
        self.last_target = None; self.last_interf = None

    def _voice(self, n, f0, off):
        t = (np.arange(n) + off) / self.fs
        env = np.clip(np.sin(2 * np.pi * 3.1 * t + f0) + 0.4, 0, 1)
        ph = 2 * np.pi * f0 * t + 3 * np.sin(2 * np.pi * 0.7 * t)
        s = sum(np.sin(k * ph) / k ** 0.8 for k in range(1, 40) if k * f0 < self.fs / 2.2)
        return env * s

    def _delay(self, s, taus):
        n = len(s); S = np.fft.rfft(s); f = np.fft.rfftfreq(n, 1 / self.fs)
        return np.fft.irfft(S[None] * np.exp(-2j * np.pi * f[None] * taus[:, None]), n, axis=1)

    def read(self, n):
        pad = 256; N = n + 2 * pad; sc = self.cfg
        tgt = sc["target_deg"] + (35 * np.sin(2 * np.pi * self.t / self.fs / 12) if sc.get("move") else 0)
        self.truth = float(tgt % 360)
        s1 = self._voice(N, 120.0, self.t - pad)
        s2 = self._voice(N, 210.0, self.t - pad + 5000) * 0.7
        t1 = self.arr.arrival_times(np.deg2rad(tgt)); t2 = self.arr.arrival_times(np.deg2rad(sc["interferer_deg"]))
        a = self._delay(s1, t1)[:, pad:pad + n]; b = self._delay(s2, t2)[:, pad:pad + n]
        a *= 0.05 / (np.sqrt(np.mean(a ** 2)) + 1e-9)
        b *= 0.5 * 0.05 / (np.sqrt(np.mean(b ** 2)) + 1e-9)   # interferer 6 dB below target
        self.last_target, self.last_interf = a.copy(), b.copy()   # for evaluation
        noise = self.rng.standard_normal(a.shape) * 0.05 * 10 ** (-sc["snr_db"] / 20)
        self.t += n
        if self.realtime: self.pace(n)
        return (a + b + noise).astype(np.float32)
    def close(self): pass
